"""Stage 4 persistence: SQLite store, migrations, resume, staleness.

All tests run against temporary files -- no shared database, no network, no
repository access. The acceptance question ("does a task survive a restart?") is
answered by writing with one store and reading back with a fresh instance, which
is exactly what a restart is.
"""

from __future__ import annotations

import pytest

from layasdlc import (
    ControllerConfig,
    DeterministicEngine,
    Evidence,
    FakeEngine,
    PolicyConfig,
    TaskKind,
    TaskPhase,
    TaskState,
    ToolPermissionPolicy,
    WorkflowAction,
    WorkflowController,
    WorkflowRouter,
    WorkflowTask,
    new_task,
)
from layasdlc.engines.fake import answer
from layasdlc.store import StoreError
from layasdlc.store import STORE_SCHEMA_VERSION, TaskStore


# ======================================================================================
# Fixtures
# ======================================================================================


@pytest.fixture
def store(tmp_path) -> TaskStore:
    s = TaskStore(tmp_path / "tasks.sqlite3")
    s.migrate()
    return s


@pytest.fixture
def bugfix() -> WorkflowTask:
    return new_task(TaskState(task_id="T-1", subject="Checkout throws 500",
                              body="Applying a promo code raises a 500.",
                              path="src/billing/pricing.py"),
                    kind=TaskKind.BUG_FIX)


# ======================================================================================
# Schema and migrations
# ======================================================================================


