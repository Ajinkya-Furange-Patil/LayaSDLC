"""Bridge between the OpenCode plugin and the layasdlc backend (Stage 5).

Invoked as ``python -m layasdlc.opencode_bridge --input <file> --output <file>``.
The payload is read from a file and the result written to one, so user-supplied
task text never reaches a shell command line.

Operations
----------
``route``
    Create a task (or resume one by id) and return the next permitted action
    with the reasons and rules that constrained it.
``inspect``
    Return the task's full state plus its context facts.
``approve`` / ``deny``
    Settle a pending approval, then report the resumed phase and the next
    action to take.

Every operation persists to the SQLite store (Stage 4) and records the current
git revision, so a task survives a restart and facts can be invalidated when
the repository moves.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

from .contracts import TaskKind, TaskState
from .store import TaskStore
from .workflow import new_task


# ======================================================================================
# Git metadata -- read-only, never mutates the working tree
# ======================================================================================


def _git_revision(directory: str) -> str | None:
    """Current commit hash, or ``None`` when the directory is not a repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=directory, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _working_tree(directory: str) -> str | None:
    """Porcelain status, or ``None`` when the directory is not a repository."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=directory, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# ======================================================================================
# Construction helpers
# ======================================================================================


def _store(directory: str) -> TaskStore:
    store = TaskStore(Path(directory) / ".layasdlc.sqlite3")
    store.migrate()
    return store


def _router():
    """Build a router, allowing the engine to be swapped via the environment.

    ``LAYA_ENGINE`` defaults to ``deterministic`` so the bridge is offline and
    free. Setting it to ``laya`` opts into the live endpoint; the router still
    falls back deterministically if the endpoint is unavailable.
    """
    from .cli import build_router
    engine = os.environ.get("LAYA_ENGINE", "deterministic")
    return build_router(engine=engine, permissions="full")


# ======================================================================================
# Operations
# ======================================================================================


def op_route(store: TaskStore, payload: dict) -> dict:
    """Create or resume a task and return the next permitted action."""
    task_id = payload.get("task_id")
    if task_id:
        task = store.load(task_id)
        if task is None:
            return {"error": f"task {task_id!r} not found"}
    else:
        subject = payload.get("subject")
        if not subject:
            return {"error": "route requires --subject or --task-id"}
        state = TaskState(
            task_id=f"T-{uuid.uuid4().hex[:8]}",
            subject=subject,
            body=payload.get("body", ""),
            path=payload.get("path"),
        )
        kind = TaskKind(payload["kind"]) if payload.get("kind") else None
        task = new_task(state, kind=kind)
        # Persist immediately so the task exists before the router is asked --
        # a crash mid-route must not lose the task.
        store.save(task)

    router = _router()
    route = router.route(task)
    if route is None:
        return {
            "task_id": task.task_id,
            "phase": task.phase.value,
            "terminal": True,
            "unmet_conditions": list(task.unmet_conditions),
        }
    return {
        "task_id": task.task_id,
        "phase": task.phase.value,
        "next_action": route.action.value,
        "to_phase": route.to_phase.value,
        "reason": route.reason,
        "rules": list(route.rules),
        "source": route.source,
        "confidence": route.confidence,
        "error": route.error,
        "terminal": False,
        "unmet_conditions": list(task.unmet_conditions),
    }


def op_inspect(store: TaskStore, payload: dict) -> dict:
    task = store.load(payload["task_id"])
    if task is None:
        return {"error": f"task {payload['task_id']!r} not found"}
    return {
        "task": task.to_dict(),
        "facts": store.facts(task.task_id, include_stale=True),
    }


def op_approve(store: TaskStore, payload: dict, *, granted: bool) -> dict:
    """Settle a pending approval and report what to do next."""
    task = store.load(payload["task_id"])
    if task is None:
        return {"error": f"task {payload['task_id']!r} not found"}
    if task.phase.value != "awaiting_approval":
        return {"error": f"task {task.task_id!r} is not awaiting approval"}

    router = _router()
    by = payload.get("by", "opencode-user")
    reason = payload.get("reason")
    if granted:
        router.grant_approval(task, by=by, reason=reason)
    else:
        router.deny_approval(task, by=by, reason=reason)

    result: dict[str, Any] = {
        "task_id": task.task_id,
        "phase": task.phase.value,
        "approval": task.approval.to_dict() if task.approval else None,
        "terminal": task.is_terminal,
    }

    # After approving, show the LLM what to do next rather than making it ask.
    if granted and not task.is_terminal:
        route = router.route(task)
        if route:
            result["next_action"] = route.action.value
            result["reason"] = route.reason
            result["rules"] = list(route.rules)
    return result


def _deny(store: TaskStore, payload: dict) -> dict:
    return op_approve(store, payload, granted=False)


_HANDLERS: dict[str, Callable[[TaskStore, dict], dict]] = {
    "route": op_route,
    "inspect": op_inspect,
    "approve": lambda store, payload: op_approve(store, payload, granted=True),
    "deny": _deny,
}


# ======================================================================================
# Entry point
# ======================================================================================


def run(payload: dict, directory: str) -> dict:
    """Execute one bridge operation against ``directory``.

    Captures the git revision before and after, invalidating context facts when
    the repository has moved, and persists the task with the current revision.
    """
    action = payload.get("action")
    handler = _HANDLERS.get(action)
    if handler is None:
        return {"error": f"unknown action {action!r}"}

    store = _store(directory)

    # Facts recorded against an older revision are no longer current.
    task_id = payload.get("task_id")
    if task_id and action != "route":
        task = store.load(task_id)
        if task is not None and task.repo_revision is not None:
            current = _git_revision(directory)
            if current is not None and current != task.repo_revision:
                store.mark_stale(task_id)

    result = handler(store, payload)

    # Persist with the current revision so the next call can detect changes.
    result_task_id = result.get("task_id")
    if result_task_id:
        task = store.load(result_task_id)
        if task is not None:
            store.save(task, repo_revision=_git_revision(directory),
                       working_tree=_working_tree(directory))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="layasdlc-opencode-bridge")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    directory = payload.pop("directory", ".")

    try:
        result = run(payload, directory)
    except Exception as exc:  # the bridge must never crash the tool call
        result = {"error": f"{type(exc).__name__}: {exc}"}

    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
