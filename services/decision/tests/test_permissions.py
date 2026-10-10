"""Stage 2 requirement 8: a model decision must never widen tool access."""

from __future__ import annotations

import pytest

from layasdlc import (
    ControllerConfig,
    DeterministicEngine,
    EngineAnswer,
    FakeEngine,
    Outcome,
    PermissionDenied,
    ToolPermissionPolicy,
    WorkflowController,
    guard_decision,
    narrow_options,
)
from layasdlc.contracts import DecisionEnvelope, SCHEMA_VERSION
from layasdlc.engines.fake import answer

WORKFLOW = ("edit_code", "run_tests", "read_investigate", "update_docs")


def envelope_for(option: str, decision_type: str = "workflow_selection") -> DecisionEnvelope:
    return DecisionEnvelope(
        schema_version=SCHEMA_VERSION, decision_id="d", task_id="T",
        decision_type=decision_type, allowed_options=(option,),
        selected_option=option, confidence=0.9, rationale=None,
        model=None, model_version=None, latency_ms=None, usage=None,
    )


# --- layer 1: narrowing before any engine is called -------------------------------------


def test_non_tool_decisions_are_never_filtered():
    """Classification labels are choices, not permissions."""
    options = ("bug_fix", "feature")
    assert narrow_options("task_classification", options,
                          ToolPermissionPolicy.read_only()) == options


def test_workflow_options_are_filtered_to_permitted_tools():
    policy = ToolPermissionPolicy.read_only()  # allows read_investigate only
    assert narrow_options("workflow_selection", WORKFLOW, policy) == ("read_investigate",)


def test_narrowing_preserves_order_and_removes_only_disallowed():
    policy = ToolPermissionPolicy.of({"run_tests", "edit_code"})
    assert narrow_options("workflow_selection", WORKFLOW, policy) == ("edit_code",
                                                                      "run_tests")


def test_narrowing_fails_closed_when_nothing_remains():
    policy = ToolPermissionPolicy.read_only()
    with pytest.raises(PermissionDenied) as excinfo:
        narrow_options("workflow_selection", ("edit_code", "run_tests"), policy)
    assert excinfo.value.tool  # carries what was refused


# --- layer 2: re-checking the validated envelope ----------------------------------------


def test_guard_allows_a_permitted_workflow_choice():
    guard_decision(envelope_for("read_investigate"),
                   ToolPermissionPolicy.read_only())  # must not raise


def test_guard_refuses_a_non_permitted_workflow_choice():
    with pytest.raises(PermissionDenied) as excinfo:
        guard_decision(envelope_for("edit_code"), ToolPermissionPolicy.read_only())
    assert excinfo.value.tool == "edit_code"


def test_guard_ignores_non_tool_decision_types():
    guard_decision(envelope_for("bug_fix", decision_type="task_classification"),
                   ToolPermissionPolicy.read_only())  # must not raise


# --- policy construction -----------------------------------------------------------------


def test_read_only_is_the_default_and_excludes_mutation():
    policy = ToolPermissionPolicy.read_only()
    assert policy.permits("read_investigate")
    assert not policy.permits("edit_code")
    assert not policy.permits("run_tests")


def test_full_policy_is_explicit_opt_in():
    policy = ToolPermissionPolicy.full()
    assert set(policy.allowed_tools) == set(WORKFLOW)


def test_guard_reports_the_allowed_set_when_denying():
    policy = ToolPermissionPolicy.of({"read_investigate"})
    with pytest.raises(PermissionDenied, match="read_investigate"):
        policy.guard("edit_code")


# --- end to end: the controller never lets the model choose a forbidden tool ------------

#: Two permitted tools. Narrowing still filters (edit_code and update_docs are
#: removed) but leaves a genuine choice, so the engine is actually consulted and
#: layer 2 has something to re-check. With only one permitted tool the option set
#: collapses and the controller settles it from policy without inference -- see
#: the forced-choice section below.
TWO_TOOLS = ToolPermissionPolicy.of({"read_investigate", "run_tests"})
TWO_TOOL_OPTIONS = ("run_tests", "read_investigate")   # narrowed, WORKFLOW order


def test_the_engine_is_only_ever_offered_permitted_options(task_state):
    engine = FakeEngine(default=answer("read_investigate", confidence=0.9,
                                       allowed=TWO_TOOL_OPTIONS))
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine(),
                                    permissions=TWO_TOOLS)

    result = controller.decide(task_state, "workflow_selection")

    offered = engine.records[0].allowed_options
    assert offered == TWO_TOOL_OPTIONS, \
        "non-permitted tools must be removed before the engine is consulted"
    assert result.source == "engine"
    assert all(controller.permissions.permits(o) for o in offered)


