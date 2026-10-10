"""Stage 3 routing: mandatory rules, bounded inference and the five scenarios.

Everything runs offline against :class:`~layasdlc.engines.fake.FakeEngine` or the
deterministic baseline. No test in this file can reach a network, a model or the
working tree -- that is the point of the module under test.
"""

from __future__ import annotations

import subprocess

import pytest

from layasdlc import (
    ControllerConfig,
    DeterministicEngine,
    Evidence,
    FakeEngine,
    IncompleteTask,
    InvalidTransition,
    PolicyConfig,
    SafetyClass,
    TaskKind,
    TaskPhase,
    TaskState,
    VerificationState,
    WorkflowAction,
    WorkflowController,
    WorkflowRouter,
    new_task,
)
from layasdlc.cli import SCENARIOS, run_scenario
from layasdlc.engines.fake import answer
from layasdlc.errors import EngineUnavailable, MalformedDecision, OutOfScopeOption
from layasdlc.permissions import ToolPermissionPolicy
from layasdlc.router import (
    CHANGE_KINDS,
    CONTEXT_FIRST_KINDS,
    action_for_tool,
    must_test,
    prefer_untried,
    tools_for,
)
from layasdlc.workflow import PROGRESS_ACTIONS, TRANSITIONS

WORKFLOW_TOOLS = ("edit_code", "run_tests", "read_investigate", "update_docs")


# ======================================================================================
# Fixtures
# ======================================================================================


def make_router(engine=None, *, fallback=None,
                permissions=ToolPermissionPolicy.full(),
                controller_config=None, **budgets) -> WorkflowRouter:
    return WorkflowRouter(
        controller=WorkflowController(
            engine=engine if engine is not None else DeterministicEngine(),
            config=controller_config or ControllerConfig(timeout_s=2.0),
            fallback=DeterministicEngine() if fallback is None else fallback,
            permissions=permissions,
        ),
        **budgets,
    )


@pytest.fixture
def offline_router() -> WorkflowRouter:
    """A router that can never touch the network."""
    return make_router()


def fixed_engine(option: str) -> FakeEngine:
    """A model with one favourite answer, no matter what it is asked."""
    return FakeEngine(handler=lambda request: answer(
        option, confidence=0.9, allowed=tuple(request.allowed_options)))


def never_available_engine() -> FakeEngine:
    return FakeEngine(is_available=False,
                      handler=lambda request: EngineUnavailable("endpoint is down"))


def dead_router(**budgets) -> WorkflowRouter:
    """Both the model and the deterministic baseline are unreachable.

    The ordinary ``offline_router`` always has a working baseline, so it can
    never exhaust a retry budget. This one models a genuinely dead endpoint,
    which is the only way the escalation paths can be reached.
    """
    dead = never_available_engine()
    return make_router(engine=dead, fallback=dead, **budgets)


@pytest.fixture
def bugfix():
    return new_task(TaskState(task_id="T-1", subject="Checkout throws 500",
                              body="Applying a promo code raises a 500; the trace "
                                   "shows a None discount after the refactor.",
                              path="src/billing/pricing.py"),
                    kind=TaskKind.BUG_FIX)


@pytest.fixture
def documentation():
    return new_task(TaskState(task_id="T-DOCS", subject="Document the retry budget",
                              body="Add a short section explaining the retry budget.",
                              path="docs/routing.md"),
                    kind=TaskKind.DOCUMENTATION)


# ======================================================================================
# The pure helpers
# ======================================================================================


def test_tool_to_action_mapping_is_total_over_the_decision_space():
    probe = new_task(TaskState(task_id="T-1", subject="x"))
    for tool in WORKFLOW_TOOLS:
        assert action_for_tool(tool, probe) is not None


