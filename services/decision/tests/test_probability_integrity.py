"""Decision integrity: malformed probability data can never become a trusted decision.

The defect this file replaces: :func:`layasdlc.engine.ranked_probabilities` used
to skip the entries it could not parse. A response carrying
``{"bug_fix": true, "feature": 0.4}`` therefore produced a *shorter*
distribution, which validation then accepted as complete -- validation only ever
saw what survived, so nothing downstream could tell that a member had gone
missing. A two-way question had silently become a one-way one, and the surviving
number was published as the model's whole answer.

The contract established here is a deliberate three-way split:

=============== ================================================ ===============================
Where           What                                             Classification
=============== ================================================ ===============================
source          ``probabilities`` present but not an object;     ``MalformedResponse`` --
(``ranked_      an entry that is bool, non-numeric, ``NaN`` or   malformed *response* data,
probabilities``) ``±Infinity``                                   refused before an
                                                                 ``EngineAnswer`` exists
validation      a number outside ``[0, 1]``; a key outside       ``DecisionRejected`` subclasses
(``validate_    ``allowed_options``; structural damage
answer``)
on the wire     finite numbers in ``[0, 1]``                     ``Alternative``, ranked best-first
=============== ================================================ ===============================

Not errors, and deliberately so: an absent distribution, and a truncated top-k
ranking whose entries do not sum to 1.

Every fixture is offline and deterministic.
"""

from __future__ import annotations

import math

import pytest

from layasdlc import (
    ControllerConfig,
    DeterministicEngine,
    EngineAnswer,
    EngineFailure,
    EngineRequest,
    EngineTimeout,
    EngineUnavailable,
    FakeEngine,
    MalformedDecision,
    MalformedResponse,
    Outcome,
    PolicyConfig,
    TaskState,
    ToolPermissionPolicy,
    Usage,
    WorkflowController,
    validate_answer,
)
from layasdlc.engine import answer_confidence, ranked_probabilities
from layasdlc.engines import LayaHttpEngine, RawResponse, Transport
from layasdlc.engines.fake import Scripted

TASK_OPTIONS = ("bug_fix", "feature", "refactor", "testing",
                "documentation", "investigation")


def request(options=TASK_OPTIONS, decision_type="task_classification") -> EngineRequest:
    return EngineRequest(
        decision_id="d1", task_id="T-1", decision_type=decision_type,
        allowed_options=tuple(options), state={"subject": "x"}, question="q",
    )


def answer(selected="bug_fix", *, probabilities=None) -> EngineAnswer:
    """A hand-built answer, bypassing the engine parser on purpose.

    The fake engine builds answers directly, so this is the shape the
    *validation* layer has to survive -- and it is why enforcement is not left
    to the parser alone.
    """
    return EngineAnswer(
        selected_option=selected,
        confidence=0.9,
        model="fake/laya",
        model_version="0.0-test",
        latency_ms=1.0,
        usage=Usage(input_tokens=10, output_tokens=0),
        probabilities={} if probabilities is None else probabilities,
    )


def selection(probabilities, *, present=True) -> dict:
    """A ``answers.selection`` object of the documented shape."""
    body = {"type": "choice", "choice": "bug_fix"}
    if present:
        body["probabilities"] = probabilities
    return body


def task_state() -> TaskState:
    return TaskState(
        task_id="T-1",
        subject="Checkout throws 500 on promo code",
        body="Applying any promo code raises a 500 and the trace shows a None "
             "discount. This is a regression from the pricing refactor.",
        path="src/billing/pricing.py",
    )


def controller_for(engine, *, fallback=None) -> WorkflowController:
    return WorkflowController(
        engine=engine,
        config=ControllerConfig(
            timeout_s=2.0,
            policy=PolicyConfig(min_confidence=0.0,
                                fallback_enabled=fallback is not None),
        ),
        fallback=fallback,
        # Full, so the permission layer is not what is under test here.
        permissions=ToolPermissionPolicy.full(),
    )


# ======================================================================================
# Layer 1 -- the source parser refuses what it cannot represent
# ======================================================================================


