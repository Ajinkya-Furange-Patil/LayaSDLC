"""Deterministic routing: turning a validated decision into the next permitted
workflow step (Stage 3).

The rule this module exists to guarantee:

    **A model chooses among steps that are already permitted; it never decides
    which steps are permitted.**

Routing runs as a fixed sequence of checks. The mandatory ones come first and no
engine is consulted for any of them, because an engine must not be able to talk
itself past a gate:

1. **completion** -- if every condition holds, finish;
2. **approval** -- a destructive or deployment task stops until a human answers;
3. **budgets** -- consecutive retries, repeats of one identical failure, failed
   test runs, and total steps. Four independent bounds, each with its own logged
   reason, so escalation is always attributable to a specific number;
4. **exhausted work** -- tried every work action and the tests still fail;
5. **ambiguity** -- a task that is still unclassified after context has been
   retrieved is escalated rather than guessed at;
6. **failed tests** -- the one step where a *model-backed* decision is mandatory:
   :data:`layasdlc.contracts.DecisionType.RETRY_VS_ESCALATE` exists precisely to
   separate retrying from escalating;
7. **sequencing** -- a change must be tested, and tested work must be reviewed;
8. **bounded inference** -- only if all of the above leave the question open does
   the router ask which work to do next, and only among tools whose action is
   legal from the current phase.

Two deliberate properties
-------------------------
*Prefer untried.* When several steps are legal, ones already taken are dropped
first. Without this a model that keeps preferring its favourite tool would cycle
forever, and the completion conditions -- which require testing and review --
could never be reached.

*No silent success.* A route that no usable decision backs carries an ``error``.
It is still a legal step (the deterministic fallback produced it), but it counts
against the retry budget, so an engine that is down for good leads to escalation
rather than to an unbounded sequence of confident-looking defaults.

Nothing here executes anything: the router *permits* ``IMPLEMENT_CHANGE`` and
``RUN_TESTS``, it never runs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .contracts import (
    DECISION_SPACE,
    DecisionType,
    Evidence,
    Outcome,
    TaskKind,
    VerificationState,
    evidence_state,
)
from .controller import WorkflowController
from .errors import InvalidTransition
from .metrics import get_logger
from .policy import requires_approval
from .workflow import (
    COMPLETION_RULES,
    PRIORITY,
    PROGRESS_ACTIONS,
    TERMINAL_PHASES,
    ActionRecord,
    Approval,
    RouteDecision,
    TaskPhase,
    WorkflowAction,
    WorkflowTask,
    failure_signature,
    guard_complete,
    validate_transition,
)

_log = get_logger("router")

_WORKFLOW_DECISION = DecisionType.WORKFLOW_SELECTION.value
_RETRY_DECISION = DecisionType.RETRY_VS_ESCALATE.value

#: Kinds whose next step plausibly touches source, so context must come first.
#: ``None`` (unclassified) is deliberately included: an unclassified task is
#: exactly the case where looking before leaping costs less than guessing.
CONTEXT_FIRST_KINDS: frozenset = frozenset(
    {kind for kind in TaskKind
     if kind not in (TaskKind.DOCUMENTATION, TaskKind.INVESTIGATION)}
    | {None}
)

#: Kinds for which producing something is the point of the task. Everything but
#: investigation, which is the one kind that can finish without changing or
#: writing anything. Kept separate from :data:`CONTEXT_FIRST_KINDS`: a
#: documentation task does need a deliverable, it just does not need repository
#: context before starting.
CHANGE_KINDS: frozenset = frozenset(
    kind for kind in TaskKind if kind is not TaskKind.INVESTIGATION
) | {None}

#: Diagnosis order for "try again after a red test run": look, then fix, then
#: re-test. Ordered so a retry makes progress rather than repeating the step that
#: just failed.
_RETRY_PRIORITY: tuple[WorkflowAction, ...] = (
    WorkflowAction.INSPECT_REPOSITORY,
    WorkflowAction.IMPLEMENT_CHANGE,
    WorkflowAction.RUN_TESTS,
    WorkflowAction.RETRIEVE_CONTEXT,
)


def action_for_tool(tool: Optional[str], task: WorkflowTask) -> Optional[WorkflowAction]:
    """Map a ``workflow_selection`` tool identifier onto a workflow action.

    ``read_investigate`` is the only state-dependent one: it means "look at the
    repository" before anything is known, and "get more context" once something
    has been looked at. That keeps the closed four-tool vocabulary able to reach
    every work step without adding a fifth tool the model could ask for.
    """
    if tool is None:
        return None
    if tool in ("edit_code", "update_docs"):
        return WorkflowAction.IMPLEMENT_CHANGE
    if tool == "run_tests":
        return WorkflowAction.RUN_TESTS
    if tool == "read_investigate":
        seen = WorkflowAction.INSPECT_REPOSITORY in task.attempted_actions
        return (WorkflowAction.RETRIEVE_CONTEXT if seen
                else WorkflowAction.INSPECT_REPOSITORY)
    return None


def tools_for(permitted: Sequence[WorkflowAction], task: WorkflowTask) -> tuple[str, ...]:
    """Tools whose mapped action is legal right now, in decision-space order.

    Computed *before* the engine is asked, so the question put to it is already
    answerable. A tool with no legal action is never offered -- asking would only
    create an answer we would have to throw away.

    The caller additionally filters this by its tool permission policy. The
    controller narrows internally too, but a set that survives *this* filter and
    then narrows to nothing is a question the controller cannot answer at all,
    so the router is responsible for not constructing one.
    """
    usable: list[str] = []
    for tool in DECISION_SPACE[DecisionType.WORKFLOW_SELECTION]:
        action = action_for_tool(tool, task)
        if action in permitted and tool not in usable:
            usable.append(tool)
    return tuple(usable)


def prefer_untried(actions: Sequence[WorkflowAction],
                   task: WorkflowTask) -> tuple[WorkflowAction, ...]:
    """Drop actions already taken, unless that would drop all of them.

    This is what stops a loop: with it, a model that always answers
    ``update_docs`` still ends up testing and reviewing, because those are the
    only untried options left. Returning everything rather than nothing means a
    task that genuinely needs to repeat a step can.
    """
    untried = tuple(a for a in actions if a not in task.attempted_actions)
    return untried or tuple(actions)


def must_test(task: WorkflowTask) -> bool:
    """A change has been made that no test run has covered since."""
    change = _last_index(task.history, WorkflowAction.IMPLEMENT_CHANGE)
    if change is None:
        return False
    return not any(r.action is WorkflowAction.RUN_TESTS for r in task.history[change + 1:])


def _context_gathered(task: WorkflowTask) -> bool:
    """The task has already looked at the repository at least once."""
    return bool(task.attempted_actions & {
        WorkflowAction.INSPECT_REPOSITORY, WorkflowAction.RETRIEVE_CONTEXT})


def _last_index(history: Sequence[ActionRecord],
                action: WorkflowAction) -> Optional[int]:
    for index in range(len(history) - 1, -1, -1):
        if history[index].action is action:
            return index
    return None


@dataclass
class WorkflowRouter:
    """Routes a :class:`~layasdlc.workflow.WorkflowTask` to its next step.

    Bounded by construction. ``max_retries`` caps consecutive failed steps,
    ``max_identical_failures`` caps repeats of *the same* failure,
    ``max_test_failures`` caps the diagnose-retry loop around a red test run, and
    ``max_steps`` caps the whole task. Four independent budgets: a task cannot run
    forever no matter which rule is being violated.
    """

    controller: WorkflowController
    max_retries: int = 3
    max_identical_failures: int = 3
    max_test_failures: int = 3
    max_steps: int = 25

    def __post_init__(self) -> None:
        for name in ("max_retries", "max_identical_failures", "max_test_failures",
                     "max_steps"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")

    # --- mandatory rules (no engine is consulted) --------------------------------------

    def _completion_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        if not task.can_complete:
            return None
        return self._policy_route(
            task, WorkflowAction.COMPLETE,
            reason=("every completion condition holds: "
                    + ", ".join(_met_rules(task))),
            rules=("completion_conditions_met",),
        )

    def _approval_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        if not requires_approval(task.finding, task.policy):
            return None
        if task.approval is not None and task.approval.granted:
            return None
        return self._policy_route(
            task, WorkflowAction.REQUEST_APPROVAL,
            reason=(f"{task.finding.safety_class.value} task: {task.finding.reason}; "
                    "a human must approve before any step is taken"),
            rules=("approval_required", f"safety:{task.finding.safety_class.value}"),
        )

    def _retry_budget_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        if task.retries < self.max_retries:
            return None
        return self._policy_route(
            task, WorkflowAction.ESCALATE,
            reason=(f"{task.retries} consecutive failed steps reached the retry "
                    f"budget of {self.max_retries}"),
            rules=("retry_budget_exhausted", f"max_retries:{self.max_retries}"),
        )

    def _identical_failure_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        if not task.last_signature:
            return None
        seen = task.failure_signatures[task.last_signature]
        if seen < self.max_identical_failures:
            return None
        return self._policy_route(
            task, WorkflowAction.ESCALATE,
            reason=(f"the same failure has now occurred {seen} times "
                    f"({task.last_signature}); escalating rather than looping"),
            rules=("identical_failure_repeated",
                   f"max_identical_failures:{self.max_identical_failures}"),
        )

    def _test_failure_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        failed = sum(1 for e in task.evidence
                     if evidence_state(e) is VerificationState.TESTS_FAILED)
        if failed < self.max_test_failures:
            return None
        return self._policy_route(
            task, WorkflowAction.ESCALATE,
            reason=(f"{failed} failed test runs reached the budget of "
                    f"{self.max_test_failures}"),
            rules=("test_failure_budget_exhausted",
                   f"max_test_failures:{self.max_test_failures}"),
        )

    def _step_budget_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        if len(task.history) < self.max_steps:
            return None
        return self._policy_route(
            task, WorkflowAction.ESCALATE,
            reason=(f"{len(task.history)} steps reached the task budget of "
                    f"{self.max_steps}"),
            rules=("step_budget_exhausted", f"max_steps:{self.max_steps}"),
        )

    def _exhausted_work_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        """Every work action has been taken and the task still does not pass.

        Without this the router can spin: once nothing is untried, "prefer
        untried" degrades to "prefer anything", so a model with a favourite
        answer keeps picking the same step and only the total step budget stops
        it. Tried everything and still red is a reason to escalate in its own
        right, and it names exactly that.
        """
        if task.verification is not VerificationState.TESTS_FAILED:
            return None
        if not PROGRESS_ACTIONS <= task.attempted_actions:
            return None
        if WorkflowAction.ESCALATE not in task.permitted_actions:
            return None
        return self._policy_route(
            task, WorkflowAction.ESCALATE,
            reason=("every work action has been attempted and the tests still "
                    "fail; there is nothing left in the workflow to try"),
            rules=("no_untried_work_left",),
        )

    def _ambiguity_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        """An unclassified task must not be guessed at once context runs out.

        "Retrieve more context" is the right answer to ambiguity exactly once.
        Asking twice in a row would just spend the same budget reaching the same
        uncertainty, so the second time round it escalates for a human instead.
        """
        if task.kind is not None:
            return None
        if WorkflowAction.RETRIEVE_CONTEXT not in task.attempted_actions:
            return None
        if WorkflowAction.ESCALATE not in task.permitted_actions:
            return None
        return self._policy_route(
            task, WorkflowAction.ESCALATE,
            reason=("the task is still unclassified after context was retrieved; "
                    "escalating rather than guessing what it is"),
            rules=("unclassified_after_context",),
        )

    def _test_after_change_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        if not must_test(task):
            return None
        if WorkflowAction.RUN_TESTS not in task.permitted_actions:
            return None
        return self._policy_route(
            task, WorkflowAction.RUN_TESTS,
            reason=("a change was implemented but has not been tested since; "
                    "verification must follow the change"),
            rules=("test_after_change",),
        )

    def _review_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        """Work that is finished must be reviewed before completion is considered.

        The guard on :data:`CHANGE_KINDS` is what keeps a change-producing task
        from being reviewed before it produced anything: without it, "inspect,
        review, complete" would satisfy the completion conditions with no
        deliverable at all. An investigation task skips that guard, because
        inspecting *is* its deliverable.
        """
        if WorkflowAction.REVIEW_DIFF in task.attempted_actions:
            return None
        if must_test(task):
            return None
        if task.verification is VerificationState.TESTS_FAILED:
            return None
        if task.kind in CHANGE_KINDS and \
                WorkflowAction.IMPLEMENT_CHANGE not in task.attempted_actions:
            return None
        if not any(r.action in PROGRESS_ACTIONS for r in task.history):
            return None
        if WorkflowAction.REVIEW_DIFF not in task.permitted_actions:
            return None
        return self._policy_route(
            task, WorkflowAction.REVIEW_DIFF,
            reason=("the work is tested and nothing is outstanding; review before "
                    "completion is considered"),
            rules=("review_before_completion",),
        )

    # --- the one model-backed mandatory rule --------------------------------------------

    def _failed_test_rule(self, task: WorkflowTask) -> Optional[RouteDecision]:
        if task.verification is not VerificationState.TESTS_FAILED:
            return None
        # Only immediately after the run. Once routing has moved on to diagnosis
        # or a fix, the ordinary work-selection path takes over again.
        if task.last_action is not WorkflowAction.RUN_TESTS:
            return None
        permitted = task.permitted_actions
        mapping = _retry_map(task, permitted)
        options = [o for o in DECISION_SPACE[DecisionType.RETRY_VS_ESCALATE]
                   if o in mapping]
        if not options:
            return None
        return self._choose(task, permitted, _RETRY_DECISION, options, mapping,
                            context="tests failed")

    # --- bounded inference ---------------------------------------------------------------

    def _choose(self, task: WorkflowTask, permitted: Sequence[WorkflowAction],
                decision_type: str, options: Sequence[str],
                mapping: Mapping[str, WorkflowAction],
                context: str) -> RouteDecision:
        """Ask the controller, then map and re-check its answer.

        The controller has already validated the answer against ``options`` and
        re-checked it against the tool permission policy. What remains here is
        confirming the *mapped action* is legal from this phase -- a question the
        controller cannot answer, because it does not know the workflow.
        """
        result = self.controller.decide(task.task, decision_type, list(options))
        tool = result.selected_option
        action = mapping.get(tool) if tool else None

        # A usable answer is one that produced a validated envelope. Everything
        # else -- abstention, rejection, both engines failing -- means this route
        # rests on a fallback alone, which counts against the retry budget.
        usable = result.envelope is not None and result.outcome is not Outcome.FAILED
        error = None if usable else (result.error or "no usable decision")

        if action is not None and action in permitted:
            reason = f"{context}: {tool!r} -> {action.value} (source={result.source})"
            if result.error:
                reason += f"; {result.error}"
            return RouteDecision(
                action=action, to_phase=validate_transition(task.phase, action),
                reason=reason,
                rules=(f"decision_type:{decision_type}", "permitted_only"),
                source=result.source, permitted=tuple(permitted),
                envelope=result.envelope, error=error,
            )

        fallback = _fallback_action(permitted, task)
        if fallback is None:  # pragma: no cover - route() excludes terminal phases
            raise AssertionError("no permitted action to fall back to")
        return RouteDecision(
            action=fallback, to_phase=validate_transition(task.phase, fallback),
            reason=(f"{context}: engine selection {tool!r} has no legal action "
                    f"from {task.phase.value}; deterministic priority applied"),
            rules=("fallback_priority", "permitted_only"),
            source="fallback", permitted=tuple(permitted),
            envelope=result.envelope,
            error=error or f"unusable selection {tool!r}",
        )

    def _policy_route(self, task: WorkflowTask, action: WorkflowAction, *,
                      reason: str, rules: Sequence[str]) -> RouteDecision:
        if action is None:  # pragma: no cover - non-terminal phases always have options
            raise AssertionError(f"no legal action from {task.phase.value}")
        return RouteDecision(
            action=action,
            to_phase=validate_transition(task.phase, action),
            reason=reason,
            rules=tuple(rules),
            source="policy",
            permitted=task.permitted_actions,
        )

    def _route_with_engine(self, task: WorkflowTask,
                           permitted: Sequence[WorkflowAction]) -> RouteDecision:
        tools = tuple(tool for tool in tools_for(permitted, task)
                      if self.controller.permissions.permits(tool))

        if task.kind in CONTEXT_FIRST_KINDS and not _context_gathered(task):
            # A task that will touch source gets exactly one legal tool until it
            # has looked at the repository, which the controller then settles
            # from policy without any inference at all. The guard is "has it
            # looked yet", not "is the tool usable" -- ``read_investigate`` stays
            # usable forever, it merely changes meaning afterwards.
            context_tools = tuple(t for t in tools if t == "read_investigate")
            if context_tools:
                tools = context_tools

        if not tools:
            return self._policy_route(
                task, _fallback_action(permitted, task),
                reason=(f"no workflow tool maps to a legal action from "
                        f"{task.phase.value}; deterministic priority applied"),
                rules=("fallback_priority", "permitted_only"),
            )

        mapping: dict[str, WorkflowAction] = {}
        for tool in tools:
            action = action_for_tool(tool, task)
            if action is not None:
                mapping[tool] = action

        # Only offer the engine actions it has not already taken, so a model with
        # a favourite answer still ends up testing and reviewing.
        legal = set(prefer_untried(tuple(dict.fromkeys(mapping.values())), task))
        mapping = {tool: action for tool, action in mapping.items() if action in legal}

        return self._choose(task, permitted, _WORKFLOW_DECISION, tuple(mapping),
                            mapping, context="next step")

    # --- public API ---------------------------------------------------------------------

    def route(self, task: WorkflowTask) -> Optional[RouteDecision]:
        """Propose the next step, or ``None`` if there is nothing to propose.

        ``None`` means the task is not awaiting a routing decision at all: it has
        finished, been escalated, or is frozen awaiting a human's approval. That
        is an ordinary state, so it is reported rather than raised.
        """
        if task.phase in TERMINAL_PHASES:
            return None
        if task.phase is TaskPhase.AWAITING_APPROVAL:
            return None

        permitted = task.permitted_actions
        for rule in (
            self._completion_rule,
            self._approval_rule,
            self._retry_budget_rule,
            self._identical_failure_rule,
            self._test_failure_rule,
            self._step_budget_rule,
            self._exhausted_work_rule,
            self._ambiguity_rule,
            self._failed_test_rule,
            self._test_after_change_rule,
            self._review_rule,
        ):
            decision = rule(task)
            if decision is not None:
                _log.debug("route %s -> %s (%s)", task.task_id, decision.action.value,
                           ", ".join(decision.rules))
                return decision

        return self._route_with_engine(task, permitted)

    # --- committing ---------------------------------------------------------------------

    def apply(self, task: WorkflowTask, route: RouteDecision, *,
              evidence: Optional[Evidence] = None,
              error: Optional[str] = None) -> WorkflowTask:
        """Commit ``route`` to the task.

        Validation happens before anything is mutated, so a refused step leaves
        the task exactly as it was. ``error`` marks a failed attempt and drives
        the retry budgets; when the caller passes none, ``route.error`` is used,
        so a route that no decision backed is counted as a failure too.

        ``evidence`` is caller-supplied: this service does not run tests, it
        records what the operator reports back.
        """
        failure = error if error is not None else route.error

        from_phase = task.phase
        to_phase = validate_transition(from_phase, route.action)
        if route.action is WorkflowAction.COMPLETE:
            guard_complete(task)
        if route.action is WorkflowAction.REQUEST_APPROVAL:
            task.awaiting_from = from_phase

        record = ActionRecord(
            action=route.action,
            from_phase=from_phase,
            to_phase=to_phase,
            source=route.source,
            reason=route.reason,
            rules=route.rules,
            decision_id=route.decision_id,
            confidence=route.confidence,
            error=failure,
            evidence=evidence,
        )
        task.history.append(record)
        task.phase = to_phase
        task.last_action = route.action

        if evidence is not None:
            task.evidence.append(evidence)

        if failure is not None:
            task.retries += 1
            task.last_error = str(failure)
            signature = failure_signature(route.action, str(failure))
            if signature:
                task.failure_signatures[signature] += 1
                task.last_signature = signature
        else:
            # A completed step is progress, so the consecutive-failure budget
            # resets. The identical-failure counters deliberately do not: a loop
            # that succeeds once and then fails identically is still a loop.
            task.retries = 0
            task.last_error = None
            task.last_signature = None

        _log.debug("apply %s %s->%s source=%s", task.task_id, from_phase.value,
                   to_phase.value, route.source)
        return task

    # --- approvals ----------------------------------------------------------------------

    def grant_approval(self, task: WorkflowTask, *, by: str,
                       reason: Optional[str] = None) -> WorkflowTask:
        """Record a human's approval and resume the task where it paused.

        Out-of-band by design: this service never grants its own approval. The
        resolution is recorded on :attr:`WorkflowTask.approval` -- naming the
        person, the verdict and the reason -- rather than appended to
        ``history``, because it is external authority rather than one of this
        service's own workflow steps. ``history`` keeps the ``REQUEST_APPROVAL``
        entry that opened it.
        """
        if task.phase is not TaskPhase.AWAITING_APPROVAL:
            raise _no_pending_approval(task, "grant")
        task.approval = Approval(granted=True, by=by, reason=reason)
        task.phase = task.awaiting_from or TaskPhase.CREATED
        task.awaiting_from = None
        return task

    def deny_approval(self, task: WorkflowTask, *, by: str,
                      reason: Optional[str] = None) -> WorkflowTask:
        """Record a refusal. A denied approval escalates rather than retrying."""
        if task.phase is not TaskPhase.AWAITING_APPROVAL:
            raise _no_pending_approval(task, "deny")
        task.approval = Approval(granted=False, by=by, reason=reason)
        task.phase = TaskPhase.ESCALATED
        task.awaiting_from = None
        return task

    # --- one-shot convenience ------------------------------------------------------------

    def step(self, task: WorkflowTask, **kwargs: Any) -> Optional[RouteDecision]:
        """Route and immediately commit. Returns the committed decision, if any."""
        route = self.route(task)
        if route is None:
            return None
        self.apply(task, route, **kwargs)
        return route


def _met_rules(task: WorkflowTask) -> tuple[str, ...]:
    """The completion conditions that currently hold.

    ``WorkflowTask`` computes which are *unmet*; "why may I complete this" needs
    the complement, so the two cannot disagree about the same task.
    """
    unmet = set(task.unmet_conditions)
    return tuple(rule.key for rule in COMPLETION_RULES if rule.key not in unmet)


def _retry_map(task: WorkflowTask,
               permitted: Sequence[WorkflowAction]) -> dict[str, WorkflowAction]:
    """Map ``retry``/``escalate`` onto a legal step.

    ``retry`` means "keep working", which after a red test run is diagnosis
    first: the highest-priority untried step in :data:`_RETRY_PRIORITY`. If
    everything has been tried it is allowed to repeat, because a retry that could
    only escalate would make the option meaningless.
    """
    mapping: dict[str, WorkflowAction] = {}
    candidates = [a for a in _RETRY_PRIORITY if a in permitted]
    if candidates:
        mapping["retry"] = prefer_untried(candidates, task)[0]
    if WorkflowAction.ESCALATE in permitted:
        mapping["escalate"] = WorkflowAction.ESCALATE
    return mapping


def _fallback_action(permitted: Sequence[WorkflowAction],
                     task: WorkflowTask) -> Optional[WorkflowAction]:
    """The step to take when the engine could not say.

    Restricted to :data:`~layasdlc.workflow.PROGRESS_ACTIONS` on purpose.
    ``ESCALATE``, ``REQUEST_APPROVAL`` and ``COMPLETE`` each have their own rule,
    and letting a priority list pick one of them would bypass exactly the checks
    those rules exist to perform -- a task could be escalated by a tie-break, or
    refused completion because a fallback happened to offer it.
    """
    ordered = [a for a in PRIORITY if a in permitted and a in PROGRESS_ACTIONS]
    return prefer_untried(ordered, task)[0] if ordered else None


def _no_pending_approval(task: WorkflowTask, verb: str) -> InvalidTransition:
    """Build the refusal for approving a task that is not awaiting approval.

    Returned rather than raised so both callers construct the identical message:
    approving at the wrong moment must fail the same way whoever tried.
    """
    return InvalidTransition(
        f"cannot {verb} an approval: task {task.task_id!r} is "
        f"{task.phase.value}, not awaiting_approval",
        from_phase=task.phase.value,
        action="request_approval",
        permitted=tuple(a.value for a in task.permitted_actions),
    )


__all__ = [
    "CONTEXT_FIRST_KINDS",
    "WorkflowRouter",
    "action_for_tool",
    "must_test",
    "prefer_untried",
    "tools_for",
]
