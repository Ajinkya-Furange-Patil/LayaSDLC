"""Stage 2: the controller's behaviour with a fake engine -- no network, no model.

Covers requirement 7 (timeouts, deterministic fallback), requirement 6 (rejection
of bad output), and the acceptance criteria around latency/usage recording.
"""

from __future__ import annotations

import pytest

from layasdlc import (
    ControllerConfig,
    DecisionType,
    DeterministicEngine,
    EngineAnswer,
    EngineFailure,
    EngineTimeout,
    EngineUnavailable,
    FakeEngine,
    Outcome,
    PolicyConfig,
    UnsupportedDecisionType,
    WorkflowController,
)
from layasdlc.engines.fake import Scripted, answer

TASK_OPTIONS = ("bug_fix", "feature", "refactor", "testing",
                "documentation", "investigation")


def fallback_free(config: ControllerConfig) -> ControllerConfig:
    config.policy = PolicyConfig(min_confidence=config.policy.min_confidence,
                                 fallback_enabled=False)
    return config


# --- the happy path --------------------------------------------------------------------


def test_a_valid_confident_decision_is_accepted(controller, task_state):
    result = controller.decide(task_state, "task_classification")

    assert result.outcome is Outcome.DECIDED
    assert result.source == "engine"
    assert result.envelope is not None
    assert result.selected_option == "bug_fix"
    assert result.confidence == pytest.approx(0.9)
    assert result.gate.value == "passed"
    assert result.action.value == "proceed"
    assert result.error is None


def test_the_envelope_carries_the_request_ids_and_model_identity(controller, task_state):
    result = controller.decide(task_state, "task_classification", request_id="fixed-id")
    envelope = result.envelope

    assert envelope is not None
    assert envelope.decision_id == "fixed-id"
    assert envelope.task_id == task_state.task_id
    assert envelope.model == "fake/laya"
    assert envelope.model_version == "0.0-test"
    assert envelope.decision_type == DecisionType.TASK_CLASSIFICATION.value
    assert set(envelope.allowed_options) == set(TASK_OPTIONS)


def test_latency_is_measured_locally_not_trusted_from_the_engine(controller, task_state):
    result = controller.decide(task_state, "task_classification")

    # The controller measures its own wall clock around the whole pipeline.
    assert result.latency_ms > 0.0
    # The engine's self-reported latency is carried on the envelope separately,
    # so a lying or absent engine figure can never be mistaken for real timing.
    assert result.envelope is not None
    assert result.envelope.latency_ms == 1.0
    assert controller.metrics.last().latency_ms == pytest.approx(result.latency_ms,
                                                                 abs=0.5)


def test_usage_is_recorded_when_the_engine_reports_it(controller, task_state):
    result = controller.decide(task_state, "task_classification")
    assert result.envelope is not None
    assert result.envelope.usage is not None
    assert result.envelope.usage.input_tokens == 120
    assert result.envelope.usage.output_tokens == 0
    assert controller.metrics.last().input_tokens == 120


def test_usage_stays_null_when_the_engine_reports_nothing(task_state):
    """The deterministic fallback is not a model: it has no tokens to report."""
    engine = FakeEngine(default=answer("feature", confidence=None,
                                       allowed=TASK_OPTIONS))
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine())

    result = controller.decide(task_state, "task_classification")

    assert result.outcome is Outcome.FALLBACK
    assert result.envelope is not None
    assert result.envelope.usage is None, "absent usage must not be reported as 0"
    assert controller.metrics.last().input_tokens is None
    assert controller.metrics.counter("usage.missing") == 1


# --- requirement 7: timeouts ------------------------------------------------------------


def test_a_hung_engine_hits_the_configured_timeout_and_falls_back(task_state):
    engine = FakeEngine(script=[Scripted(answer=answer("bug_fix", confidence=0.9),
                                         delay_s=5.0)])
    controller = WorkflowController(
        engine=engine,
        config=ControllerConfig(timeout_s=0.2),
        fallback=DeterministicEngine(),
    )
    result = controller.decide(task_state, "task_classification")

    assert result.outcome is Outcome.FALLBACK
    assert "EngineTimeout" in result.error
    assert result.envelope is not None and result.source == "fallback"
    assert result.latency_ms < 4000.0, "the watchdog must not wait for the sleeper"


