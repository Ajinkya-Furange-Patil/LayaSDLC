"""The Stage 3 state machine: vocabulary, transition table, completion conditions.

Everything here is pure -- no engine, no network, no filesystem -- so these
tests pin the rules themselves rather than any particular way of reaching them.
"""

from __future__ import annotations

import pytest

from layasdlc import (
    Action,
    Evidence,
    IncompleteTask,
    InvalidTransition,
    PolicyConfig,
    SafetyClass,
    SafetyFinding,
    TaskKind,
    TaskPhase,
    TaskState,
    WorkflowAction,
    WorkflowTask,
    classify_safety,
    new_task,
    validate_transition,
)
from layasdlc.workflow import (
    COMPLETION_RULES,
    PRIORITY,
    PROGRESS_ACTIONS,
    TERMINAL_PHASES,
    TRANSITIONS,
    failure_signature,
    guard_complete,
    permitted_from,
)

EIGHT = (
    "inspect_repository", "retrieve_context", "implement_change", "run_tests",
    "review_diff", "escalate", "request_approval", "complete",
)


# ======================================================================================
# Vocabulary
# ======================================================================================


def test_the_eight_workflow_actions_exist():
    assert tuple(a.value for a in WorkflowAction) == EIGHT


@pytest.mark.parametrize("action,coarse", [
    (WorkflowAction.INSPECT_REPOSITORY, Action.INVESTIGATE),
    (WorkflowAction.RETRIEVE_CONTEXT, Action.INVESTIGATE),
    (WorkflowAction.IMPLEMENT_CHANGE, Action.PROCEED),
    (WorkflowAction.RUN_TESTS, Action.PROCEED),
    (WorkflowAction.REVIEW_DIFF, Action.PROCEED),
    (WorkflowAction.ESCALATE, Action.ESCALATE),
    (WorkflowAction.REQUEST_APPROVAL, Action.ESCALATE),
    (WorkflowAction.COMPLETE, Action.PROCEED),
])
def test_every_action_maps_onto_the_coarse_verdict(action, coarse):
    """The two vocabularies are related explicitly, not by coincidence."""
    assert action.coarse is coarse


def test_priority_is_the_declaration_order_and_is_total():
    assert PRIORITY == tuple(WorkflowAction)
    assert len(set(PRIORITY)) == len(EIGHT)


def test_progress_excludes_review_and_complete():
    """Reviewing work that was never done is not progress."""
    assert WorkflowAction.REVIEW_DIFF not in PROGRESS_ACTIONS
    assert WorkflowAction.COMPLETE not in PROGRESS_ACTIONS
    assert WorkflowAction.IMPLEMENT_CHANGE in PROGRESS_ACTIONS


# ======================================================================================
# Transition table
# ======================================================================================


def test_terminal_phases_permit_nothing():
    for phase in TERMINAL_PHASES:
        assert TRANSITIONS[phase] == {}, f"{phase} should be terminal"
    assert permitted_from(TaskPhase.COMPLETE) == ()
    assert permitted_from(TaskPhase.ESCALATED) == ()


def test_awaiting_approval_permits_only_escalation():
    """While a human is deciding, the task is frozen: no work can slip past."""
    assert permitted_from(TaskPhase.AWAITING_APPROVAL) == (WorkflowAction.ESCALATE,)


@pytest.mark.parametrize("phase", [p for p in TaskPhase
                                   if p not in TERMINAL_PHASES
                                   and p is not TaskPhase.AWAITING_APPROVAL])
def test_every_open_phase_permits_the_full_work_set(phase):
    permitted = set(permitted_from(phase))
    assert {a for a in WorkflowAction
            if a not in (WorkflowAction.ESCALATE, WorkflowAction.REQUEST_APPROVAL,
                         WorkflowAction.COMPLETE)} <= permitted
    assert {WorkflowAction.ESCALATE, WorkflowAction.REQUEST_APPROVAL,
            WorkflowAction.COMPLETE} <= permitted


@pytest.mark.parametrize("action,expected", [
    (WorkflowAction.INSPECT_REPOSITORY, TaskPhase.INSPECTING),
    (WorkflowAction.RETRIEVE_CONTEXT, TaskPhase.GATHERING_CONTEXT),
    (WorkflowAction.IMPLEMENT_CHANGE, TaskPhase.IMPLEMENTING),
    (WorkflowAction.RUN_TESTS, TaskPhase.TESTING),
    (WorkflowAction.REVIEW_DIFF, TaskPhase.REVIEWING),
    (WorkflowAction.ESCALATE, TaskPhase.ESCALATED),
    (WorkflowAction.REQUEST_APPROVAL, TaskPhase.AWAITING_APPROVAL),
    (WorkflowAction.COMPLETE, TaskPhase.COMPLETE),
])
def test_validate_transition_lands_where_the_table_says(action, expected):
    assert validate_transition(TaskPhase.CREATED, action) is expected


