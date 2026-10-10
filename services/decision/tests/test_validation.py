"""Stage 2 requirements 5 and 6: validate every answer; reject bad ones safely."""

from __future__ import annotations

import math

import pytest

from layasdlc import (
    DecisionType,
    EngineAnswer,
    EngineRequest,
    InvalidConfidence,
    MalformedDecision,
    OutOfScopeOption,
    SCHEMA_VERSION,
    UnsupportedDecisionType,
    Usage,
    resolve_allowed_options,
    validate_answer,
    validate_envelope,
)

TASK_OPTIONS = ("bug_fix", "feature", "refactor", "testing",
                "documentation", "investigation")


def request(options=TASK_OPTIONS, decision_type="task_classification") -> EngineRequest:
    return EngineRequest(
        decision_id="d1", task_id="T-1", decision_type=decision_type,
        allowed_options=tuple(options), state={"subject": "x"}, question="q",
    )


# --- option-set resolution (before any engine is called) ------------------------------


def test_defaults_to_the_canonical_option_set():
    assert resolve_allowed_options("task_classification") == TASK_OPTIONS


def test_a_caller_may_narrow_but_not_widen():
    assert resolve_allowed_options("task_classification", ["bug_fix"]) == ("bug_fix",)
    with pytest.raises(OutOfScopeOption):
        resolve_allowed_options("task_classification", ["bug_fix", "chore"])


def test_unknown_decision_type_is_rejected():
    with pytest.raises(UnsupportedDecisionType) as excinfo:
        resolve_allowed_options("release_the_hounds")
    assert "release_the_hounds" in str(excinfo.value)


def test_empty_and_duplicate_option_sets_are_rejected():
    with pytest.raises(MalformedDecision):
        resolve_allowed_options("task_classification", [])
    with pytest.raises(MalformedDecision):
        resolve_allowed_options("task_classification", ["bug_fix", "bug_fix"])


# --- answer validation -----------------------------------------------------------------


def test_valid_answer_becomes_a_validated_envelope():
    answer = EngineAnswer(selected_option="bug_fix", confidence=0.72,
                          model="laya", model_version="0.3.4", latency_ms=9.0,
                          usage=Usage(input_tokens=10, output_tokens=0))
    envelope = validate_answer(request(), answer)

    assert envelope.selected_option == "bug_fix"
    assert envelope.schema_version == SCHEMA_VERSION
    assert envelope.confidence == 0.72
    assert envelope.decision_id == "d1", "ids come from the request, not the engine"
    assert envelope.task_id == "T-1"
    assert envelope.usage.input_tokens == 10


def test_out_of_scope_selection_is_rejected_with_both_sets_recorded():
    answer = EngineAnswer(selected_option="chore", confidence=0.9)
    with pytest.raises(OutOfScopeOption) as excinfo:
        validate_answer(request(), answer)
    assert excinfo.value.selected == "chore"
    assert excinfo.value.allowed == list(TASK_OPTIONS)


@pytest.mark.parametrize("bad", [None, "", "   ", 42, "BUGFIX"])
def test_missing_or_malformed_selection_is_rejected(bad):
    answer = EngineAnswer(selected_option=bad)  # type: ignore[arg-type]
    with pytest.raises((MalformedDecision, OutOfScopeOption)):
        validate_answer(request(), answer)


def test_none_answer_is_malformed_not_a_crash():
    with pytest.raises(MalformedDecision):
        validate_answer(request(), None)  # type: ignore[arg-type]


def test_missing_confidence_is_accepted_as_none():
    # Requirement 3: confidence only when meaningfully supported. Absent != malformed.
    envelope = validate_answer(request(), EngineAnswer(selected_option="bug_fix",
                                                       confidence=None))
    assert envelope.confidence is None


@pytest.mark.parametrize("bad_confidence", [1.5, -0.2, float("nan"),
                                            float("inf"), True, "high", object()])
def test_present_but_meaningless_confidence_is_rejected(bad_confidence):
    answer = EngineAnswer(selected_option="bug_fix", confidence=bad_confidence)  # type: ignore[arg-type]
    with pytest.raises(InvalidConfidence):
        validate_answer(request(), answer)


def test_boundary_confidences_are_accepted():
    for value in (0.0, 1.0, 0.5):
        envelope = validate_answer(request(), EngineAnswer(selected_option="bug_fix",
                                                           confidence=value))
        assert envelope.confidence == value


def test_rationale_must_be_a_string_or_null():
    good = validate_answer(request(), EngineAnswer(selected_option="bug_fix",
                                                   rationale="matched crash keywords"))
    assert good.rationale == "matched crash keywords"

    with pytest.raises(MalformedDecision):
        validate_answer(request(), EngineAnswer(selected_option="bug_fix",
                                                rationale=["not", "a", "string"]))


def test_selection_is_trimmed_but_not_silently_changed():
    envelope = validate_answer(request(), EngineAnswer(selected_option="  bug_fix  ",
                                                       confidence=0.5))
    assert envelope.selected_option == "bug_fix"


def test_workflow_selection_validates_against_the_workflow_space():
    req = request(options=("edit_code", "run_tests"),
                  decision_type=DecisionType.WORKFLOW_SELECTION.value)
    assert validate_answer(req, EngineAnswer(selected_option="run_tests",
                                             confidence=0.8)).selected_option == "run_tests"
    with pytest.raises(OutOfScopeOption):
        validate_answer(req, EngineAnswer(selected_option="deploy_to_prod", confidence=0.9))


# --- re-validation across a process boundary -------------------------------------------


def test_validate_envelope_round_trips():
    original = validate_answer(request(), EngineAnswer(
        selected_option="bug_fix", confidence=0.72, model="laya",
        usage=Usage(input_tokens=5, output_tokens=0),
    ))
    assert validate_envelope(original.to_dict()) == original


def test_validate_envelope_rejects_a_foreign_schema_version():
    payload = validate_answer(request(),
                              EngineAnswer(selected_option="bug_fix")).to_dict()
    payload["schema_version"] = "99.0"
    with pytest.raises(MalformedDecision, match="schema_version"):
        validate_envelope(payload)


def test_validate_envelope_rejects_a_forged_option_list():
    payload = validate_answer(request(),
                              EngineAnswer(selected_option="bug_fix")).to_dict()
    payload["allowed_options"] = ["bug_fix", "chore"]  # not in the registry
    with pytest.raises(OutOfScopeOption):
        validate_envelope(payload)


def test_validate_envelope_rejects_missing_required_fields():
    with pytest.raises(MalformedDecision):
        validate_envelope({"schema_version": SCHEMA_VERSION})
    with pytest.raises(MalformedDecision):
        validate_envelope({"schema_version": SCHEMA_VERSION, "decision_id": "",
                           "task_id": "t", "decision_type": "task_classification",
                           "selected_option": "bug_fix",
                           "allowed_options": list(TASK_OPTIONS)})