def test_read_investigate_changes_meaning_once_the_repository_is_seen():
    probe = new_task(TaskState(task_id="T-1", subject="x"))
    assert action_for_tool("read_investigate", probe) is WorkflowAction.INSPECT_REPOSITORY

    from layasdlc.workflow import ActionRecord
    probe.history.append(ActionRecord(
        action=WorkflowAction.INSPECT_REPOSITORY, from_phase=TaskPhase.CREATED,
        to_phase=TaskPhase.INSPECTING, source="policy", reason="test"))
    assert action_for_tool("read_investigate", probe) is WorkflowAction.RETRIEVE_CONTEXT


def test_an_unknown_tool_maps_to_nothing():
    probe = new_task(TaskState(task_id="T-1", subject="x"))
    assert action_for_tool("drop_production", probe) is None
    assert action_for_tool(None, probe) is None


def test_tools_for_offers_only_actions_legal_right_now():
    probe = new_task(TaskState(task_id="T-1", subject="x"))
    tools = tools_for(TRANSITIONS[TaskPhase.AWAITING_APPROVAL], probe)
    assert tools == ()  # only ESCALATE is legal, and ESCALATE is not a tool


def test_prefer_untried_drops_what_the_task_has_already_done():
    probe = new_task(TaskState(task_id="T-1", subject="x"))
    _commit(probe, WorkflowAction.IMPLEMENT_CHANGE)
    _commit(probe, WorkflowAction.RUN_TESTS)

    candidates = (WorkflowAction.IMPLEMENT_CHANGE, WorkflowAction.RUN_TESTS,
                  WorkflowAction.REVIEW_DIFF)
    assert prefer_untried(candidates, probe) == (WorkflowAction.REVIEW_DIFF,)


def test_prefer_untried_returns_everything_rather_than_nothing():
    """A step that genuinely must repeat must still be selectable."""
    probe = new_task(TaskState(task_id="T-1", subject="x"))
    _commit(probe, WorkflowAction.INSPECT_REPOSITORY)
    assert prefer_untried((WorkflowAction.INSPECT_REPOSITORY,), probe) == \
        (WorkflowAction.INSPECT_REPOSITORY,)


def test_must_test_is_true_only_for_an_untested_change():
    probe = new_task(TaskState(task_id="T-1", subject="x"), kind=TaskKind.BUG_FIX)
    assert must_test(probe) is False  # no change yet

    _commit(probe, WorkflowAction.IMPLEMENT_CHANGE)
    assert must_test(probe) is True

    _commit(probe, WorkflowAction.RUN_TESTS)
    assert must_test(probe) is False

    _commit(probe, WorkflowAction.IMPLEMENT_CHANGE)  # another change invalidates it
    assert must_test(probe) is True


def test_context_first_covers_unclassified_tasks_but_not_documentation():
    assert TaskKind.BUG_FIX in CONTEXT_FIRST_KINDS
    assert None in CONTEXT_FIRST_KINDS
    assert TaskKind.DOCUMENTATION not in CONTEXT_FIRST_KINDS
    assert TaskKind.INVESTIGATION not in CONTEXT_FIRST_KINDS


def test_only_investigation_is_exempt_from_producing_a_deliverable():
    assert TaskKind.INVESTIGATION not in CHANGE_KINDS
    assert TaskKind.DOCUMENTATION in CHANGE_KINDS
    assert None in CHANGE_KINDS


# ======================================================================================
# Mandatory rules
# ======================================================================================


def test_approval_is_requested_before_anything_else_happens(offline_router):
    task = new_task(TaskState(task_id="T-DEP", subject="Deploy checkout to production"),
                    kind=TaskKind.FEATURE)
    route = offline_router.route(task)

    assert route.action is WorkflowAction.REQUEST_APPROVAL
    assert route.source == "policy"
    assert "approval_required" in route.rules
    assert "deployment" in route.reason


def test_a_pending_approval_freezes_the_task(offline_router):
    task = new_task(TaskState(task_id="T-DEP", subject="Deploy checkout to production"),
                    kind=TaskKind.FEATURE)
    offline_router.step(task)

    assert task.phase is TaskPhase.AWAITING_APPROVAL
    assert offline_router.route(task) is None
    assert task.permitted_actions == (WorkflowAction.ESCALATE,)


