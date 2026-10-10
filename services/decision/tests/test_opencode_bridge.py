"""Stage 5: OpenCode bridge -- route, inspect, approve operations.

The bridge is tested directly (not through the TypeScript plugin, which
requires a running OpenCode instance). The Python side is the full
integration surface.
"""

from __future__ import annotations

import pytest

from layasdlc.opencode_bridge import run


# ======================================================================================
# Route
# ======================================================================================


def test_route_creates_a_new_task(tmp_path):
    result = run({"action": "route", "subject": "Fix the crash",
                  "kind": "bug_fix"}, str(tmp_path))

    assert result.get("next_action")
    assert result["task_id"].startswith("T-")
    assert result["phase"] == "created"
    assert result["next_action"] is not None
    assert result["terminal"] is False
    assert result["reason"]
    assert isinstance(result["rules"], list)


def test_route_resumes_an_existing_task(tmp_path):
    first = run({"action": "route", "subject": "Fix the crash",
                 "kind": "bug_fix"}, str(tmp_path))
    second = run({"action": "route", "task_id": first["task_id"]},
                 str(tmp_path))

    assert second["task_id"] == first["task_id"]
    assert second.get("next_action")


def test_route_requires_subject_or_task_id(tmp_path):
    result = run({"action": "route"}, str(tmp_path))
    assert "error" in result


def test_route_unknown_task(tmp_path):
    result = run({"action": "route", "task_id": "T-404"}, str(tmp_path))
    assert "error" in result


def test_route_returns_next_action_for_bugfix(tmp_path):
    """A bug-fix task should inspect the repository first (context-first rule)."""
    result = run({"action": "route", "subject": "Fix the crash",
                  "kind": "bug_fix"}, str(tmp_path))
    assert result["next_action"] == "inspect_repository"


def test_route_requests_approval_for_high_risk(tmp_path):
    """A deployment task must request approval before any work."""
    result = run({"action": "route",
                  "subject": "Deploy the checkout service to production"},
                 str(tmp_path))
    assert result["next_action"] == "request_approval"
    assert "approval_required" in result["rules"]


def test_route_persists_task_to_store(tmp_path):
    result = run({"action": "route", "subject": "Fix the crash",
                  "kind": "bug_fix"}, str(tmp_path))
    # The task must be in the store after routing.
    from layasdlc import TaskStore
    store = TaskStore(tmp_path / ".layasdlc.sqlite3")
    task = store.load(result["task_id"])
    assert task is not None


# ======================================================================================
# Inspect
# ======================================================================================


def test_inspect_returns_task_state(tmp_path):
    created = run({"action": "route", "subject": "Fix the crash",
                   "kind": "bug_fix"}, str(tmp_path))
    result = run({"action": "inspect", "task_id": created["task_id"]},
                 str(tmp_path))

    assert result["task"]["task_id"] == created["task_id"]
    assert result["task"]["phase"] == "created"
    assert "facts" in result


def test_inspect_unknown_task(tmp_path):
    result = run({"action": "inspect", "task_id": "T-404"}, str(tmp_path))
    assert "error" in result


# ======================================================================================
# Approve / Deny
# ======================================================================================


def test_approve_settles_pending_request(tmp_path):
    """Approve a high-risk task and verify it resumes."""
    created = run({"action": "route",
                   "subject": "Deploy the checkout service to production"},
                  str(tmp_path))
    # Move to awaiting_approval.
    from layasdlc import TaskStore, WorkflowRouter, WorkflowController, ControllerConfig, DeterministicEngine, ToolPermissionPolicy
    store = TaskStore(tmp_path / ".layasdlc.sqlite3")
    task = store.load(created["task_id"])
    router = WorkflowRouter(controller=WorkflowController(
        engine=DeterministicEngine(),
        config=ControllerConfig(timeout_s=2.0),
        permissions=ToolPermissionPolicy.full()))
    router.step(task)
    store.save(task)

    result = run({"action": "approve", "task_id": created["task_id"],
                  "by": "test-user"}, str(tmp_path))

    assert result["approval"]["granted"] is True
    assert result["approval"]["by"] == "test-user"
    assert result["phase"] == "created"  # resumed where it paused
    assert result.get("next_action") is not None  # tells LLM what to do next


def test_deny_escalates_task(tmp_path):
    created = run({"action": "route",
                   "subject": "Deploy the checkout service to production"},
                  str(tmp_path))
    from layasdlc import TaskStore, WorkflowRouter, WorkflowController, ControllerConfig, DeterministicEngine, ToolPermissionPolicy
    store = TaskStore(tmp_path / ".layasdlc.sqlite3")
    task = store.load(created["task_id"])
    router = WorkflowRouter(controller=WorkflowController(
        engine=DeterministicEngine(),
        config=ControllerConfig(timeout_s=2.0),
        permissions=ToolPermissionPolicy.full()))
    router.step(task)
    store.save(task)

    result = run({"action": "deny", "task_id": created["task_id"],
                  "by": "test-user"}, str(tmp_path))

    assert "error" not in result
    assert result["approval"]["granted"] is False
    assert result["phase"] == "escalated"
    assert result["terminal"] is True


def test_approve_rejects_when_not_pending(tmp_path):
    """Cannot approve a task that is not awaiting approval."""
    created = run({"action": "route", "subject": "Fix the crash",
                   "kind": "bug_fix"}, str(tmp_path))
    result = run({"action": "approve", "task_id": created["task_id"]},
                 str(tmp_path))
    assert "error" in result


def test_approve_unknown_task(tmp_path):
    result = run({"action": "approve", "task_id": "T-404"}, str(tmp_path))
    assert "error" in result


# ======================================================================================
# Error handling
# ======================================================================================


def test_unknown_action(tmp_path):
    result = run({"action": "destroy"}, str(tmp_path))
    assert "error" in result
    assert "unknown action" in result["error"]


def test_bridge_never_crashes_on_bad_input(tmp_path):
    """The bridge must return an error dict, never raise through the tool."""
    result = run({"action": "route", "subject": None}, str(tmp_path))
    assert "error" in result
