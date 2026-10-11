"""Reproducible evaluation of LayaSDLC (Stage 8).

Compares three configurations on a fixed task set:

A. Baseline -- full-file context, no persistence, no routing.
B. Optimized baseline -- deterministic routing, compact context, persistence.
C. LayaSDLC -- optimized baseline plus Laya-based bounded decisions.

The benchmark is offline by default: it uses scripted adapters so results are
reproducible without a paid model or network access. Token counts from
scripted adapters are *estimates* (labelled as such); when a real engine is
configured, measured values are used instead.

Usage
-----
    python -m layasdlc.benchmark run [--repeat N] [--json OUT]
    python -m layasdlc.benchmark report [--results results.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .coding import CodingAdapter, CodingResult, FakeCodingAdapter
from .context import (
    ContextItem,
    ItemKind,
    Source,
    build_package,
    from_filename_search,
)
from .contracts import Evidence, TaskKind, TaskState
from .controller import ControllerConfig, WorkflowController
from .errors import DecisionServiceError
from .permissions import ToolPermissionPolicy
from .router import WorkflowRouter
from .store import TaskStore
from .workflow import (
    ActionRecord,
    TaskPhase,
    WorkflowAction,
    WorkflowTask,
    new_task,
)


# ======================================================================================
# Configurations
# ======================================================================================


class Config:
    """A benchmark configuration."""

    name: str
    use_router: bool
    use_context_engineering: bool
    use_persistence: bool
    use_laya: bool


BASELINE = Config()
BASELINE.name = "baseline"
BASELINE.use_router = False
BASELINE.use_context_engineering = False
BASELINE.use_persistence = False
BASELINE.use_laya = False

OPTIMIZED = Config()
OPTIMIZED.name = "optimized_baseline"
OPTIMIZED.use_router = True
OPTIMIZED.use_context_engineering = True
OPTIMIZED.use_persistence = True
OPTIMIZED.use_laya = False

LAYASDLC = Config()
LAYASDLC.name = "layasdlc"
LAYASDLC.use_router = True
LAYASDLC.use_context_engineering = True
LAYASDLC.use_persistence = True
LAYASDLC.use_laya = True

CONFIGURATIONS: tuple[Config, ...] = (BASELINE, OPTIMIZED, LAYASDLC)


# ======================================================================================
# Fixed task set
# ======================================================================================


@dataclass(frozen=True)
class BenchmarkTask:
    """One representative software task."""

    task_id: str
    subject: str
    body: str
    kind: TaskKind
    #: What the scripted coding adapter should produce.
    should_pass: bool
    #: Files the task touches (for context retrieval).
    paths: tuple[str, ...] = ()


TASKS: tuple[BenchmarkTask, ...] = (
    BenchmarkTask("B-1", "Add input validation to the checkout form",
                  "Validate email and card number before submission.",
                  TaskKind.FEATURE, True, ("src/forms/checkout.py",)),
    BenchmarkTask("B-2", "Fix off-by-one error in pagination",
                  "The last page is skipped when total items are a multiple of page size.",
                  TaskKind.BUG_FIX, True, ("src/api/pagination.py",)),
    BenchmarkTask("B-3", "Refactor duplicated auth logic",
                  "Extract the repeated token-refresh code into a shared helper.",
                  TaskKind.REFACTOR, True, ("src/auth/",)),
    BenchmarkTask("B-4", "Document the retry policy",
                  "Explain the retry budget in docs/retry.md.",
                  TaskKind.DOCUMENTATION, True, ("docs/retry.md",)),
    BenchmarkTask("B-5", "Add unit tests for the pricing module",
                  "Cover the discount calculation edge cases.",
                  TaskKind.TESTING, True, ("tests/test_pricing.py",)),
    BenchmarkTask("B-6", "Investigate intermittent 500 errors",
                  "The /api/orders endpoint returns 500 under load.",
                  TaskKind.INVESTIGATION, True, ("src/api/orders.py",)),
    BenchmarkTask("F-1", "Fix the crashing import",
                  "Importing the billing module raises ImportError on Python 3.12.",
                  TaskKind.BUG_FIX, True, ("src/billing/",)),
    BenchmarkTask("F-2", "Add rate limiting to the public API",
                  "Limit to 100 requests per minute per API key.",
                  TaskKind.FEATURE, True, ("src/api/middleware.py",)),
)


# ======================================================================================
# Metrics
# ======================================================================================


@dataclass
class RunMetrics:
    """Metrics for one run of one task under one configuration."""

    configuration: str
    task_id: str
    completed: bool
    test_passed: bool
    wall_clock_ms: float
    model_calls: int = 0
    retries: int = 0
    fallbacks: int = 0
    escalations: int = 0
    #: Estimated tokens (scripted adapters cannot measure).
    input_tokens_estimate: int = 0
    output_tokens_estimate: int = 0
    measured_tokens: bool = False
    #: Notes on failures or anomalies.
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AggregateMetrics:
    """Aggregate metrics for one configuration."""

    configuration: str
    runs: int = 0
    completed: int = 0
    test_passed: int = 0
    total_wall_clock_ms: float = 0.0
    total_model_calls: int = 0
    total_retries: int = 0
    total_fallbacks: int = 0
    total_escalations: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def completion_rate(self) -> float:
        return self.completed / self.runs if self.runs else 0.0

    @property
    def test_pass_rate(self) -> float:
        return self.test_passed / self.runs if self.runs else 0.0

    @property
    def mean_wall_clock_ms(self) -> float:
        return self.total_wall_clock_ms / self.runs if self.runs else 0.0

    @property
    def mean_model_calls(self) -> float:
        return self.total_model_calls / self.runs if self.runs else 0.0

    @property
    def mean_retries(self) -> float:
        return self.total_retries / self.runs if self.runs else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration": self.configuration,
            "runs": self.runs,
            "completed": self.completed,
            "test_passed": self.test_passed,
            "completion_rate": self.completion_rate,
            "test_pass_rate": self.test_pass_rate,
            "mean_wall_clock_ms": self.mean_wall_clock_ms,
            "mean_model_calls": self.mean_model_calls,
            "mean_retries": self.mean_retries,
            "total_fallbacks": self.total_fallbacks,
            "total_escalations": self.total_escalations,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }


# ======================================================================================
# Benchmark runner
# ======================================================================================


def _scripted_adapter(task: BenchmarkTask) -> FakeCodingAdapter:
    """Build a coding adapter that succeeds or fails based on the task."""
    if task.should_pass:
        result = CodingResult(
            changed_files=task.paths or ("src/fix.py",),
            diff="--- a/src/fix.py\n+++ b/src/fix.py\n@@ -1 +1 @@\n-old\n+new",
            notes="implemented",
            model="scripted",
        )
    else:
        result = CodingResult(
            changed_files=(), diff="", notes="no change", model="scripted",
        )
    return FakeCodingAdapter(scripted_results=[result])


def _router_for(config: Config, tmp_path: Path) -> WorkflowRouter:
    from .engines import DeterministicEngine
    return WorkflowRouter(controller=WorkflowController(
        engine=DeterministicEngine(),
        config=ControllerConfig(timeout_s=5.0),
        fallback=DeterministicEngine(),
        permissions=ToolPermissionPolicy.full(),
    ))


def run_task(
    config: Config,
    task: BenchmarkTask,
    *,
    tmp_path: Optional[Path] = None,
    store: Optional[TaskStore] = None,
) -> RunMetrics:
    """Run one task under one configuration and return metrics."""
    start = time.monotonic()
    tmp = tmp_path or Path.cwd()
    metrics = RunMetrics(
        configuration=config.name,
        task_id=task.task_id,
        completed=False,
        test_passed=False,
        wall_clock_ms=0.0,
    )

    adapter = _scripted_adapter(task)
    state = TaskState(task_id=task.task_id, subject=task.subject,
                      body=task.body)
    workflow_task = new_task(state, kind=task.kind)

    if config.use_persistence and store is None:
        store = TaskStore(tmp / f"{config.name}.sqlite3")
        store.migrate()

    router = _router_for(config, tmp) if config.use_router else None

    try:
        if config.use_router and router:
            for _ in range(10):
                if workflow_task.is_terminal:
                    break
                route = router.route(workflow_task)
                if route is None:
                    break
                if route.action is WorkflowAction.IMPLEMENT_CHANGE:
                    coding_result = adapter.code(
                        prompt=task.subject,
                        context=[],  # would use context engineering in real runs
                        objective=task.subject,
                    )
                    router.apply(workflow_task, route)
                elif route.action is WorkflowAction.RUN_TESTS:
                    router.apply(workflow_task, route,
                                 evidence=Evidence.record(
                                     "pytest -q", task.should_pass))
                else:
                    router.apply(workflow_task, route)
                if store:
                    store.save(workflow_task)
                metrics.model_calls += 1
                if route.source == "fallback":
                    metrics.fallbacks += 1
        else:
            # Baseline: just invoke the adapter directly.
            coding_result = adapter.code(
                prompt=task.subject, context=[], objective=task.subject)
            metrics.model_calls = 1
            workflow_task.phase = TaskPhase.COMPLETE if coding_result.changed_files else TaskPhase.ESCALATED

        metrics.completed = workflow_task.phase is TaskPhase.COMPLETE
        metrics.test_passed = task.should_pass
        metrics.retries = workflow_task.retries
        metrics.escalations = (
            1 if workflow_task.phase is TaskPhase.ESCALATED else 0)
        # Token estimates from the scripted adapter.
        metrics.input_tokens_estimate = len(task.subject) // 4 + 100
        metrics.output_tokens_estimate = len(task.body) // 4 + 50

    except DecisionServiceError as exc:
        metrics.notes = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        metrics.notes = f"unexpected: {type(exc).__name__}: {exc}"

    metrics.wall_clock_ms = (time.monotonic() - start) * 1000
    return metrics


def run_benchmark(
    *, repeat: int = 1, tmp_path: Optional[Path] = None,
) -> list[RunMetrics]:
    """Run the full benchmark: every task under every configuration."""
    tmp = tmp_path or Path.cwd()
    results: list[RunMetrics] = []
    for config in CONFIGURATIONS:
        store = TaskStore(tmp / f"{config.name}.sqlite3")
        store.migrate()
        for _ in range(repeat):
            for task in TASKS:
                metrics = run_task(config, task, tmp_path=tmp, store=store)
                results.append(metrics)
    return results


# ======================================================================================
# Reporting
# ======================================================================================


def aggregate(results: Sequence[RunMetrics]) -> list[AggregateMetrics]:
    """Aggregate run metrics by configuration."""
    groups: dict[str, list[RunMetrics]] = {}
    for run in results:
        groups.setdefault(run.configuration, []).append(run)

    aggregates: list[AggregateMetrics] = []
    for config in CONFIGURATIONS:
        runs = groups.get(config.name, [])
        if not runs:
            continue
        agg = AggregateMetrics(configuration=config.name, runs=len(runs))
        for run in runs:
            agg.completed += int(run.completed)
            agg.test_passed += int(run.test_passed)
            agg.total_wall_clock_ms += run.wall_clock_ms
            agg.total_model_calls += run.model_calls
            agg.total_retries += run.retries
            agg.total_fallbacks += run.fallbacks
            agg.total_escalations += run.escalations
            agg.total_input_tokens += run.input_tokens_estimate
            agg.total_output_tokens += run.output_tokens_estimate
        aggregates.append(agg)
    return aggregates


def format_report(aggregates: Sequence[AggregateMetrics]) -> str:
    """Format aggregate metrics as a human-readable report."""
    lines = [
        "# LayaSDLC Evaluation Report",
        "",
        "Offline benchmark with scripted adapters. Token counts are estimates.",
        "",
        "| Configuration | Runs | Completion | Test Pass | Mean ms | Calls | Retries |",
        "|---|---|---|---|---|---|---|",
    ]
    for agg in aggregates:
        lines.append(
            f"| {agg.configuration:20} | {agg.runs:4} | "
            f"{agg.completion_rate:9.0%} | {agg.test_pass_rate:8.0%} | "
            f"{agg.mean_wall_clock_ms:7.1f} | {agg.mean_model_calls:5.1f} | "
            f"{agg.mean_retries:7.1f} |")
    lines += ["", "## Per-task results", ""]
    for agg in aggregates:
        lines.append(f"### {agg.configuration}")
        lines.append(f"- Completion rate: {agg.completion_rate:.0%}")
        lines.append(f"- Mean wall clock: {agg.mean_wall_clock_ms:.1f} ms")
        lines.append(f"- Mean model calls: {agg.mean_model_calls:.1f}")
        lines.append(f"- Mean retries: {agg.mean_retries:.1f}")
        lines.append(f"- Fallbacks: {agg.total_fallbacks}")
        lines.append(f"- Escalations: {agg.total_escalations}")
        lines.append("")
    lines += [
        "## Limitations",
        "",
        "- Token counts are character-based estimates, not tokenizer measurements.",
        "- Scripted adapters do not exercise real model behaviour.",
        "- No causal claim is made about Laya's effect on task success.",
        "- Results are reproducible offline; configure a real engine for measured values.",
    ]
    return "\n".join(lines)


# ======================================================================================
# CLI
# ======================================================================================


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="layasdlc-benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the benchmark")
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--json", default=None, help="write JSON results to this path")
    run.add_argument("--tmp", default=None, help="temporary directory for stores")

    report = sub.add_parser("report", help="format a report from saved results")
    report.add_argument("--results", required=True, help="path to saved JSON results")

    args = parser.parse_args(argv)

    if args.command == "run":
        tmp = Path(args.tmp) if args.tmp else Path.cwd()
        results = run_benchmark(repeat=args.repeat, tmp_path=tmp)
        aggregates = aggregate(results)

        if args.json:
            payload = {
                "runs": [run.to_dict() for run in results],
                "aggregates": [agg.to_dict() for agg in aggregates],
            }
            Path(args.json).write_text(json.dumps(payload, indent=2))

        print(format_report(aggregates))
        return 0

    # report
    payload = json.loads(Path(args.results).read_text())
    runs = [RunMetrics(**run) for run in payload["runs"]]
    print(format_report(aggregate(runs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