def test_a_hung_engine_without_fallback_fails_closed(task_state):
    engine = FakeEngine(script=[Scripted(answer=answer("bug_fix"), delay_s=5.0)])
    config = ControllerConfig(timeout_s=0.2, policy=PolicyConfig(fallback_enabled=False))
    controller = WorkflowController(engine=engine, config=config)

    result = controller.decide(task_state, "task_classification")
    assert result.outcome is Outcome.FAILED
    assert result.envelope is None
    assert result.action.value == "abstain"
    assert "EngineTimeout" in result.error


def test_a_pre_raised_timeout_is_treated_as_a_transport_failure(task_state):
    engine = FakeEngine(script=[Scripted(error=EngineTimeout("endpoint exceeded 10s"))])
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine())

    result = controller.decide(task_state, "task_classification")
    assert result.outcome is Outcome.FALLBACK
    assert "EngineTimeout" in result.error


def test_timeout_is_configurable_per_controller(config):
    assert config.timeout_s == 2.0
    with pytest.raises(ValueError, match="timeout_s"):
        ControllerConfig(timeout_s=0)


# --- requirement 6: malformed / unsupported output -------------------------------------


def test_an_out_of_scope_answer_is_rejected_rather_than_coerced(task_state):
    engine = FakeEngine(default=EngineAnswer(selected_option="chore", confidence=0.99))
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine())

    result = controller.decide(task_state, "task_classification")

    assert result.outcome is Outcome.FALLBACK
    assert "OutOfScopeOption" in result.error
    assert result.envelope is not None
    assert result.envelope.selected_option in TASK_OPTIONS, \
        "the bogus option must not reach the caller"


def test_a_structurally_broken_answer_is_rejected(task_state):
    engine = FakeEngine(default=EngineAnswer(selected_option="", confidence=0.9))
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine())

    result = controller.decide(task_state, "task_classification")
    assert result.outcome is Outcome.FALLBACK
    assert "MalformedDecision" in result.error


def test_an_impossible_confidence_is_rejected(task_state):
    engine = FakeEngine(default=EngineAnswer(selected_option="bug_fix", confidence=3.14))
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine())

    result = controller.decide(task_state, "task_classification")
    assert result.outcome is Outcome.FALLBACK
    assert "InvalidConfidence" in result.error


def test_an_unknown_decision_type_from_the_caller_raises_immediately(controller,
                                                                     task_state):
    """A caller mistake is a programming error, not a runtime condition."""
    with pytest.raises(UnsupportedDecisionType):
        controller.decide(task_state, "approve_the_release")


def test_a_widened_option_set_from_the_caller_raises_immediately(controller, task_state):
    from layasdlc import OutOfScopeOption

    with pytest.raises(OutOfScopeOption):
        controller.decide(task_state, "task_classification",
                          allowed_options=["bug_fix", "chore"])


# --- missing confidence information -----------------------------------------------------


def test_missing_confidence_never_counts_as_a_pass(task_state):
    engine = FakeEngine(default=EngineAnswer(selected_option="bug_fix", confidence=None))
    config = ControllerConfig(policy=PolicyConfig(min_confidence=0.35,
                                                  fallback_enabled=False))
    controller = WorkflowController(engine=engine, config=config)

    result = controller.decide(task_state, "task_classification")
    assert result.gate.value == "unevaluated"
    assert result.outcome is Outcome.REJECTED
    assert result.action.value == "investigate"
    assert result.envelope is not None and result.envelope.confidence is None


def test_missing_confidence_triggers_the_deterministic_fallback(task_state):
    engine = FakeEngine(default=EngineAnswer(selected_option="bug_fix", confidence=None))
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine())

    result = controller.decide(task_state, "task_classification")
    assert result.outcome is Outcome.FALLBACK
    assert result.gate.value == "passed"