def test_an_engine_returning_a_forbidden_tool_is_rejected(task_state):
    """Even an engine that ignores the narrowed option set cannot get through."""
    engine = FakeEngine(default=EngineAnswer(selected_option="edit_code", confidence=0.99))
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine(),
                                    permissions=TWO_TOOLS)

    result = controller.decide(task_state, "workflow_selection")

    assert result.outcome is Outcome.FALLBACK
    assert "OutOfScopeOption" in result.error
    assert result.envelope is not None
    # The baseline was handed the already-narrowed set, so its keyword-driven
    # answer can only land on a permitted tool.
    assert result.envelope.selected_option == "run_tests"
    assert controller.permissions.permits(result.envelope.selected_option)


def test_confidence_cannot_buy_permission(task_state):
    """A maximally confident forbidden choice is still refused."""
    from layasdlc import PolicyConfig

    engine = FakeEngine(default=EngineAnswer(selected_option="edit_code", confidence=1.0))
    controller = WorkflowController(
        engine=engine,
        config=ControllerConfig(policy=PolicyConfig(fallback_enabled=False)),
        permissions=TWO_TOOLS,
    )

    result = controller.decide(task_state, "workflow_selection")
    assert result.outcome is Outcome.REJECTED
    assert result.envelope is None


def test_fallback_output_is_also_subject_to_the_policy(task_state):
    """Layer 2 applies to the fallback answer too, not just the model's."""
    engine = FakeEngine(default=EngineAnswer(selected_option="nonsense", confidence=0.99))
    controller = WorkflowController(
        engine=engine,
        fallback=DeterministicEngine(),
        permissions=TWO_TOOLS,
    )
    result = controller.decide(task_state, "workflow_selection")

    assert result.outcome is Outcome.FALLBACK
    assert result.envelope is not None
    assert result.envelope.selected_option == "run_tests"
    assert controller.permissions.permits(result.envelope.selected_option)


# --- a collapsed option set is settled without inference --------------------------------


def test_a_single_permitted_tool_never_reaches_the_engine(task_state):
    engine = FakeEngine(default=answer("read_investigate", confidence=0.9))
    controller = WorkflowController(engine=engine, fallback=DeterministicEngine(),
                                    permissions=ToolPermissionPolicy.read_only())

    result = controller.decide(task_state, "workflow_selection")

    assert engine.records == [], \
        "a question with exactly one possible answer is not a decision to make"
    assert result.outcome is Outcome.DECIDED
    assert result.source == "policy"
    assert result.envelope is not None
    assert result.envelope.selected_option == "read_investigate"


def test_a_single_permitted_tool_survives_a_broken_engine(task_state):
    """Nothing to ask means nothing to fail -- and no request to a dead model."""
    class Exploding:
        name = "exploding"
        version = "0"

        def available(self):
            return False

        def decide(self, request):  # pragma: no cover - must never be reached
            raise RuntimeError("model is down")

    controller = WorkflowController(engine=Exploding(), fallback=None,
                                    permissions=ToolPermissionPolicy.read_only())

    result = controller.decide(task_state, "workflow_selection")

    assert result.outcome is Outcome.DECIDED
    assert result.error is None
    assert result.envelope is not None
    assert result.envelope.selected_option == "read_investigate"


def test_a_policy_answer_is_certain_by_construction_not_by_measurement(task_state):
    """Confidence 1.0 here means 'no alternative existed', not 'the model felt sure'."""
    controller = WorkflowController(engine=FakeEngine(),
                                    permissions=ToolPermissionPolicy.read_only())

    result = controller.decide(task_state, "workflow_selection")
    envelope = result.envelope

    assert envelope is not None
    assert envelope.confidence == 1.0
    # No model was consulted, so none may be credited with the answer.
    assert envelope.model is None
    assert envelope.model_version is None
    assert envelope.usage is None, "no tokens were spent, so none may be claimed"
    assert envelope.rationale is None
    assert result.latency_ms >= 0.0


def test_the_policy_source_is_recorded_separately_from_the_engine(task_state):
    """'How often did the real model answer?' must be answerable from metrics."""
    controller = WorkflowController(engine=FakeEngine(),
                                    permissions=ToolPermissionPolicy.read_only())

    controller.decide(task_state, "workflow_selection")

    assert controller.metrics.counter("source.policy") == 1
    assert controller.metrics.counter("source.engine") == 0


def test_a_one_option_question_still_returns_a_valid_versioned_envelope(task_state):
    controller = WorkflowController(engine=FakeEngine(),
                                    permissions=ToolPermissionPolicy.read_only())

    result = controller.decide(task_state, "workflow_selection")
    payload = result.envelope.to_dict()

    assert payload["schema_version"] == result.envelope.schema_version
    assert payload["selected_option"] == "read_investigate"
    assert payload["allowed_options"] == ["read_investigate"]
    assert payload["usage"] is None