def test_granting_resumes_where_the_task_paused(offline_router):
    task = new_task(TaskState(task_id="T-DEP", subject="Deploy checkout to production"),
                    kind=TaskKind.FEATURE)
    offline_router.step(task)
    offline_router.grant_approval(task, by="release-manager", reason="signed off")

    assert task.phase is TaskPhase.CREATED
    assert task.approval.granted is True
    assert task.approval.by == "release-manager"
    # And approval no longer gates: the next step is real work.
    assert offline_router.route(task).action is not WorkflowAction.REQUEST_APPROVAL


def test_denial_escalates_rather_than_retrying(offline_router):
    task = new_task(TaskState(task_id="T-DEP", subject="Deploy checkout to production"),
                    kind=TaskKind.FEATURE)
    offline_router.step(task)
    offline_router.deny_approval(task, by="release-manager", reason="not this week")

    assert task.phase is TaskPhase.ESCALATED
    assert task.approval.granted is False
    assert offline_router.route(task) is None


@pytest.mark.parametrize("verb", ["grant", "deny"])
def test_approving_at_the_wrong_moment_is_refused(offline_router, verb):
    task = new_task(TaskState(task_id="T-1", subject="Fix the typo"),
                    kind=TaskKind.DOCUMENTATION)
    with pytest.raises(InvalidTransition):
        getattr(offline_router, f"{verb}_approval")(task, by="someone")


def test_approval_is_not_invented_for_a_safe_task(offline_router):
    task = new_task(TaskState(task_id="T-1", subject="Fix the typo in the README"),
                    kind=TaskKind.DOCUMENTATION)
    assert offline_router.route(task).action is not WorkflowAction.REQUEST_APPROVAL


def test_a_change_must_be_tested_before_anything_else(offline_router, documentation):
    offline_router.apply(documentation, offline_router.route(documentation))  # implement

    route = offline_router.route(documentation)
    assert route.action is WorkflowAction.RUN_TESTS
    assert route.rules == ("test_after_change",)
    assert route.source == "policy"


def test_review_must_follow_testing(offline_router, documentation):
    route = offline_router.route(documentation)
    offline_router.apply(documentation, route)
    offline_router.apply(documentation, offline_router.route(documentation),
                         evidence=Evidence.record("pytest", True))

    route = offline_router.route(documentation)
    assert route.action is WorkflowAction.REVIEW_DIFF
    assert route.rules == ("review_before_completion",)


def test_completion_is_offered_only_once_conditions_hold(offline_router, documentation):
    _drive_to_review(offline_router, documentation)

    assert offline_router.route(documentation).action is WorkflowAction.COMPLETE
    assert "completion_conditions_met" in offline_router.route(documentation).rules


def test_a_task_that_is_not_reviewed_cannot_complete(offline_router):
    task = new_task(TaskState(task_id="T-1", subject="Add a flag"),
                    kind=TaskKind.FEATURE)
    _commit(task, WorkflowAction.IMPLEMENT_CHANGE)
    task.evidence.append(Evidence.record("pytest", True))
    task.phase = TaskPhase.TESTING

    # COMPLETE is legal in the transition table; only the conditions refuse it.
    with pytest.raises(IncompleteTask) as excinfo:
        offline_router.apply(task, _complete_route(offline_router, task))
    assert "reviewed" in excinfo.value.unmet


def test_completion_never_depends_on_the_model_alone(offline_router, bugfix):
    """Even a confident 'complete' is refused while conditions are unmet."""
    _commit(bugfix, WorkflowAction.IMPLEMENT_CHANGE)
    bugfix.phase = TaskPhase.REVIEWING

    with pytest.raises(IncompleteTask):
        offline_router.apply(bugfix, _complete_route(offline_router, bugfix))
    assert bugfix.phase is TaskPhase.REVIEWING  # and nothing moved


# ======================================================================================
# Context-first, and the engine being asked nothing when it need not be
# ======================================================================================