def test_a_valid_distribution_is_returned_ranked_best_first():
    pairs = ranked_probabilities(selection({"bug_fix": 0.2, "feature": 0.7,
                                            "testing": 0.1}))
    assert pairs == [("feature", 0.7), ("bug_fix", 0.2), ("testing", 0.1)]


def test_an_empty_distribution_is_not_an_error():
    assert ranked_probabilities(selection({})) == []


def test_an_explicitly_null_distribution_is_not_an_error():
    assert ranked_probabilities(selection(None)) == []


def test_a_missing_probabilities_field_reports_no_distribution():
    assert ranked_probabilities(selection(None, present=False)) == []


def test_a_response_without_a_selection_object_reports_no_distribution():
    """A non-choice answer has no probabilities at all; that is not malformed."""
    assert ranked_probabilities({"type": "noul", "p_true": 0.7}) == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinities_are_refused_at_the_source(value):
    with pytest.raises(MalformedResponse) as excinfo:
        ranked_probabilities(selection({"bug_fix": value, "feature": 0.4}))
    assert "bug_fix" in str(excinfo.value), "the refusal must name the offending option"


@pytest.mark.parametrize("value", [True, False])
def test_booleans_are_refused_at_the_source(value):
    """JSON ``true`` is a boolean; Python models it as int 1, which would read as certainty."""
    with pytest.raises(MalformedResponse):
        ranked_probabilities(selection({"bug_fix": value, "feature": 0.4}))


@pytest.mark.parametrize("value", ["high", "0.5", None, {}, [0.4], object()])
def test_non_numeric_values_are_refused_at_the_source(value):
    with pytest.raises(MalformedResponse):
        ranked_probabilities(selection({"bug_fix": value, "feature": 0.4}))


@pytest.mark.parametrize("value", [[0.4, 0.6], "0.9", 7])
def test_a_present_probabilities_field_that_is_not_an_object_is_malformed(value):
    with pytest.raises(MalformedResponse):
        ranked_probabilities(selection(value))


def test_one_bad_entry_refuses_the_whole_distribution_rather_than_narrowing_it():
    """The heart of the fix: no member is dropped and the rest published."""
    with pytest.raises(MalformedResponse):
        ranked_probabilities(selection({"bug_fix": 0.4, "feature": True,
                                        "testing": 0.2}))


def test_the_refusal_is_a_typed_response_error_not_a_generic_engine_failure():
    """A malformed response must not be mistaken for a dead engine."""
    assert MalformedResponse is not EngineFailure
    assert not issubclass(MalformedResponse, EngineFailure)
    assert MalformedResponse.retryable is False, "a payload defect is never transient"
    assert MalformedResponse.status == "malformed", \
        "observable and distinct from status='engine_error'"


# ======================================================================================
# Layer 1 vs layer 2 -- what each one owns
# ======================================================================================


def test_out_of_range_numbers_pass_the_parser_and_are_rejected_by_validation():
    """Preserved behaviour: 1.5 is representable, so it is the validator's call."""
    surviving = dict(ranked_probabilities(selection({"bug_fix": 1.5, "feature": 0.4})))
    assert surviving["bug_fix"] == 1.5

    with pytest.raises(MalformedDecision):
        validate_answer(request(), answer(probabilities=surviving))

    with pytest.raises(MalformedDecision):
        validate_answer(request(), answer(probabilities={"bug_fix": -0.1,
                                                        "feature": 0.4}))


def test_validation_still_refuses_what_a_hand_built_answer_brings():
    """The parser is not the only guard: answers can be built without going near it."""
    with pytest.raises(MalformedDecision):
        validate_answer(request(), answer(probabilities={"bug_fix": 0.5,
                                                        "feature": float("nan")}))
    with pytest.raises(MalformedDecision):
        validate_answer(request(), answer(probabilities={"bug_fix": 0.5,
                                                        "feature": True}))


def test_a_truncated_top_k_ranking_is_accepted_without_a_sum_constraint():
    """Not normalised, not rescaled, not rejected: a partial ranking is still real."""
    envelope = validate_answer(
        request(),
        answer(probabilities=dict(ranked_probabilities(
            selection({"bug_fix": 0.5, "feature": 0.3})))),
    )

    assert [(a.option, a.probability) for a in envelope.alternatives] == [
        ("bug_fix", 0.5), ("feature", 0.3)
    ]
    assert sum(a.probability for a in envelope.alternatives) == pytest.approx(0.8), \
        "a top-k ranking legitimately does not sum to 1 and must not be forced to"