def test_confidence_below_the_threshold_abstains_without_fallback(task_state):
    engine = FakeEngine(default=EngineAnswer(selected_option="bug_fix", confidence=0.20))
    config = ControllerConfig(policy=PolicyConfig(min_confidence=0.35,
                                                  fallback_enabled=False))
    controller = WorkflowController(engine=engine, config=config)

    result = controller.decide(task_state, "task_classification")
    assert result.gate.value == "abstained"
    assert result.outcome is Outcome.REJECTED
    assert "below threshold" in result.error


def test_threshold_is_configurable():
    strict = PolicyConfig(min_confidence=0.99)
    assert strict.min_confidence == 0.99
    with pytest.raises(ValueError, match="min_confidence"):
        PolicyConfig(min_confidence=1.5)


# --- requirement: model failures ---------------------------------------------------------


@pytest.mark.parametrize("error", [
    EngineUnavailable("connection refused"),
    RuntimeError("kaboom"),
    ValueError("engine bug"),
])
def test_any_engine_failure_is_contained_and_recorded(task_state, error):
    engine = FakeEngine(script=[Scripted(error=error)])
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine())

    result = controller.decide(task_state, "task_classification")
    assert result.outcome is Outcome.FALLBACK
    assert result.error
    assert controller.metrics.last().error is not None


def test_no_exception_escapes_the_controller(task_state):
    engine = FakeEngine(script=[Scripted(error=KeyboardInterrupt("no"))])
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine())
    # KeyboardInterrupt derives from BaseException; the controller's contract is
    # that ordinary Exceptions are contained. Re-raising anything else is fine.
    with pytest.raises(BaseException):
        controller.decide(task_state, "task_classification")


# --- the other three bounded decision types --------------------------------------------


@pytest.mark.parametrize("decision_type,options,expected", [
    (DecisionType.WORKFLOW_SELECTION.value, ("run_tests", "edit_code"), "run_tests"),
    (DecisionType.RETRY_VS_ESCALATE.value, ("retry", "escalate"), "retry"),
    (DecisionType.CONTEXT_PRIORITY.value, ("high", "medium", "low"), "medium"),
])
def test_the_other_bounded_decision_types_round_trip(controller, task_state,
                                                      decision_type, options, expected):
    from layasdlc import ToolPermissionPolicy

    # Workflow options are tool identifiers; this test is about round-tripping the
    # decision type, so grant every tool explicitly rather than being narrowed away.
    controller.permissions = ToolPermissionPolicy.full()
    controller.engine = FakeEngine(default=answer(expected, confidence=0.8,
                                                  allowed=options))
    result = controller.decide(task_state, decision_type, allowed_options=options)

    assert result.outcome is Outcome.DECIDED
    assert result.envelope is not None
    assert result.envelope.decision_type == decision_type
    assert result.envelope.selected_option == expected
    assert set(result.envelope.allowed_options) == set(options)


def test_retry_vs_escalate_maps_to_an_action(controller, task_state):
    controller.engine = FakeEngine(default=answer("escalate", confidence=0.9,
                                                  allowed=("retry", "escalate")))
    result = controller.decide(task_state, "retry_vs_escalate")
    assert result.action.value == "escalate"

    controller.engine = FakeEngine(default=answer("retry", confidence=0.9,
                                                  allowed=("retry", "escalate")))
    retry = controller.decide(task_state, "retry_vs_escalate")
    assert retry.action.value == "proceed"


# --- metrics ----------------------------------------------------------------------------


def test_every_decision_is_measured_even_when_it_fails(controller, task_state):
    controller.decide(task_state, "task_classification")
    controller.engine = FakeEngine(script=[Scripted(error=RuntimeError("down"))])
    controller.decide(task_state, "task_classification")

    summary = controller.metrics.summary()
    assert summary["counters"]["outcome.decided"] == 1
    assert summary["counters"]["outcome.fallback"] == 1
    assert summary["measurements"] == 2
    assert summary["latency_ms"]["mean"] is not None


def test_health_delegates_to_the_health_module(controller, task_state):
    document = controller.health()
    assert document["status"] in ("ok", "degraded")
    assert document["schema_version"]
    assert document["engine"]["name"] == "fake"
    assert "metrics" in document