def test_validate_transition_rejects_and_reports_what_was_allowed():
    with pytest.raises(InvalidTransition) as excinfo:
        validate_transition(TaskPhase.COMPLETE, WorkflowAction.RUN_TESTS)
    error = excinfo.value
    assert error.from_phase == TaskPhase.COMPLETE.value
    assert error.action == WorkflowAction.RUN_TESTS.value
    assert error.permitted == []
    assert "terminal" in str(error)


def test_validate_transition_rejects_work_while_awaiting_approval():
    with pytest.raises(InvalidTransition) as excinfo:
        validate_transition(TaskPhase.AWAITING_APPROVAL, WorkflowAction.IMPLEMENT_CHANGE)
    assert excinfo.value.permitted == [WorkflowAction.ESCALATE.value]


# ======================================================================================
# Completion conditions
# ======================================================================================


def test_completion_rules_are_named_and_documented():
    keys = [rule.key for rule in COMPLETION_RULES]
    assert keys == ["progress", "reviewed", "evidence", "approval",
                    "not_awaiting_approval"]
    assert all(rule.description.strip() for rule in COMPLETION_RULES)


def test_a_fresh_task_cannot_be_completed():
    """The rule the whole stage turns on: COMPLETE is never just a model choice."""
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX)
    assert task.phase is TaskPhase.CREATED
    assert set(task.unmet_conditions) >= {"progress", "reviewed"}

    with pytest.raises(IncompleteTask) as excinfo:
        guard_complete(task)
    assert "progress" in excinfo.value.unmet
    assert "reviewed" in excinfo.value.unmet


def test_progress_without_review_is_not_complete():
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX)
    from layasdlc.workflow import ActionRecord
    task.history.append(ActionRecord(
        action=WorkflowAction.IMPLEMENT_CHANGE, from_phase=TaskPhase.CREATED,
        to_phase=TaskPhase.IMPLEMENTING, source="policy", reason="test"))

    assert task.unmet_conditions == ("reviewed", "evidence")


def test_a_change_without_passing_evidence_is_not_complete():
    task = _task_with_change()
    from layasdlc.workflow import ActionRecord
    task.history.append(ActionRecord(
        action=WorkflowAction.REVIEW_DIFF, from_phase=TaskPhase.IMPLEMENTING,
        to_phase=TaskPhase.REVIEWING, source="policy", reason="test"))

    assert "evidence" in task.unmet_conditions
    assert not task.can_complete


def test_a_reviewed_change_with_passing_evidence_can_complete():
    task = _task_with_change(evidence=Evidence.record("pytest", True))
    from layasdlc.workflow import ActionRecord
    task.history.append(ActionRecord(
        action=WorkflowAction.REVIEW_DIFF, from_phase=TaskPhase.IMPLEMENTING,
        to_phase=TaskPhase.REVIEWING, source="policy", reason="test"))

    assert task.unmet_conditions == ()
    guard_complete(task)  # must not raise


def test_evidence_with_no_command_does_not_count_as_passing():
    task = _task_with_change(evidence=Evidence(test_command="", tests_passed=True))
    from layasdlc.workflow import ActionRecord
    task.history.append(ActionRecord(
        action=WorkflowAction.REVIEW_DIFF, from_phase=TaskPhase.IMPLEMENTING,
        to_phase=TaskPhase.REVIEWING, source="policy", reason="test"))

    assert "evidence" in task.unmet_conditions


def test_an_approval_that_is_still_pending_blocks_completion():
    task = new_task(TaskState(task_id="T-1", subject="Drop the users table"),
                    kind=TaskKind.INVESTIGATION)
    assert task.finding.safety_class is SafetyClass.DESTRUCTIVE

    from layasdlc.workflow import ActionRecord
    task.history.extend([
        ActionRecord(action=WorkflowAction.INSPECT_REPOSITORY,
                     from_phase=TaskPhase.CREATED, to_phase=TaskPhase.INSPECTING,
                     source="policy", reason="test"),
        ActionRecord(action=WorkflowAction.REVIEW_DIFF,
                     from_phase=TaskPhase.INSPECTING, to_phase=TaskPhase.REVIEWING,
                     source="policy", reason="test"),
    ])
    task.phase = TaskPhase.AWAITING_APPROVAL

    assert set(task.unmet_conditions) >= {"approval", "not_awaiting_approval"}


def test_completion_rules_cannot_be_contradicted_by_the_complement():
    """``unmet_conditions`` and the printed reasons must agree about one task."""
    task = _task_with_change(evidence=Evidence.record("pytest", True))
    from layasdlc.workflow import ActionRecord
    task.history.append(ActionRecord(
        action=WorkflowAction.REVIEW_DIFF, from_phase=TaskPhase.IMPLEMENTING,
        to_phase=TaskPhase.REVIEWING, source="policy", reason="test"))
    unmet = set(task.unmet_conditions)
    described = {key for key in unmet if task.rule_description(key) != key}
    assert described == unmet  # every unmet key resolves to a real description


# ======================================================================================
# Task construction
# ======================================================================================