def test_a_source_changing_task_gathers_context_before_it_changes_anything():
    router = make_router(engine=fixed_engine("edit_code"))
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX)

    route = router.route(task)
    assert route.action is WorkflowAction.INSPECT_REPOSITORY
    # Nothing was asked of the model: the option set had already collapsed.
    assert router.controller.engine.records == []
    assert route.source == "policy"
    assert route.confidence == 1.0


def test_the_model_is_asked_once_there_is_a_real_choice():
    engine = fixed_engine("edit_code")
    router = make_router(engine=engine)
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX)
    # Advance past the context-gathering step using a separate offline router, so
    # the assertion below counts only the calls the choice itself triggered.
    advancer = make_router()
    advancer.apply(task, advancer.route(task))

    route = router.route(task)
    assert route.action is WorkflowAction.IMPLEMENT_CHANGE
    assert len(engine.records) == 1
    assert engine.records[0].allowed_options  # more than one option was offered


def test_read_only_permissions_collapse_the_choice_without_a_model_call():
    router = make_router(permissions=ToolPermissionPolicy.read_only())
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX)

    route = router.route(task)
    assert route.action is WorkflowAction.INSPECT_REPOSITORY
    assert route.source == "policy"


def test_read_only_permissions_never_offer_a_tool_the_policy_forbids():
    """Regression: the router used to hand the controller a set that narrowed to
    nothing, so a read-only run raised ``PermissionDenied`` instead of routing.
    """
    router = make_router(permissions=ToolPermissionPolicy.read_only())
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    for _ in range(10):
        if task.is_terminal:
            break
        route = router.route(task)
        # Inspection is the only tool a read-only policy permits, so every
        # engine-backed route must land on an inspection step.
        if route.source != "policy" or route.rules[0].startswith("decision_type:"):
            assert route.action in (WorkflowAction.INSPECT_REPOSITORY,
                                    WorkflowAction.RETRIEVE_CONTEXT)
        router.apply(task, route)


# ======================================================================================
# Unavailability, malformation and the bounded retries
# ======================================================================================


def test_an_unavailable_engine_falls_back_and_says_so():
    router = make_router(engine=never_available_engine())
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    route = router.route(task)
    assert route.action is WorkflowAction.IMPLEMENT_CHANGE
    assert route.source == "fallback"
    # The deterministic baseline still answered, so the step is not a failure --
    # but the reason records why the model was not the one who chose it.
    assert "endpoint is down" in route.reason
    assert route.error is None

    router.apply(task, route)
    assert task.retries == 0


def test_when_both_engines_fail_the_route_still_happens_and_counts_as_a_failure():
    """A dead endpoint must not stall a task, and must not look like progress."""
    router = dead_router(max_retries=2)
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    route = router.route(task)
    assert route.action is WorkflowAction.INSPECT_REPOSITORY  # still bounded work
    assert route.source == "fallback"
    assert route.error

    router.apply(task, route)
    assert task.retries == 1
    assert task.last_error


def test_the_fallback_never_picks_escalate_or_complete_on_its_own():
    """A tie-break must not do the job of the rules that gate those steps.

    Regression: with everything useful already tried, the priority list used to
    walk straight into ``ESCALATE``, ending a task without any of the conditions
    that are supposed to justify escalation.
    """
    router = dead_router(max_steps=99, max_retries=99, max_identical_failures=99)
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    for _ in range(12):
        if task.is_terminal:
            break
        route = router.route(task)
        if route.rules == ("fallback_priority", "permitted_only") or \
                route.rules == ("fallback_priority",):
            assert route.action in PROGRESS_ACTIONS
        router.apply(task, route, evidence=Evidence.record("pytest", True))


def test_a_malformed_decision_is_rejected_and_routed_deterministically():
    engine = FakeEngine(handler=lambda request: MalformedDecision(
        "body was not the documented payload"))
    router = make_router(engine=engine)
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    route = router.route(task)
    assert route.action is WorkflowAction.IMPLEMENT_CHANGE
    assert route.source == "fallback"
    assert "MalformedDecision" in route.reason


