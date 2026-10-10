"""Workflow vocabulary, task state machine and transition validation (Stage 3).

Stage 2 answered *one bounded question*. Stage 3 answers the question a developer
actually cares about next: **what may happen to this task, and why.**

Two vocabularies, deliberately not merged
-----------------------------------------
:mod:`layasdlc.contracts` defines ``Action`` -- the coarse *routing verdict* a
single decision produces (``proceed`` / ``investigate`` / ``escalate`` /
``abstain``). This module defines :class:`WorkflowAction`, the eight bounded
*workflow steps* a task moves through. They are different grains of the same
idea, so the mapping is explicit (:attr:`WorkflowAction.coarse`) rather than
accidental, and the two are never compared against each other.

The workflow vocabulary lives here rather than in ``contracts.py`` because it is
not part of the engine-facing schema: no engine is ever asked to choose one of
the eight, ``SCHEMA_VERSION`` does not describe it, and the TypeScript mirror
does not carry it. Folding it into the decision contract would mean versioning
and mirroring vocabulary that has nothing to do with an inference request.

Nothing here executes anything
------------------------------
``IMPLEMENT_CHANGE`` is a *permit to act*, not an act; the caller (Stage 5:
OpenCode) performs it. That keeps this layer a pure decision layer, which is
what makes the acceptance scenarios testable offline with no repository, no
shell and no network.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, FrozenSet, Mapping, Optional, Sequence

from .contracts import (
    Action,
    DecisionEnvelope,
    Evidence,
    SafetyClass,
    TaskKind,
    TaskState,
    VerificationState,
    evidence_state,
    utc_now,
)
from .errors import IncompleteTask, InvalidTransition
from .policy import PolicyConfig, requires_approval
from .safety import SafetyFinding, classify_safety


# ======================================================================================
# Vocabulary
# ======================================================================================


class WorkflowAction(str, Enum):
    """The eight bounded workflow steps (``Stages/stage3.md``).

    Each is a *permit to take one step*, never an execution. Ordered as a
    nominal lifecycle, which is also the order the deterministic routing
    priority uses.
    """

    INSPECT_REPOSITORY = "inspect_repository"
    RETRIEVE_CONTEXT = "retrieve_context"
    IMPLEMENT_CHANGE = "implement_change"
    RUN_TESTS = "run_tests"
    REVIEW_DIFF = "review_diff"
    ESCALATE = "escalate"
    REQUEST_APPROVAL = "request_approval"
    COMPLETE = "complete"

    @property
    def coarse(self) -> Action:
        """The Stage 1/2 routing verdict this step corresponds to.

        Explicit rather than implied, so the two vocabularies cannot drift
        silently. ``REQUEST_APPROVAL`` is an escalation in the coarse sense: it
        hands the decision to a human.
        """
        return _COARSE[self]


#: One-way mapping to the coarse verdict. Declared after the enum because it
#: refers to its members.
_COARSE: Mapping[WorkflowAction, Action] = MappingProxyType({
    WorkflowAction.INSPECT_REPOSITORY: Action.INVESTIGATE,
    WorkflowAction.RETRIEVE_CONTEXT: Action.INVESTIGATE,
    WorkflowAction.IMPLEMENT_CHANGE: Action.PROCEED,
    WorkflowAction.RUN_TESTS: Action.PROCEED,
    WorkflowAction.REVIEW_DIFF: Action.PROCEED,
    WorkflowAction.ESCALATE: Action.ESCALATE,
    WorkflowAction.REQUEST_APPROVAL: Action.ESCALATE,
    WorkflowAction.COMPLETE: Action.PROCEED,
})


class TaskPhase(str, Enum):
    """Where a task currently is.

    ``ESCALATED`` and ``COMPLETE`` are terminal on purpose: a task that has been
    handed to a human, or finished, does not silently resume.
    """

    CREATED = "created"
    INSPECTING = "inspecting"
    GATHERING_CONTEXT = "gathering_context"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    AWAITING_APPROVAL = "awaiting_approval"
    ESCALATED = "escalated"
    COMPLETE = "complete"


TERMINAL_PHASES: FrozenSet[TaskPhase] = frozenset({
    TaskPhase.ESCALATED, TaskPhase.COMPLETE,
})

#: The five steps that advance real work, and the phase each lands in.
_WORK_FLOWS: Mapping[WorkflowAction, TaskPhase] = MappingProxyType({
    WorkflowAction.INSPECT_REPOSITORY: TaskPhase.INSPECTING,
    WorkflowAction.RETRIEVE_CONTEXT: TaskPhase.GATHERING_CONTEXT,
    WorkflowAction.IMPLEMENT_CHANGE: TaskPhase.IMPLEMENTING,
    WorkflowAction.RUN_TESTS: TaskPhase.TESTING,
    WorkflowAction.REVIEW_DIFF: TaskPhase.REVIEWING,
})


def _build_transitions() -> Mapping[TaskPhase, Mapping[WorkflowAction, TaskPhase]]:
    """The transition table.

    Hand-written rather than derived, because the interesting entries are the
    *absences*:

    * terminal phases permit nothing;
    * ``AWAITING_APPROVAL`` permits only ``ESCALATE`` -- while an approval is
      pending the task is frozen, so no work step can be slipped in behind the
      approver's back.
    """
    rows: dict[TaskPhase, Mapping[WorkflowAction, TaskPhase]] = {}
    for phase in TaskPhase:
        if phase in TERMINAL_PHASES:
            rows[phase] = MappingProxyType({})
        elif phase is TaskPhase.AWAITING_APPROVAL:
            rows[phase] = MappingProxyType({
                WorkflowAction.ESCALATE: TaskPhase.ESCALATED,
            })
        else:
            row: dict[WorkflowAction, TaskPhase] = dict(_WORK_FLOWS)
            row[WorkflowAction.ESCALATE] = TaskPhase.ESCALATED
            row[WorkflowAction.REQUEST_APPROVAL] = TaskPhase.AWAITING_APPROVAL
            row[WorkflowAction.COMPLETE] = TaskPhase.COMPLETE
            rows[phase] = MappingProxyType(row)
    return MappingProxyType(rows)


#: ``current phase -> {action: next phase}``. Empty row == terminal.
TRANSITIONS: Mapping[TaskPhase, Mapping[WorkflowAction, TaskPhase]] = _build_transitions()

#: Deterministic tie-break and fallback order. A later action never precedes an
#: earlier one, so two runs over the same state choose the same step.
PRIORITY: tuple[WorkflowAction, ...] = tuple(WorkflowAction)


def permitted_from(phase: TaskPhase) -> tuple[WorkflowAction, ...]:
    """Actions legal from ``phase``, in :data:`PRIORITY` order."""
    row = TRANSITIONS[phase]
    return tuple(action for action in PRIORITY if action in row)


# ======================================================================================
# Completion conditions -- what "done" actually means
# ======================================================================================


#: The steps that constitute progress. ``REVIEW_DIFF`` and ``COMPLETE`` are
#: deliberately absent: reviewing work that was never done is not progress.
PROGRESS_ACTIONS: FrozenSet[WorkflowAction] = frozenset(
    action for action in _WORK_FLOWS if action is not WorkflowAction.REVIEW_DIFF
)


@dataclass(frozen=True)
class CompletionRule:
    """One named, checkable precondition for entering ``COMPLETE``.

    The rule is data rather than a bare function so the CLI can print *why* a
    task is not finished instead of just saying it is not.
    """

    key: str
    description: str
    check: Callable[["WorkflowTask"], bool]


def _is_reviewed(task: "WorkflowTask") -> bool:
    """Review is mandatory for *every* task, not just ones that changed source.

    Required unconditionally because :func:`_has_progress` already establishes
    that real work happened: a task that did something and was never reviewed is
    exactly the state this rule exists to block.
    """
    return any(r.action is WorkflowAction.REVIEW_DIFF for r in task.history)


def _has_progress(task: "WorkflowTask") -> bool:
    """At least one step that actually moved the work forward.

    Without this a task with no changes could satisfy ``reviewed`` and
    ``evidence`` by doing nothing at all, and would therefore be completable the
    moment it was created -- precisely the outcome "cannot be completed merely
    because Laya selected COMPLETE" forbids.
    """
    return any(r.action in PROGRESS_ACTIONS for r in task.history)


def _is_evidence_backed(task: "WorkflowTask") -> bool:
    """A change that was made must be a change that was tested.

    A task with no ``IMPLEMENT_CHANGE`` has nothing to verify, so it passes by
    construction. When evidence enforcement is switched off the rule degrades to
    "nothing to check" rather than to a forced pass -- the two are recorded
    differently because ``enforce_test_evidence`` is an explicit opt-out.
    """
    changed = any(r.action is WorkflowAction.IMPLEMENT_CHANGE for r in task.history)
    if not changed:
        return True
    if not task.policy.enforce_test_evidence:
        return True
    return any(evidence_state(evidence) is VerificationState.TESTS_PASSED
               for evidence in task.evidence)


def _approval_is_settled(task: "WorkflowTask") -> bool:
    if not requires_approval(task.finding, task.policy):
        return True
    return task.approval is not None and task.approval.granted


def _not_awaiting_approval(task: "WorkflowTask") -> bool:
    return task.phase is not TaskPhase.AWAITING_APPROVAL


#: The five conditions. Ordered from "was anything actually done?" through to
#: "is anything still pending?", so the first failure a caller sees is usually
#: the one they can act on.
COMPLETION_RULES: tuple[CompletionRule, ...] = (
    CompletionRule(
        "progress",
        "at least one workflow step actually moved the work forward",
        _has_progress,
    ),
    CompletionRule(
        "reviewed",
        "the change was reviewed (a REVIEW_DIFF step was recorded)",
        _is_reviewed,
    ),
    CompletionRule(
        "evidence",
        "every implemented change is backed by passing test evidence",
        _is_evidence_backed,
    ),
    CompletionRule(
        "approval",
        "approval was granted where the task required it",
        _approval_is_settled,
    ),
    CompletionRule(
        "not_awaiting_approval",
        "no approval request is still pending",
        _not_awaiting_approval,
    ),
)


# ======================================================================================
# Records
# ======================================================================================


@dataclass(frozen=True)
class Approval:
    """An out-of-band human decision. This service never grants one itself."""

    granted: bool
    by: str
    reason: Optional[str] = None
    at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {"granted": self.granted, "by": self.by, "reason": self.reason,
                "at": self.at}


@dataclass(frozen=True)
class ActionRecord:
    """One committed step, plus the justification for it.

    ``source`` reuses the Stage 2 vocabulary (``engine`` / ``fallback`` /
    ``policy``) so a workflow audit trail reads the same way a decision audit
    trail does. ``rules`` names the deterministic constraints that applied --
    stage3.md asks for exactly that, and a reason string alone cannot be
    asserted on in a test.
    """

    action: WorkflowAction
    from_phase: TaskPhase
    to_phase: TaskPhase
    source: str
    reason: str
    rules: tuple[str, ...] = ()
    decision_id: Optional[str] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    evidence: Optional[Evidence] = None
    at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "from_phase": self.from_phase.value,
            "to_phase": self.to_phase.value,
            "source": self.source,
            "reason": self.reason,
            "rules": list(self.rules),
            "decision_id": self.decision_id,
            "confidence": self.confidence,
            "error": self.error,
            "evidence": None if self.evidence is None else {
                "test_command": self.evidence.test_command,
                "tests_passed": self.evidence.tests_passed,
                "artifact": self.evidence.artifact,
                "checked_at": self.evidence.checked_at,
            },
            "at": self.at,
        }


# ======================================================================================
# The task record
# ======================================================================================


@dataclass
class WorkflowTask:
    """The mutable state of one engineering task.

    Deliberately distinct from :class:`layasdlc.contracts.TaskState`, which is a
    frozen *prompt* payload handed to an engine. This is the record the workflow
    advances, and it is what Stage 4 will persist.
    """

    task: TaskState
    finding: SafetyFinding = field(
        default_factory=lambda: SafetyFinding(SafetyClass.SAFE, (), False))
    #: The rules that decide "done" and "needs approval". Travels with the task
    #: so a resumed task is judged by the rules it was created under.
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    #: Classifies as ``documentation``/``investigation``? No -- supplied by the
    #: caller or by a task_classification decision; never inferred from text here.
    kind: Optional[TaskKind] = None
    phase: TaskPhase = TaskPhase.CREATED
    history: list[ActionRecord] = field(default_factory=list)
    #: Evidence references, oldest first. The most recent wins.
    evidence: list[Evidence] = field(default_factory=list)
    approval: Optional[Approval] = None
    #: The phase to restore to if the pending approval is granted.
    awaiting_from: Optional[TaskPhase] = None
    retries: int = 0
    #: How many times each ``failure_signature`` has been seen. This is what
    #: stops an identical failure from being retried forever.
    failure_signatures: Counter = field(default_factory=Counter)
    last_action: Optional[WorkflowAction] = None
    last_error: Optional[str] = None
    #: The signature of the most recent failure, if any. Kept alongside the
    #: counters so routing can ask "is *this* failure one we have already seen?"
    #: without re-deriving it from history.
    last_signature: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.task.task_id.strip():
            raise ValueError("a workflow task needs a non-empty task_id")

    # --- views -------------------------------------------------------------------------

    @property
    def task_id(self) -> str:
        return self.task.task_id

    @property
    def is_terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    @property
    def attempted_actions(self) -> frozenset[WorkflowAction]:
        """Actions already taken at least once. Drives the prefer-untried policy."""
        return frozenset(record.action for record in self.history)

    @property
    def last_record(self) -> Optional["ActionRecord"]:
        return self.history[-1] if self.history else None

    @property
    def permitted_actions(self) -> tuple[WorkflowAction, ...]:
        return permitted_from(self.phase)

    @property
    def verification(self) -> VerificationState:
        return evidence_state(self.evidence[-1] if self.evidence else None)

    @property
    def unmet_conditions(self) -> tuple[str, ...]:
        return tuple(rule.key for rule in COMPLETION_RULES if not rule.check(self))

    @property
    def can_complete(self) -> bool:
        return not self.unmet_conditions

    def rule_description(self, key: str) -> str:
        for rule in COMPLETION_RULES:
            if rule.key == key:
                return rule.description
        return key

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "subject": self.task.subject,
            "path": self.task.path,
            "kind": self.kind.value if self.kind else None,
            "phase": self.phase.value,
            "permitted_actions": [a.value for a in self.permitted_actions],
            "safety_class": self.finding.safety_class.value,
            "safety_reason": self.finding.reason,
            "requires_approval": requires_approval(self.finding, self.policy),
            "approval": self.approval.to_dict() if self.approval else None,
            "verification": self.verification.value,
            "retries": self.retries,
            "last_error": self.last_error,
            "unmet_conditions": list(self.unmet_conditions),
            "terminal": self.is_terminal,
            "history": [record.to_dict() for record in self.history],
            "evidence": [
                {"test_command": e.test_command, "tests_passed": e.tests_passed,
                 "artifact": e.artifact, "checked_at": e.checked_at}
                for e in self.evidence
            ],
        }


@dataclass(frozen=True)
class RouteDecision:
    """What the router chose, and every reason it had for choosing it."""

    action: WorkflowAction
    to_phase: TaskPhase
    reason: str
    #: The deterministic constraints that applied. Never empty: a route with no
    #: stated constraint is unauditable.
    rules: tuple[str, ...]
    #: ``policy`` (deterministic rule, no inference) | ``engine`` | ``fallback``.
    source: str
    permitted: tuple[WorkflowAction, ...]
    envelope: Optional[DecisionEnvelope] = None
    error: Optional[str] = None

    @property
    def confidence(self) -> Optional[float]:
        return self.envelope.confidence if self.envelope else None

    @property
    def decision_id(self) -> Optional[str]:
        return self.envelope.decision_id if self.envelope else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "to_phase": self.to_phase.value,
            "reason": self.reason,
            "rules": list(self.rules),
            "source": self.source,
            "permitted": [a.value for a in self.permitted],
            "confidence": self.confidence,
            "decision_id": self.decision_id,
            "error": self.error,
            "coarse": self.action.coarse.value,
        }


# ======================================================================================
# Transition validation
# ======================================================================================


def validate_transition(phase: TaskPhase, action: WorkflowAction) -> TaskPhase:
    """Return the phase ``action`` lands on, or raise :class:`InvalidTransition`.

    Pure and table-driven: the model is never consulted, so no amount of
    confidence can widen it.
    """
    row = TRANSITIONS[phase]
    if action not in row:
        permitted = permitted_from(phase)
        if phase in TERMINAL_PHASES:
            raise InvalidTransition(
                f"{action.value} is not permitted: task is already "
                f"{phase.value} and {phase.value} is terminal",
                from_phase=phase.value,
                action=action.value,
                permitted=tuple(a.value for a in permitted),
            )
        raise InvalidTransition(
            f"{action.value} is not permitted from {phase.value}",
            from_phase=phase.value,
            action=action.value,
            permitted=tuple(a.value for a in permitted),
        )
    return row[action]


def guard_complete(task: WorkflowTask) -> None:
    """Raise :class:`IncompleteTask` unless every completion condition holds.

    This is the check that makes "a task cannot be completed merely because Laya
    selected COMPLETE" true. ``WorkflowTask.can_complete`` is the non-raising
    view of the same thing.
    """
    unmet = task.unmet_conditions
    if not unmet:
        return
    detail = "; ".join(f"{key}: {task.rule_description(key)}" for key in unmet)
    raise IncompleteTask(
        f"task {task.task_id!r} cannot be completed -- {detail}",
        unmet=unmet,
    )


def failure_signature(action: Optional[WorkflowAction], error: Optional[str]) -> Optional[str]:
    """A coarse identity for "the same thing went wrong again".

    Keyed on the **action and the message, not the phase**. Including the phase
    would sound more precise, and would defeat the purpose: a router that cycles
    through ``inspect -> gather -> implement -> test`` reaches the same failing
    step again from a different phase each time, so a phase-qualified signature
    never repeats and the loop goes undetected. What makes a repeat a repeat is
    the same step failing with the same message.

    Normalises **whitespace and case only**. It deliberately does not attempt to
    strip ids, timings or paths out of the message: over-normalising would merge
    genuinely different failures, which is worse than missing a loop, because the
    consequence of merging is an escalation the record does not justify.

    The trade-off is recorded rather than hidden: an error whose text varies from
    run to run will not be recognised as a repeat. That case is still bounded --
    by ``max_retries`` on consecutive failures and by ``max_steps`` on the task as
    a whole -- so a loop is never unbounded, only less precisely labelled.
    """
    if not error:
        return None
    text = " ".join(str(error).split()).lower()
    if not text:
        return None
    return f"{action.value if action else '-'}:{text}"


def new_task(state: TaskState, *, kind: Optional[TaskKind] = None,
             policy: Optional[PolicyConfig] = None,
             finding: Optional[SafetyFinding] = None) -> WorkflowTask:
    """Register a task, applying the deterministic safety scan up front.

    Safety is decided here, once, from the task text -- never from a model. A
    destructive or deployment task is therefore gated before any engine is
    asked for a single step.
    """
    return WorkflowTask(
        task=state,
        finding=finding if finding is not None else classify_safety(
            state.as_prompt_state()),
        policy=policy if policy is not None else PolicyConfig(),
        kind=kind,
    )


__all__ = [
    "ActionRecord",
    "Approval",
    "COMPLETION_RULES",
    "CompletionRule",
    "PRIORITY",
    "PROGRESS_ACTIONS",
    "RouteDecision",
    "TERMINAL_PHASES",
    "TRANSITIONS",
    "TaskPhase",
    "WorkflowAction",
    "WorkflowTask",
    "failure_signature",
    "guard_complete",
    "new_task",
    "permitted_from",
    "validate_transition",
]