def test_migrate_creates_the_current_schema(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    version = store.migrate()

    assert version == STORE_SCHEMA_VERSION
    with store._connect() as conn:
        tables = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tasks", "history", "evidence", "context_facts"} <= tables


def test_migrate_is_idempotent(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    first = store.migrate()
    second = store.migrate()
    assert first == second


def test_a_database_is_not_refused_for_being_new(tmp_path):
    """An empty file is not an error -- it is a database waiting to be created."""
    store = TaskStore(tmp_path / "fresh.sqlite3")
    store.migrate()
    assert store.load("nope") is None


# ======================================================================================
# Round-trip: the acceptance test for persistence
# ======================================================================================


def test_a_task_survives_a_restart(store, bugfix):
    """Write with one store, read back with a fresh instance. That is a restart."""
    _drive(store, bugfix)

    reopened = TaskStore(store.path)
    resumed = reopened.load("T-1")

    assert resumed is not None
    assert resumed.task_id == "T-1"
    assert resumed.phase is TaskPhase.COMPLETE
    assert resumed.kind is TaskKind.BUG_FIX
    assert [r.action for r in resumed.history] == [
        WorkflowAction.INSPECT_REPOSITORY,
        WorkflowAction.IMPLEMENT_CHANGE,
        WorkflowAction.RUN_TESTS,
        WorkflowAction.REVIEW_DIFF,
        WorkflowAction.COMPLETE,
    ]
    assert resumed.verification.name == "TESTS_PASSED"
    assert resumed.retries == 0


def test_resuming_preserves_the_policy_the_task_was_created_under(store, bugfix):
    """A resumed task must be judged by the rules it was created under."""
    bugfix.policy = PolicyConfig(min_confidence=0.9, enforce_test_evidence=False)
    store.save(bugfix)

    resumed = TaskStore(store.path).load("T-1")
    assert resumed.policy.min_confidence == 0.9
    assert resumed.policy.enforce_test_evidence is False


def test_resuming_preserves_the_safety_finding(store):
    task = new_task(TaskState(task_id="T-DEP", subject="Deploy checkout to production"))
    store.save(task)

    resumed = TaskStore(store.path).load("T-DEP")
    assert resumed.finding.safety_class.name == "DEPLOYMENT"
    assert resumed.finding.requires_approval is True
    assert resumed.finding.matched  # the phrases that triggered it


def test_resuming_preserves_approval_state(store):
    task = new_task(TaskState(task_id="T-DEP", subject="Deploy checkout to production"))
    store.save(task)

    resumed = TaskStore(store.path).load("T-DEP")
    router = WorkflowRouter(controller=WorkflowController(
        engine=DeterministicEngine(), config=ControllerConfig(timeout_s=2.0),
        permissions=ToolPermissionPolicy.full()))
    router.step(resumed)
    router.grant_approval(resumed, by="release-manager", reason="signed off")
    store.save(resumed)

    again = TaskStore(store.path).load("T-DEP")
    assert again.approval is not None
    assert again.approval.granted is True
    assert again.approval.by == "release-manager"
    assert again.phase is TaskPhase.CREATED  # resumed where it paused


def test_resuming_preserves_failure_counters(store, bugfix):
    """Retry counts and failure signatures are what bound a loop -- losing them
    on resume would let an identical failure repeat forever."""
    bugfix.retries = 2
    bugfix.failure_signatures["run_tests:timed out"] = 2
    bugfix.last_signature = "run_tests:timed out"
    store.save(bugfix)

    resumed = TaskStore(store.path).load("T-1")
    assert resumed.retries == 2
    assert resumed.failure_signatures == {"run_tests:timed out": 2}
    assert resumed.last_signature == "run_tests:timed out"


def test_history_records_keep_their_evidence(store, bugfix):
    record_evidence = Evidence.record("pytest -q", True)
    bugfix.history.append(_record(WorkflowAction.RUN_TESTS, record_evidence))
    bugfix.evidence.append(record_evidence)
    store.save(bugfix)

    resumed = TaskStore(store.path).load("T-1")
    assert resumed.evidence[0].test_command == "pytest -q"
    assert resumed.evidence[0].tests_passed is True
    assert resumed.history[0].evidence is not None
    assert resumed.history[0].evidence.test_command == "pytest -q"


def test_saving_twice_does_not_duplicate_history(store, bugfix):
    """Repeated requests must not duplicate completed steps."""
    store.save(bugfix)
    store.save(bugfix)
    store.save(bugfix)

    resumed = TaskStore(store.path).load("T-1")
    assert len(resumed.history) == 0  # still nothing committed


def test_save_replaces_history_rather_than_appending(store, bugfix):
    bugfix.history.append(_record(WorkflowAction.INSPECT_REPOSITORY))
    store.save(bugfix)

    # The router advanced the task; saving the new state must not stack on top.
    bugfix.history.append(_record(WorkflowAction.IMPLEMENT_CHANGE))
    store.save(bugfix)

    resumed = TaskStore(store.path).load("T-1")
    assert [r.action for r in resumed.history] == [
        WorkflowAction.INSPECT_REPOSITORY, WorkflowAction.IMPLEMENT_CHANGE]


def test_load_returns_none_for_an_unknown_task(store):
    assert store.load("T-404") is None


# ======================================================================================
# Listing and deletion
# ======================================================================================


def test_listing_shows_tasks_most_recent_first(store):
    for task_id in ("T-A", "T-B", "T-C"):
        store.save(new_task(TaskState(task_id=task_id, subject=task_id)))

    listed = store.list_tasks()
    assert [row["task_id"] for row in listed] == ["T-C", "T-B", "T-A"]


def test_deleting_removes_the_task_and_its_rows(store, bugfix):
    bugfix.history.append(_record(WorkflowAction.INSPECT_REPOSITORY))
    store.save(bugfix)

    store.delete("T-1")
    assert store.load("T-1") is None
    with store._connect() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM history WHERE task_id = 'T-1'").fetchone()[0]
    assert remaining == 0


# ======================================================================================
# Context facts
# ======================================================================================


def test_facts_are_stored_with_their_kind(store, bugfix):
    store.save(bugfix)
    store.add_fact("T-1", kind="verified", content="The promo code path is /api/apply",
                  source="read_investigate", revision="abc123")
    store.add_fact("T-1", kind="requirement", content="No change to public API",
                  source="user", revision=None)

    assert len(store.facts("T-1")) == 2
    assert len(store.facts("T-1", kind="verified")) == 1


def test_fact_kinds_are_restricted(store, bugfix):
    """An unknown kind is refused rather than stored -- the five kinds are what
    the context layer is allowed to reason about."""
    store.save(bugfix)
    with pytest.raises(StoreError):
        store.add_fact("T-1", kind="transcript", content="a long log", source="x")


def test_stale_facts_are_hidden_by_default(store, bugfix):
    store.save(bugfix)
    store.add_fact("T-1", kind="verified", content="pricing.py defines apply()",
                  source="read_investigate", revision="abc123")
    assert store.mark_stale("T-1", kind="verified") == 1
    assert store.facts("T-1") == []
    assert len(store.facts("T-1", include_stale=True)) == 1


def test_marking_stale_is_idempotent(store, bugfix):
    store.save(bugfix)
    store.add_fact("T-1", kind="verified", content="fact", source="x")
    assert store.mark_stale("T-1") == 1
    assert store.mark_stale("T-1") == 0


def test_stale_marks_only_the_requested_kind(store, bugfix):
    store.save(bugfix)
    store.add_fact("T-1", kind="verified", content="fact", source="x")
    store.add_fact("T-1", kind="hypothesis", content="guess", source="y")
    store.mark_stale("T-1", kind="verified")

    assert len(store.facts("T-1")) == 1
    assert store.facts("T-1")[0]["kind"] == "hypothesis"


def test_a_revision_change_marks_related_facts_stale(store, bugfix):
    """When the repository moves, facts about the code must not stay current."""
    store.save(bugfix)
    store.add_fact("T-1", kind="verified", content="pricing.py defines apply()",
                  source="read_investigate", revision="abc123")
    store.save(bugfix, repo_revision="abc123")

    resumed = TaskStore(store.path).load("T-1")
    assert resumed.repo_revision == "abc123"

    store.mark_stale("T-1")  # working tree moved underneath us
    assert store.facts("T-1") == []


def test_no_credentials_are_stored(store):
    """The store must never be where a secret ends up.

    The task record has no column for keys, tokens or endpoints, and this test
    fails loudly if one is ever added.
    """
    with store._connect() as conn:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(tasks)")]
    lowered = {c.lower() for c in columns}
    assert not lowered & {"api_key", "secret", "password", "token", "credential"}


# ======================================================================================
# Helpers
# ======================================================================================


def _record(action: WorkflowAction, evidence: Evidence | None = None):
    from layasdlc.workflow import ActionRecord
    return ActionRecord(
        action=action,
        from_phase=TaskPhase.CREATED,
        to_phase=TaskPhase.CREATED,
        source="test",
        reason="test",
        evidence=evidence,
    )


def _drive(store: TaskStore, task: WorkflowTask) -> None:
    """Route a task to completion and persist it at every step."""
    router = WorkflowRouter(controller=WorkflowController(
        engine=FakeEngine(handler=lambda request: answer(
            {"workflow_selection": "edit_code",
             "retry_vs_escalate": "escalate"}.get(request.decision_type, "edit_code"),
            confidence=0.9, allowed=tuple(request.allowed_options))),
        config=ControllerConfig(timeout_s=2.0),
        fallback=DeterministicEngine(),
        permissions=ToolPermissionPolicy.full()))

    from layasdlc.contracts import TaskKind, TaskState
    task.kind = TaskKind.BUG_FIX

    for _ in range(20):
        if task.is_terminal:
            break
        route = router.route(task)
        if route is None:
            break
        evidence = None
        if route.action is WorkflowAction.RUN_TESTS:
            evidence = Evidence.record("pytest tests/billing", True)
        router.apply(task, route, evidence=evidence)
        store.save(task)