def test_an_out_of_scope_selection_never_widens_the_route():
    """A model asking for a tool it was not offered cannot get it."""
    engine = FakeEngine(handler=lambda request: answer(
        "drop_production", confidence=0.9, allowed=tuple(request.allowed_options)))
    router = make_router(engine=engine)
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    route = router.route(task)
    assert route.action in task.permitted_actions
    assert "drop_production" not in {a.value for a in task.permitted_actions}
    assert "OutOfScopeOption" in route.reason


def test_repeated_identical_failures_escalate_instead_of_looping():
    router = dead_router(max_retries=99, max_identical_failures=3)
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    _run_until_settled(router, task)

    assert task.phase is TaskPhase.ESCALATED
    assert "identical_failure_repeated" in task.history[-1].rules
    assert max(task.failure_signatures.values()) >= 3


def test_the_retry_budget_exhausts_and_escalates():
    router = dead_router(max_retries=2, max_identical_failures=99)
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    _run_until_settled(router, task)

    assert task.phase is TaskPhase.ESCALATED
    assert "retry_budget_exhausted" in task.history[-1].rules


def test_the_step_budget_bounds_a_task_that_never_settles():
    router = dead_router(max_steps=4, max_retries=99, max_identical_failures=99)
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    _run_until_settled(router, task)

    assert task.phase is TaskPhase.ESCALATED
    assert "step_budget_exhausted" in task.history[-1].rules


def test_a_success_resets_the_consecutive_failure_budget_but_not_the_loop_counters():
    router = make_router(engine=fixed_engine("edit_code"), max_retries=99,
                         max_identical_failures=99)
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)

    router.apply(task, router.route(task), error="boom one")
    router.apply(task, router.route(task), error="boom two")
    assert task.retries == 2
    assert sum(task.failure_signatures.values()) == 2

    router.apply(task, router.route(task))  # a clean step
    assert task.retries == 0
    assert task.last_signature is None
    # The identical-failure counters deliberately survive the success: a loop
    # that succeeds once and then fails identically is still a loop.
    assert sum(task.failure_signatures.values()) == 2


def test_a_budget_must_be_positive():
    with pytest.raises(ValueError):
        make_router(max_retries=0)
    with pytest.raises(ValueError):
        make_router(max_steps=0)


# ======================================================================================
# Failed tests
# ======================================================================================


def test_a_failed_test_is_put_to_the_retry_versus_escalate_decision():
    engine = FakeEngine(handler=lambda request: answer(
        "retry", confidence=0.8, allowed=tuple(request.allowed_options)))
    router = make_router(engine=engine)
    task = new_task(TaskState(task_id="T-1", subject="Add a flag"),
                    kind=TaskKind.FEATURE)
    _commit(task, WorkflowAction.IMPLEMENT_CHANGE)

    router.apply(task, router.route(task), evidence=Evidence.record("pytest", False))
    route = router.route(task)

    assert route.action is WorkflowAction.INSPECT_REPOSITORY  # diagnose first
    retry_call = [r for r in engine.records
                  if r.decision_type == "retry_vs_escalate"]
    assert retry_call, "the retry decision should have been posed"


def test_a_persistent_failure_escalates_from_the_deterministic_baseline():
    task = new_task(TaskState(task_id="T-1", subject="Add a flag",
                              body="it fails consistently, again and again"),
                    kind=TaskKind.FEATURE)
    router = make_router()
    _commit(task, WorkflowAction.IMPLEMENT_CHANGE)
    router.apply(task, router.route(task), evidence=Evidence.record("pytest", False))

    assert router.route(task).action is WorkflowAction.ESCALATE


