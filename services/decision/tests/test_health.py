"""Stage 1 foundation: the health check, plus the logging/metrics responsibility."""

from __future__ import annotations

import pytest

from layasdlc import (
    ControllerConfig,
    DeterministicEngine,
    FakeEngine,
    Measurement,
    Metrics,
    PolicyConfig,
    ToolPermissionPolicy,
    Usage,
    WorkflowController,
    get_logger,
    health_check,
    is_healthy,
)
from layasdlc.engines.fake import answer


def make_controller(*, engine_available: bool = True) -> WorkflowController:
    return WorkflowController(
        engine=FakeEngine(is_available=engine_available, name="fake"),
        config=ControllerConfig(),
        fallback=DeterministicEngine(),
        permissions=ToolPermissionPolicy.read_only(),
    )


# --- health -----------------------------------------------------------------------------


def test_health_reports_ok_when_the_engine_is_available():
    document = health_check(controller=make_controller())
    assert document["status"] == "ok"
    assert is_healthy(document) is True
    assert document["engine"] == {"name": "fake", "version": "test-only", "available": True}


def test_health_reports_degraded_not_ok_when_the_engine_is_not_available():
    document = health_check(controller=make_controller(engine_available=False))
    assert document["status"] == "degraded"
    assert is_healthy(document) is False
    assert document["engine"]["available"] is False


def test_health_never_hides_a_throwing_probe():
    class Exploding:
        name = "exploding"
        version = "0"

        def available(self):
            raise RuntimeError("probe blew up")

        def decide(self, request):  # pragma: no cover - not exercised
            raise AssertionError

    document = health_check(engine=Exploding())
    assert document["status"] == "degraded"
    assert "probe_error" in document["engine"]
    assert "RuntimeError" in document["engine"]["probe_error"]


def test_health_identifies_the_fallback_separately_from_the_primary():
    document = health_check(controller=make_controller(engine_available=False))
    assert document["fallback"]["name"] == "deterministic"
    assert document["fallback"]["available"] is True, \
        "a caller must be able to tell 'Laya is answering' from 'baseline only'"


def test_health_declares_its_contract_and_capabilities():
    document = health_check(controller=make_controller())
    assert document["schema_version"]
    assert document["service"]
    assert set(document["capabilities"]["decision_types"]) == {
        "task_classification", "workflow_selection", "retry_vs_escalate",
        "context_priority",
    }
    assert document["capabilities"]["options"]["task_classification"][0] == "bug_fix"


def test_health_reports_configuration_and_runtime():
    document = health_check(controller=make_controller())
    assert document["permissions"] == ["read_investigate"]
    assert document["policy"]["min_confidence"] == PolicyConfig().min_confidence
    assert document["policy"]["timeout_s"] == ControllerConfig().timeout_s
    assert document["runtime"]["python"]


def test_health_document_is_json_serialisable():
    import json
    json.dumps(health_check(controller=make_controller()))


def test_health_works_without_a_controller():
    document = health_check(engine=DeterministicEngine())
    assert document["status"] == "ok"
    assert "metrics" not in document


# --- metrics ----------------------------------------------------------------------------


def test_counters_track_outcomes_types_and_engines():
    metrics = Metrics()
    metrics.record(engine="fake", decision_type="task_classification",
                   outcome="decided", latency_ms=1.5,
                   usage=Usage(input_tokens=10, output_tokens=0))
    metrics.record(engine="deterministic", decision_type="task_classification",
                   outcome="fallback", latency_ms=0.2)

    assert metrics.counter("outcome.decided") == 1
    assert metrics.counter("outcome.fallback") == 1
    assert metrics.counter("engine.fake") == 1
    assert metrics.counter("usage.recorded") == 1
    assert metrics.counter("usage.missing") == 1


def test_absent_usage_is_counted_as_missing_not_as_zero():
    metrics = Metrics()
    measurement = metrics.record(engine="deterministic", decision_type="task_classification",
                                 outcome="fallback", latency_ms=0.1, usage=None)
    assert measurement.input_tokens is None
    assert measurement.usage_available is False
    assert metrics.counter("usage.recorded") == 0


def test_summary_reports_latency_and_token_totals():
    metrics = Metrics()
    metrics.record(engine="e", decision_type="task_classification", outcome="decided",
                   latency_ms=10.0, usage=Usage(input_tokens=100, output_tokens=0))
    metrics.record(engine="e", decision_type="task_classification", outcome="decided",
                   latency_ms=30.0, usage=Usage(input_tokens=50, output_tokens=0))

    summary = metrics.summary()
    assert summary["latency_ms"]["min"] == 10.0
    assert summary["latency_ms"]["max"] == 30.0
    assert summary["latency_ms"]["mean"] == 20.0
    assert summary["usage"]["input_tokens_total"] == 150
    assert summary["usage"]["missing"] == 0


def test_summary_on_an_empty_registry_is_safe_not_a_crash():
    summary = Metrics().summary()
    assert summary["measurements"] == 0
    assert summary["latency_ms"]["mean"] is None
    assert summary["usage"]["input_tokens_total"] is None


def test_error_reasons_are_counted_by_type():
    metrics = Metrics()
    metrics.record(engine="e", decision_type="task_classification", outcome="failed",
                   latency_ms=1.0, error="EngineTimeout[e]: too slow")
    assert metrics.counter("error.EngineTimeout[e]") == 1


def test_measurement_log_is_bounded():
    metrics = Metrics(max_measurements=3)
    for index in range(10):
        metrics.record(engine="e", decision_type="task_classification", outcome="decided",
                       latency_ms=float(index))
    assert len(metrics.measurements) == 3
    assert metrics.measurements[-1].latency_ms == 9.0  # newest retained


def test_timed_context_manager_measures_the_block():
    metrics = Metrics()
    with metrics.timed("e", "task_classification") as context:
        pass
    assert context["latency_ms"] >= 0.0


def test_reset_clears_everything():
    metrics = Metrics()
    metrics.record(engine="e", decision_type="task_classification", outcome="decided",
                   latency_ms=1.0)
    metrics.reset()
    assert metrics.summary()["measurements"] == 0
    assert metrics.counter("outcome.decided") == 0


def test_measurement_serialises_for_reporting():
    payload = Measurement(at="t", engine="e", decision_type="task_classification",
                          outcome="decided", latency_ms=1.0).to_dict()
    assert payload["engine"] == "e"
    assert payload["input_tokens"] is None


def test_logger_configuration_is_idempotent():
    first, second = get_logger("x"), get_logger("x")
    assert first is second, "the same suffix must resolve to the same logger"

    import logging
    root = logging.getLogger("layasdlc")
    before = len(root.handlers)
    for suffix in ("a", "b", "c", "d", "e"):
        get_logger(suffix)
    assert len(root.handlers) == before, \
        f"repeated get_logger() calls stacked handlers: {before} -> {len(root.handlers)}"