def test_an_absent_distribution_still_reaches_the_caller_as_null():
    envelope = validate_answer(request(), answer(probabilities={}))
    assert envelope.alternatives is None
    assert envelope.to_dict()["alternatives"] is None


def test_confidence_parsing_is_untouched_by_the_stricter_parser():
    """A no-unrelated-change guard: confidence may be absent; a distribution may not."""
    assert answer_confidence(selection({"bug_fix": 0.9, "feature": 0.1})) == 0.9
    assert answer_confidence({"type": "choice", "confidence": 0.35}) == 0.35
    assert answer_confidence({"type": "choice", "confidence": float("nan")}) is None
    assert answer_confidence({"type": "choice"}) is None


# ======================================================================================
# Through the real HTTP engine -- raw bytes in, answer or refusal out
# ======================================================================================


def _body(probabilities: str | None) -> bytes:
    inner = '{"type": "choice", "choice": "bug_fix", "confidence": 0.8'
    if probabilities is not None:
        inner += f', "probabilities": {probabilities}'
    inner += "}"
    return (
        '{"model": "laya-0.3.4/typed-decisions", '
        '"usage": {"input_tokens": 120, "output_tokens": 4}, '
        f'"answers": {{"selection": {inner}}}}}'
    ).encode("utf-8")


class _StubTransport(Transport):
    """Returns one canned response and counts how often it was asked."""

    def __init__(self, response: RawResponse):
        self.response = response
        self.calls = 0

    def post(self, url, *, body, headers, timeout_s):
        self.calls += 1
        return self.response


def _engine_with_body(probabilities: str | None):
    transport = _StubTransport(RawResponse(status=200, body=_body(probabilities)))
    return LayaHttpEngine(base_url="https://example.invalid", transport=transport,
                          sleep=lambda _s: None), transport


@pytest.mark.parametrize("probabilities,fragment", [
    ('{"bug_fix": true, "feature": 0.4}', "bool"),
    ('{"bug_fix": false, "feature": 0.4}', "bool"),
    ('{"bug_fix": NaN, "feature": 0.4}', "finite"),
    ('{"bug_fix": Infinity, "feature": 0.4}', "finite"),
    ('{"bug_fix": -Infinity, "feature": 0.4}', "finite"),
    ('{"bug_fix": "high", "feature": 0.4}', "str"),
    ('[0.4, 0.6]', "object"),
])
def test_a_malformed_probability_in_a_real_response_body_is_refused(probabilities, fragment):
    """Raw wire bytes, through ``decide()``, to the typed refusal."""
    engine, _transport = _engine_with_body(probabilities)

    with pytest.raises(MalformedResponse) as excinfo:
        engine.decide(request())

    assert fragment in str(excinfo.value)


def test_a_malformed_body_is_not_retried():
    """A payload defect is deterministic; retrying would just spend the budget."""
    engine, transport = _engine_with_body('{"bug_fix": true, "feature": 0.4}')

    with pytest.raises(MalformedResponse):
        engine.decide(request())

    assert transport.calls == 1


def test_a_well_formed_body_still_produces_an_answer():
    engine, _transport = _engine_with_body('{"bug_fix": 0.7, "feature": 0.3}')

    envelope = validate_answer(request(), engine.decide(request()))

    assert [(a.option, a.probability) for a in envelope.alternatives] == [
        ("bug_fix", 0.7), ("feature", 0.3)
    ]
    # Laya's answer_confidence is max(p) for a choice, not the entropy field.
    assert envelope.confidence == pytest.approx(0.7)


def test_a_body_with_no_probabilities_field_is_accepted_as_no_distribution():
    engine, _transport = _engine_with_body(None)

    envelope = validate_answer(request(), engine.decide(request()))

    assert envelope.selected_option == "bug_fix"
    assert envelope.alternatives is None


# ======================================================================================
# Through the controller -- the classifications stay distinct and observable
# ======================================================================================