def test_the_failed_test_budget_escalates_before_anything_else_runs():
    """One red run is enough to stop, when one is all the budget allows.

    Note on reachability: with a larger budget this rule is usually shadowed by
    ``no_untried_work_left``, because "prefer untried" means a second test run
    needs a *second* change, and by then every work action has been tried. That
    is the intended ordering -- exhaustion is the more informative reason -- so
    this rule is pinned here at the one setting where it is the thing that fires.
    """

    def always_retry(request):
        option = "retry" if request.decision_type == "retry_vs_escalate" else "edit_code"
        return answer(option, confidence=0.8, allowed=tuple(request.allowed_options))

    router = make_router(engine=FakeEngine(handler=always_retry),
                         max_test_failures=1, max_retries=99,
                         max_identical_failures=99, max_steps=99)
    task = new_task(TaskState(task_id="T-1", subject="Add a flag"),
                    kind=TaskKind.FEATURE)
    _commit(task, WorkflowAction.IMPLEMENT_CHANGE)
    failing = Evidence.record("pytest", False)

    for _ in range(12):
        if task.is_terminal:
            break
        route = router.route(task)
        router.apply(task, route, evidence=failing
                     if route.action is WorkflowAction.RUN_TESTS else None)

    assert task.phase is TaskPhase.ESCALATED
    assert "test_failure_budget_exhausted" in task.history[-1].rules


def test_work_that_is_exhausted_escalates_instead_of_repeating_itself():
    """A model with a favourite answer must not be able to spin forever.

    Regression: once nothing was untried, "prefer untried" degraded to "prefer
    anything", so an engine that kept answering ``read_investigate`` looped until
    the total step budget stopped it. Tried everything and still red is its own
    reason to escalate.
    """

    def always_read(request):
        option = "retry" if request.decision_type == "retry_vs_escalate" else "read_investigate"
        return answer(option, confidence=0.8, allowed=tuple(request.allowed_options))

    router = make_router(engine=FakeEngine(handler=always_read), max_steps=99,
                         max_retries=99, max_identical_failures=99)
    task = new_task(TaskState(task_id="T-1", subject="Add a flag"),
                    kind=TaskKind.FEATURE)
    _commit(task, WorkflowAction.IMPLEMENT_CHANGE)

    for _ in range(12):
        if task.is_terminal:
            break
        route = router.route(task)
        router.apply(task, route, evidence=Evidence.record("pytest", False)
                     if route.action is WorkflowAction.RUN_TESTS else None)

    assert task.phase is TaskPhase.ESCALATED
    assert len(task.history) <= 8, "it should settle quickly, not run to a budget"
    assert "no_untried_work_left" in task.history[-1].rules


def test_verification_follows_the_evidence_recorded():
    task = new_task(TaskState(task_id="T-1", subject="Add a flag"),
                    kind=TaskKind.FEATURE)
    assert task.verification is VerificationState.UNVERIFIED
    task.evidence.append(Evidence.record("pytest", False))
    assert task.verification is VerificationState.TESTS_FAILED
    task.evidence.append(Evidence.record("pytest", True))
    assert task.verification is VerificationState.TESTS_PASSED


# ======================================================================================
# Ambiguity
# ======================================================================================


def test_an_unclassified_task_gathers_context_before_it_escalates():
    router = make_router(engine=never_available_engine())
    task = new_task(TaskState(task_id="T-V", subject="Improve the thing a bit"),
                    kind=None)

    assert router.route(task).action is WorkflowAction.INSPECT_REPOSITORY
    router.apply(task, router.route(task))
    # The engine could not classify it, so the deterministic fallback runs.
    assert router.route(task).action is WorkflowAction.RETRIEVE_CONTEXT
    router.apply(task, router.route(task))

    route = router.route(task)
    assert route.action is WorkflowAction.ESCALATE
    assert route.rules == ("unclassified_after_context",)


def test_a_classified_task_is_not_escalated_as_ambiguous():
    task = new_task(TaskState(task_id="T-1", subject="Improve the thing a bit"),
                    kind=TaskKind.FEATURE)
    router = make_router()
    for _ in range(6):
        if not task.is_terminal:
            route = router.route(task)
            assert route.rules != ("unclassified_after_context",)
            router.apply(task, route, evidence=Evidence.record("pytest", True))


# ======================================================================================
# Structural guarantees
# ======================================================================================


