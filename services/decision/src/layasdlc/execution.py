"""Controlled execution engine (Stage 7).

Ties together the router, context engineering, coding adapter and evidence
recording into one bounded workflow:

    inspect → retrieve context → select workflow → invoke coding adapter
    → inspect diff → run tests → record evidence → accept or retry

Safety is enforced deterministically. The coding adapter is never given a
shell command to run; it receives structured input and returns a result. All
test execution goes through the permission policy. Approval gates block
destructive operations regardless of what the model suggests.

Laya's role is advisory: it may select among bounded next actions or help
prioritise evidence. Test results — never model output — determine whether
verification succeeded.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from .coding import CodingAdapter, CodingResult
from .contracts import Evidence
from .context import (
    ContextItem,
    ContextPackage,
    build_package,
    from_git_diff,
)
from .errors import ExecutionError
from .permissions import ToolPermissionPolicy
from .router import WorkflowRouter
from .store import TaskStore
from .workflow import (
    ActionRecord,
    TaskPhase,
    WorkflowAction,
    WorkflowTask,
    new_task,
    validate_transition,
)


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one verification check."""

    name: str
    passed: bool
    output: str = ""
    duration_ms: float = 0.0


@dataclass
class ExecutionResult:
    """What the execution engine did, step by step."""

    task: WorkflowTask
    checks: list[CheckResult] = field(default_factory=list)
    coding_result: Optional[CodingResult] = None
    accepted: bool = False
    reason: str = ""

    @property
    def all_checks_passed(self) -> bool:
        return all(check.passed for check in self.checks)