def test_new_task_runs_the_deterministic_safety_scan():
    task = new_task(TaskState(task_id="T-1", subject="Deploy checkout to production"),
                    kind=TaskKind.FEATURE)
    assert task.finding.safety_class is SafetyClass.DEPLOYMENT
    assert task.finding.requires_approval is True
    assert "deploy" in task.finding.reason.lower()


def test_a_safe_task_needs_no_approval():
    task = new_task(TaskState(task_id="T-1", subject="Fix the typo in the README"),
                    kind=TaskKind.DOCUMENTATION)
    assert task.finding.safety_class is SafetyClass.SAFE
    assert task.finding.requires_approval is False


def test_new_task_accepts_an_explicit_finding():
    finding = SafetyFinding(SafetyClass.DESTRUCTIVE, ("drop table",), True)
    task = new_task(TaskState(task_id="T-1", subject="anything"), finding=finding)
    assert task.finding is finding


def test_a_task_needs_an_identifier():
    with pytest.raises(ValueError):
        new_task(TaskState(task_id="   ", subject="Fix the crash"))


def test_safety_is_classified_from_the_whole_prompt_state():
    """Path and body count, not just the subject line."""
    finding = classify_safety(
        TaskState(task_id="T-1", subject="Routine change",
                  body="then force push to main").as_prompt_state())
    assert finding.requires_approval is True


# ======================================================================================
# Failure signatures
# ======================================================================================


def test_a_signature_keeps_the_step_and_the_message():
    signature = failure_signature(WorkflowAction.RUN_TESTS,
                                  "EngineTimeout: timed out after 5s")
    assert signature is not None
    assert signature.startswith("run_tests:")


def test_a_signature_has_no_phase_component():
    """Keyed on action + message only.

    The phase is deliberately absent: a cycle reaches the same failing step from
    a different phase each time, so a phase-qualified signature would never
    compare equal to itself and the loop would go undetected. The behavioural
    consequence is pinned in ``test_router.py``.
    """
    assert failure_signature(WorkflowAction.RUN_TESTS, "boom") == "run_tests:boom"


def test_a_signature_normalises_whitespace_and_case():
    """Two runs of one failure must compare equal, or a loop is never seen."""
    first = failure_signature(WorkflowAction.RUN_TESTS,
                              "EngineTimeout[a]:  did not\n answer  within 10s")
    second = failure_signature(WorkflowAction.RUN_TESTS,
                               "enginetimeout[a]: did not answer within 10s")
    assert first == second


def test_a_signature_does_not_pretend_to_normalise_volatile_detail():
    """Documented limitation, pinned so it cannot be quietly relied upon.

    A message that embeds a different value each run will not be recognised as a
    repeat. That is the safe failure direction -- over-normalising would merge
    genuinely different failures -- and the loop is still bounded by ``max_retries``
    and ``max_steps``.
    """
    first = failure_signature(WorkflowAction.RUN_TESTS,
                              "EngineTimeout[a]: timed out after 10.0s")
    second = failure_signature(WorkflowAction.RUN_TESTS,
                               "EngineTimeout[a]: timed out after 5.0s")
    assert first != second


def test_a_different_step_produces_a_different_signature():
    assert (failure_signature(WorkflowAction.RUN_TESTS, "boom")
            != failure_signature(WorkflowAction.IMPLEMENT_CHANGE, "boom"))


def test_a_different_message_produces_a_different_signature():
    assert (failure_signature(WorkflowAction.RUN_TESTS, "boom")
            != failure_signature(WorkflowAction.RUN_TESTS, "bang"))


def test_no_error_means_no_signature():
    assert failure_signature(WorkflowAction.RUN_TESTS, None) is None
    assert failure_signature(None, "   ") is None


# ======================================================================================
# Serialisation
# ======================================================================================


def test_to_dict_exposes_what_an_operator_needs():
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX)
    payload = task.to_dict()

    assert payload["task_id"] == "T-1"
    assert payload["phase"] == "created"
    assert payload["terminal"] is False
    assert payload["safety_class"] == "safe"
    assert payload["verification"] == "unverified"
    assert set(payload["permitted_actions"]) == {a.value for a in task.permitted_actions}
    assert payload["history"] == []
    assert payload["unmet_conditions"] == list(task.unmet_conditions)


def test_policy_travels_with_the_task():
    """A resumed task must be judged by the rules it was created under."""
    config = PolicyConfig(min_confidence=0.9, enforce_test_evidence=False)
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX, policy=config)
    assert task.policy is config
    assert task.to_dict()["requires_approval"] is False


# --- helpers -------------------------------------------------------------------------


def _task_with_change(evidence: Evidence | None = None) -> WorkflowTask:
    from layasdlc.workflow import ActionRecord
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX)
    task.history.append(ActionRecord(
        action=WorkflowAction.IMPLEMENT_CHANGE, from_phase=TaskPhase.CREATED,
        to_phase=TaskPhase.IMPLEMENTING, source="engine", reason="engine chose edit_code"))
    if evidence is not None:
        task.evidence.append(evidence)
    return task