def test_a_settled_task_has_no_route(offline_router, documentation):
    _drive_to_review(offline_router, documentation)
    offline_router.apply(documentation, offline_router.route(documentation))
    assert documentation.phase is TaskPhase.COMPLETE
    assert offline_router.route(documentation) is None


def test_apply_validates_before_it_mutates():
    task = new_task(TaskState(task_id="T-1", subject="Fix the typo"),
                    kind=TaskKind.DOCUMENTATION)
    router = make_router()
    before = list(task.history)

    # COMPLETE is legal from `created` in the table, so the refusal must come from
    # the completion conditions -- and must leave the task exactly as it was.
    with pytest.raises(IncompleteTask):
        router.apply(task, _complete_route(router, task))

    assert task.history == before
    assert task.phase is TaskPhase.CREATED


def test_apply_records_the_justification_for_every_step():
    router = make_router(engine=fixed_engine("edit_code"))
    task = new_task(TaskState(task_id="T-1", subject="Fix the crash"),
                    kind=TaskKind.BUG_FIX)

    router.apply(task, router.route(task))
    record = task.history[0]

    assert record.reason, "a step with no stated reason is unauditable"
    assert record.rules, "a step with no stated rule is unauditable"
    assert record.source in {"policy", "engine", "fallback"}
    assert record.from_phase is TaskPhase.CREATED
    assert record.to_phase is TaskPhase.INSPECTING


def test_every_route_names_the_rules_that_constrained_it():
    router = make_router()
    task = new_task(TaskState(task_id="T-1", subject="Document the flag"),
                    kind=TaskKind.DOCUMENTATION)
    for _ in range(8):
        if task.is_terminal:
            break
        route = router.route(task)
        assert route.rules, f"no rules recorded for {route.action}"
        router.apply(task, route, evidence=Evidence.record("pytest", True))


# ======================================================================================
# The five acceptance scenarios
# ======================================================================================


def test_a_simple_documentation_task_completes_in_four_steps(offline_router,
                                                             documentation):
    _run(offline_router, documentation,
         evidence={"run_tests": Evidence.record("pytest --collect-only", True)})

    assert documentation.phase is TaskPhase.COMPLETE
    assert [r.action for r in documentation.history] == [
        WorkflowAction.IMPLEMENT_CHANGE, WorkflowAction.RUN_TESTS,
        WorkflowAction.REVIEW_DIFF, WorkflowAction.COMPLETE]
    assert documentation.unmet_conditions == ()


def test_a_bug_fix_inspects_before_it_changes_anything(offline_router, bugfix):
    _run(offline_router, bugfix,
         evidence={"run_tests": Evidence.record("pytest tests/billing", True)})

    actions = [r.action for r in bugfix.history]
    assert actions[0] is WorkflowAction.INSPECT_REPOSITORY
    assert actions.index(WorkflowAction.IMPLEMENT_CHANGE) > \
        actions.index(WorkflowAction.INSPECT_REPOSITORY)
    assert bugfix.phase is TaskPhase.COMPLETE


def test_a_failed_test_leads_to_escalation(offline_router):
    task = new_task(TaskState(task_id="T-RED",
                              subject="Test suite fails consistently after the merge",
                              body="it fails consistently, again and again"),
                    kind=TaskKind.BUG_FIX)
    _run(offline_router, task,
         evidence={"run_tests": Evidence.record("pytest", False)})

    assert task.phase is TaskPhase.ESCALATED
    assert WorkflowAction.ESCALATE in [r.action for r in task.history]
    assert task.phase is not TaskPhase.COMPLETE


def test_an_ambiguous_task_escalates_rather_than_guessing(offline_router):
    task = new_task(TaskState(task_id="T-V",
                              subject="Improve the thing a bit",
                              body="The scope was never written down."),
                    kind=None)
    _run(offline_router, task)

    assert task.phase is TaskPhase.ESCALATED
    assert "unclassified_after_context" in [
        rule for record in task.history for rule in record.rules]