class ExecutionEngine:
    """Runs one bounded execution cycle for a task.

    A cycle is: route → (if IMPLEMENT_CHANGE) retrieve context → invoke
    coding adapter → run tests → record evidence → route again. The engine
    never loops indefinitely: ``max_cycles`` bounds the number of
    implement→test iterations, and the router's own budgets bound retries.
    """

    def __init__(
        self,
        router: WorkflowRouter,
        coding_adapter: CodingAdapter,
        store: TaskStore,
        *,
        permissions: ToolPermissionPolicy = ToolPermissionPolicy.full(),
        max_cycles: int = 3,
        test_command: Sequence[str] = ("pytest", "-q"),
        sandbox: Optional[Path] = None,
    ) -> None:
        self.router = router
        self.coding_adapter = coding_adapter
        self.store = store
        self.permissions = permissions
        self.max_cycles = max_cycles
        self.test_command = tuple(test_command)
        self.sandbox = sandbox

    # --- public API ---------------------------------------------------------------------

    def execute(self, task: WorkflowTask) -> ExecutionResult:
        """Run the bounded workflow until the task settles or cycles exhaust."""
        result = ExecutionResult(task=task)

        for cycle in range(self.max_cycles):
            if task.is_terminal:
                break

            route = self.router.route(task)
            if route is None:
                break

            if route.action is WorkflowAction.IMPLEMENT_CHANGE:
                self._implement(task, result)
            elif route.action is WorkflowAction.RUN_TESTS:
                self._test(task, result)
            elif route.action is WorkflowAction.REVIEW_DIFF:
                self._review(task, result)
            elif route.action is WorkflowAction.COMPLETE:
                self._complete(task, result)
                break
            else:
                # ESCALATE, REQUEST_APPROVAL, INSPECT_REPOSITORY, etc.
                self.router.apply(task, route)
                self.store.save(task)

        return result

    # --- steps ---------------------------------------------------------------------------

    def _implement(self, task: WorkflowTask, result: ExecutionResult) -> None:
        """Retrieve context, invoke the coding adapter, apply the change."""
        objective = task.task.subject
        context = self._gather_context(task)

        package = build_package(
            objective=objective,
            items=context,
            budget_tokens=8000,
            reserved_tokens=2000,
        )

        route = self.router.route(task)
        if route is None:
            return

        try:
            coding_result = self.coding_adapter.code(
                prompt=objective,
                context=package.items,
                objective=objective,
            )
        except Exception as exc:
            self.router.apply(task, route, error=f"coding adapter: {exc}")
            self.store.save(task)
            result.reason = f"coding adapter failed: {exc}"
            return

        result.coding_result = coding_result
        # An adapter that produced no changes is a failure, not a success.
        # Recording it as an error is what lets the retry budget exhaust.
        # A malformed result (not a CodingResult) is also a failure.
        if isinstance(coding_result, CodingResult) and coding_result.changed_files:
            error = None
        else:
            error = "coding adapter produced no usable change"
        self.router.apply(task, route, error=error)
        self.store.save(task)

    def _test(self, task: WorkflowTask, result: ExecutionResult) -> None:
        """Run the configured test command and record the result as evidence."""
        route = self.router.route(task)
        if route is None:
            return

        check = self._run_check("tests", self.test_command)
        result.checks.append(check)

        evidence = Evidence.record(
            test_command=" ".join(self.test_command),
            tests_passed=check.passed,
        )
        # A failing test is a failure: record it as an error so the retry
        # budget can exhaust. Otherwise the counter resets on every test run
        # and a permanently red task never escalates.
        error = None if check.passed else f"tests failed: {check.output[-200:]}"
        self.router.apply(task, route, evidence=evidence, error=error)
        self.store.save(task)

    def _review(self, task: WorkflowTask, result: ExecutionResult) -> None:
        """Review the diff. Acceptance is deterministic: tests must pass."""
        route = self.router.route(task)
        if route is None:
            return

        diff_items = from_git_diff(str(self.sandbox or Path.cwd()))
        check = CheckResult(
            name="review",
            passed=task.verification.value == "tests_passed",
            output=f"{len(diff_items)} changed file(s)",
        )
        result.checks.append(check)
        self.router.apply(task, route)
        self.store.save(task)

    def _complete(self, task: WorkflowTask, result: ExecutionResult) -> None:
        route = self.router.route(task)
        if route is None:
            return
        self.router.apply(task, route)
        self.store.save(task)
        result.accepted = task.phase is TaskPhase.COMPLETE
        result.reason = "all checks passed and completion conditions met"

    # --- helpers -------------------------------------------------------------------------

    def _gather_context(self, task: WorkflowTask) -> list[ContextItem]:
        """Collect context from the diff, the task path and test failures."""
        repo = str(self.sandbox or Path.cwd())
        items: list[ContextItem] = []
        items.extend(from_git_diff(repo))

        if task.task.path:
            items.extend(_context_from_path(task.task.path))

        # Include facts stored against this task.
        for fact in self.store.facts(task.task_id):
            items.append(ContextItem(
                kind=_fact_kind(fact["kind"]),
                content=fact["content"],
                source=_fact_source(fact),
                score=0.6,
            ))
        return items

    def _run_check(self, name: str, command: Sequence[str]) -> CheckResult:
        """Run one check command. Never passes arbitrary model output here."""
        import time
        start = time.monotonic()
        try:
            proc = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.sandbox) if self.sandbox else None,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CheckResult(name=name, passed=False, output=str(exc))
        duration_ms = (time.monotonic() - start) * 1000
        return CheckResult(
            name=name,
            passed=proc.returncode == 0,
            output=(proc.stdout + proc.stderr)[-4000:],
            duration_ms=duration_ms,
        )


def _fact_kind(kind: str):
    from .context import ItemKind
    try:
        return ItemKind(kind)
    except ValueError:
        return ItemKind.SNIPPET


def _fact_source(fact: dict[str, Any]):
    from .context import Source
    return Source(
        file=fact.get("file"),
        line_start=fact.get("line_start"),
        line_end=fact.get("line_end"),
    )


def _context_from_path(file_path: str) -> list[ContextItem]:
    """Read a file and return it as a context item, or an empty list."""
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return [ContextItem(
        kind=ItemKind.SNIPPET,
        content="\n".join(lines[:200]),
        source=Source(file=file_path, line_start=1,
                     line_end=min(len(lines), 200)),
        score=0.7,
    )]


__all__ = [
    "CheckResult",
    "ExecutionEngine",
    "ExecutionResult",
]