def test_a_malformed_probability_is_a_response_failure_not_a_transport_failure():
    controller = controller_for(FakeEngine(script=[Scripted(
        error=MalformedResponse("probability for 'bug_fix' must be a number"))]))

    result = controller.decide(task_state(), "task_classification")

    assert result.outcome is Outcome.FAILED
    assert result.error is not None
    assert result.error.startswith("MalformedResponse["), result.error
    assert "EngineFailure" not in result.error, \
        "a malformed payload must not be reported as an engine/transport failure"


@pytest.mark.parametrize("error,expected", [
    (EngineUnavailable("connection refused"), "EngineUnavailable"),
    (EngineTimeout("did not answer"), "EngineTimeout"),
    (EngineFailure("something unrecognised"), "EngineFailure"),
    (MalformedResponse("probabilities carried a boolean"), "MalformedResponse"),
])
def test_engine_transport_and_response_failures_stay_distinguishable(error, expected):
    """Requirement: the classification survives and stays observable."""
    controller = controller_for(FakeEngine(script=[Scripted(error=error)]))

    result = controller.decide(task_state(), "task_classification")

    assert result.outcome is Outcome.FAILED
    assert result.error is not None and result.error.startswith(f"{expected}["), \
        f"{expected} was reported as {result.error!r}"


def test_the_malformed_response_is_counted_under_its_own_metric():
    controller = controller_for(FakeEngine(script=[Scripted(
        error=MalformedResponse("probabilities carried a boolean"))]))
    controller.decide(task_state(), "task_classification")

    keys = [k for k in controller.metrics.counters if k.startswith("error.")]
    assert len(keys) == 1, keys
    assert keys[0].startswith("error.MalformedResponse"), keys


def test_a_malformed_response_falls_back_to_the_baseline_instead_of_being_trusted():
    engine = FakeEngine(script=[Scripted(
        error=MalformedResponse("probabilities carried a boolean"))])
    controller = controller_for(engine, fallback=DeterministicEngine())

    result = controller.decide(task_state(), "task_classification")

    assert result.outcome is Outcome.FALLBACK
    assert result.source == "fallback", "the baseline answered, not the model"
    assert result.error is not None and "MalformedResponse" in result.error, \
        "the reason for falling back must survive the fallback"
    assert result.envelope is not None
    assert result.envelope.model == DeterministicEngine.name


def test_a_rejected_payload_is_still_a_rejection_not_a_failure():
    """Validation's own classification must not be reclassified by the new raise."""
    engine = FakeEngine(default=answer(probabilities={"bug_fix": 0.5, "feature": 1.5}))
    controller = controller_for(engine)

    result = controller.decide(task_state(), "task_classification")

    assert result.outcome is Outcome.REJECTED, result.error
    assert result.error is not None and result.error.startswith("MalformedDecision["), \
        result.error


@pytest.mark.parametrize("probabilities", [
    {"bug_fix": float("nan"), "feature": 0.4},
    {"bug_fix": float("inf"), "feature": 0.4},
    {"bug_fix": float("-inf"), "feature": 0.4},
    {"bug_fix": True, "feature": 0.4},
    {"bug_fix": "high", "feature": 0.4},
    {"bug_fix": None, "feature": 0.4},
    {"bug_fix": 1.5, "feature": 0.4},
    {"bug_fix": -0.1, "feature": 0.4},
])
def test_a_malformed_probability_never_produces_a_trusted_model_decision(probabilities):
    """Acceptance: whatever the shape, no malformed number is published as the model's."""
    engine = FakeEngine(default=answer(probabilities=probabilities))
    controller = controller_for(engine, fallback=DeterministicEngine())

    result = controller.decide(task_state(), "task_classification")

    assert result.outcome is not Outcome.DECIDED, \
        f"a malformed distribution was accepted: {result.error!r}"

    if result.envelope is not None:
        # Only the deterministic baseline can have answered, and it must be
        # clearly attributable to the baseline rather than to the model.
        assert result.source == "fallback"
        for alternative in result.envelope.alternatives or ():
            assert math.isfinite(alternative.probability)
            assert 0.0 <= alternative.probability <= 1.0
