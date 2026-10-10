"""Integration: real Laya inference, when a real Laya endpoint is reachable.

Stage 2 testing rule: **do not simulate a successful real inference**. Nothing in
this module fabricates an answer. Either a real engine answers, or the test
skips with an explicit reason.

Two engines can satisfy "real Laya":

* :class:`~layasdlc.engines.laya_http.LayaHttpEngine` -- a Jev-compatible
  ``POST /v1/systemone`` endpoint. Set ``LAYA_BASE_URL`` to point elsewhere; it
  defaults to a free, keyless public endpoint that was verified live during
  reconnaissance.
* :class:`~layasdlc.engines.laya_sdk.LayaSdkEngine` -- the local ``laya``
  package. Not installed on this host, so it skips rather than pretending.

Run explicitly with::

    pytest -m integration            # opt in
    pytest                           # runs only if the endpoint answers within 10s
    LAYA_BASE_URL=https://your-host pytest -m integration

Deselect everywhere else with ``-m "not integration"``.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from layasdlc import (
    ControllerConfig,
    DeterministicEngine,
    DecisionType,
    EngineRequest,
    FakeEngine,
    Outcome,
    PolicyConfig,
    TaskState,
    ToolPermissionPolicy,
    WorkflowController,
    question_for,
)
from layasdlc.engines.laya_http import LayaHttpEngine
from layasdlc.engines.laya_sdk import LayaSdkEngine, laya_sdk_available

pytestmark = pytest.mark.integration

#: Free, keyless, Jev-compatible endpoint verified during reconnaissance.
DEFAULT_BASE_URL = "https://laya.inference.zaitlabs.com"
PROBE_TIMEOUT_S = float(os.environ.get("LAYA_PROBE_TIMEOUT", "10"))


def _build_engine():
    """Return a *real* engine, or skip. Never returns a fake."""
    choice = os.environ.get("LAYA_ENGINE", "http")

    if choice == "sdk":
        if not laya_sdk_available():
            pytest.skip("the 'laya' Python package is not installed in this environment")
        return LayaSdkEngine()

    base_url = os.environ.get("LAYA_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.environ.get("LAYA_API_KEY") or None
    model = os.environ.get("LAYA_MODEL") or None

    engine = LayaHttpEngine(base_url=base_url, api_key=api_key, model=model)
    if not engine.available():
        pytest.skip("no Laya base_url configured")
    return engine


def _assert_reachable(engine) -> None:
    """Skip -- never fake -- when the endpoint cannot answer a real request."""
    probe = engine.probe(timeout_s=PROBE_TIMEOUT_S) if hasattr(engine, "probe") else None
    if probe is not None and not probe.get("reachable"):
        pytest.skip(f"Laya endpoint unreachable: {probe.get('detail')}")


def _real_controller(engine) -> WorkflowController:
    # No fallback here on purpose: if the baseline answers, this test would be
    # measuring the baseline, not Laya.
    #
    # Two permitted tools, not one. With a single permitted tool the option set
    # collapses to one element and the controller settles it from policy without
    # inference -- which is correct behaviour, but would mean workflow_selection
    # never reaches the endpoint here. Two tools keep the question real while
    # still excluding edit_code, so the permission layer stays exercised.
    #
    # min_confidence=0.0 is deliberate. Calibrating Laya's threshold is a separate
    # milestone; this module verifies *plumbing* -- that a real request is built,
    # sent, validated and envelope-ed. Gating the result here would let a
    # perfectly real answer fail the test, hiding plumbing regressions behind
    # calibration noise.
    return WorkflowController(
        engine=engine,
        config=ControllerConfig(
            timeout_s=PROBE_TIMEOUT_S,
            policy=PolicyConfig(min_confidence=0.0, fallback_enabled=False),
        ),
        fallback=None,
        permissions=ToolPermissionPolicy.of({"read_investigate", "run_tests"}),
    )


#: How many whole decisions to attempt before declaring the free endpoint
#: degraded. The engine already retries internally, so this is a second layer.
ENDPOINT_ATTEMPTS = 2
#: Only *endpoint-side* conditions justify retrying or skipping. Anything else
#: (validation, permissions, contract) is a defect in this repo and must fail.
_DEGRADED_MARKERS = ("EngineUnavailable", "EngineTimeout", "EngineRateLimited")


def _ask_or_skip(controller, state, decision_type):
    """Ask the real endpoint for real, and skip -- never fake -- if it is down.

    Every attempt sends a genuinely new request to Laya and returns only what
    Laya actually said. On persistent endpoint failure this skips with the real
    error attached; it never substitutes an answer of its own.
    """
    last_error = None
    result = None
    for attempt in range(1, ENDPOINT_ATTEMPTS + 1):
        result = controller.decide(state, decision_type)
        if result.source == "engine" and result.envelope is not None:
            return result
        last_error = result.error or f"outcome={result.outcome.value}"
        if attempt < ENDPOINT_ATTEMPTS and any(m in last_error for m in _DEGRADED_MARKERS):
            time.sleep(0.5 * attempt)
            continue
        break

    if last_error and any(m in last_error for m in _DEGRADED_MARKERS):
        pytest.skip(
            f"the real Laya endpoint is currently degraded ({last_error}); "
            "no answer was simulated or substituted"
        )
    return result


def test_real_bounded_decision_through_laya():
    """Acceptance: at least one real, bounded decision works through Laya."""
    engine = _build_engine()
    _assert_reachable(engine)
    controller = _real_controller(engine)

    state = TaskState(
        task_id="IT-1",
        subject="Checkout throws 500 on promo code",
        body="Applying any promo code raises a 500 and the stack trace shows a None "
             "discount. This is a regression from the pricing refactor.",
        path="src/billing/pricing.py",
    )

    result = _ask_or_skip(controller, state, DecisionType.TASK_CLASSIFICATION.value)

    # --- the decision must be real, not produced by a fallback -------------------------
    assert result.source == "engine", (
        f"expected a real Laya answer, got source={result.source!r} "
        f"outcome={result.outcome.value!r} error={result.error!r}"
    )
    assert result.outcome is Outcome.DECIDED, result.error
    assert result.envelope is not None

    envelope = result.envelope
    # --- structure, not guesswork -------------------------------------------------------
    assert envelope.selected_option in envelope.allowed_options
    assert envelope.decision_type == DecisionType.TASK_CLASSIFICATION.value
    assert envelope.schema_version
    if envelope.confidence is not None:
        assert 0.0 <= envelope.confidence <= 1.0
    # Laya does not generate text: a real answer must not invent a rationale.
    assert envelope.rationale is None

    # --- measured, not asserted ---------------------------------------------------------
    assert result.latency_ms > 0.0, "latency must be measured, not assumed"
    measurement = controller.metrics.last()
    assert measurement is not None and measurement.latency_ms > 0.0

    print(f"\n[real laya] model={envelope.model!r} v={envelope.model_version!r} "
          f"selected={envelope.selected_option!r} confidence={envelope.confidence} "
          f"latency={result.latency_ms:.1f}ms "
          f"usage={envelope.usage.to_dict() if envelope.usage else None}")


@pytest.mark.parametrize("decision_type", list(DecisionType))
def test_real_laya_answers_every_bounded_decision_type(decision_type):
    """Stage 2 requirement 4: all four bounded decision types round-trip for real."""
    engine = _build_engine()
    _assert_reachable(engine)
    controller = _real_controller(engine)

    state = TaskState(
        task_id="IT-2",
        subject="Flaky checkout test",
        body="The checkout integration test times out intermittently in CI; it "
             "passed locally. Investigate before changing code.",
    )

    result = _ask_or_skip(controller, state, decision_type.value)
    assert result.envelope is not None, result.error
    assert result.envelope.decision_type == decision_type.value
    assert result.envelope.selected_option in result.envelope.allowed_options
    assert result.source == "engine", f"baseline answered, not Laya: {result.error}"


def test_real_laya_rejects_an_unsupported_model_identifier():
    """Real error path: this spelling is documented to return HTTP 400 unknown_model."""
    engine = _build_engine()
    if not isinstance(engine, LayaHttpEngine):
        pytest.skip("model rejection is an HTTP-endpoint behaviour")

    request = EngineRequest(
        decision_id="IT-3", task_id="IT-3",
        decision_type=DecisionType.TASK_CLASSIFICATION.value,
        allowed_options=("bug_fix", "feature"),
        state={"subject": "x", "body": "fix the bug"},
        question="q",
        model="laya-english",          # verified to be rejected by the endpoint
        timeout_s=PROBE_TIMEOUT_S,
    )

    from layasdlc import EngineRejected

    with pytest.raises(EngineRejected) as excinfo:
        engine.decide(request)
    assert excinfo.value.http_status in (400, 422)
    assert "unknown model" in str(excinfo.value).lower()


def test_real_question_payload_matches_the_verified_wire_shape():
    """The question we send must be the verified system_one shape."""
    question = question_for("task_classification", ("bug_fix", "feature"))
    assert set(question) == {"selection"}
    inner = question["selection"]
    assert inner["type"] == "choice"
    assert isinstance(inner["instructions"], str) and inner["instructions"]
    assert set(inner["criteria"]) == {"bug_fix", "feature"}
    json.dumps(question)  # must be JSON-serialisable as sent