def test_a_high_risk_action_waits_for_a_human_and_then_finishes(offline_router):
    task = new_task(TaskState(task_id="T-DEP",
                              subject="Deploy the checkout service to production"),
                    kind=TaskKind.FEATURE)

    route = offline_router.route(task)
    assert route.action is WorkflowAction.REQUEST_APPROVAL
    offline_router.apply(task, route)
    assert task.phase is TaskPhase.AWAITING_APPROVAL
    assert offline_router.route(task) is None  # nothing may proceed unapproved

    offline_router.grant_approval(task, by="release-manager")
    _run(offline_router, task,
         evidence={"run_tests": Evidence.record("pytest", True)})

    assert task.phase is TaskPhase.COMPLETE
    assert task.approval.granted is True
    assert task.approval.by == "release-manager"


def test_a_denied_high_risk_action_never_completes(offline_router):
    task = new_task(TaskState(task_id="T-DEP",
                              subject="Deploy the checkout service to production"),
                    kind=TaskKind.FEATURE)
    offline_router.apply(task, offline_router.route(task))
    offline_router.deny_approval(task, by="release-manager", reason="hold")

    assert task.phase is TaskPhase.ESCALATED
    assert task.can_complete is False


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.key for s in SCENARIOS])
def test_every_cli_scenario_settles_without_touching_anything(scenario, monkeypatch):
    """No shell, no filesystem writes -- the workflow only ever *permits*."""

    def explode(*args, **kwargs):
        raise AssertionError("the mock workflow must not shell out")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "call", explode)

    report = run_scenario(scenario)

    assert report.task.phase in (TaskPhase.COMPLETE, TaskPhase.ESCALATED)
    assert len(report.steps) <= 8, "a scenario should settle quickly"
    assert all(step.get("reason") for step in report.steps)
    for record in report.task.history:
        assert record.action in tuple(WorkflowAction)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.key for s in SCENARIOS])
def test_every_scenario_step_is_one_of_the_eight_actions(scenario):
    report = run_scenario(scenario)
    legal = {a for a in WorkflowAction}
    for record in report.task.history:
        assert record.action in legal
        assert record.to_phase in TRANSITIONS[record.from_phase].values()


# ======================================================================================
# Helpers
# ======================================================================================


def _commit(task, action: WorkflowAction) -> None:
    from layasdlc.workflow import ActionRecord
    to_phase = TRANSITIONS[task.phase][action]
    task.history.append(ActionRecord(
        action=action, from_phase=task.phase, to_phase=to_phase,
        source="policy", reason="helper"))
    task.phase = to_phase
    task.last_action = action


def _run(router: WorkflowRouter, task, evidence=None, max_steps: int = 12) -> None:
    evidence = dict(evidence or {})
    for _ in range(max_steps):
        if task.is_terminal:
            return
        route = router.route(task)
        if route is None:
            return
        payload = evidence.get(route.action.value) if route.action \
            is WorkflowAction.RUN_TESTS else None
        router.apply(task, route, evidence=payload)
    raise AssertionError(f"task {task.task_id} never settled; phase={task.phase}")


def _run_until_settled(router: WorkflowRouter, task, max_steps: int = 30) -> None:
    """Apply routes until the router refuses to propose another one."""
    for _ in range(max_steps):
        if task.is_terminal:
            return
        route = router.route(task)
        if route is None:
            return
        router.apply(task, route)
    raise AssertionError(f"task {task.task_id} never settled; phase={task.phase}")


def _drive_to_review(router: WorkflowRouter, task) -> None:
    for _ in range(8):
        route = router.route(task)
        if route.action is WorkflowAction.REVIEW_DIFF:
            router.apply(task, route)
            return
        router.apply(task, route, evidence=Evidence.record("pytest", True)
                     if route.action is WorkflowAction.RUN_TESTS else None)
    raise AssertionError("never reached review")


def _complete_route(router: WorkflowRouter, task):
    return router._policy_route(task, WorkflowAction.COMPLETE,
                                reason="forced for the test", rules=("test",))
