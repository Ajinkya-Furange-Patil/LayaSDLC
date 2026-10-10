"""The smallest useful CLI for the Stage 3 workflow router.

Two commands, both deliberately boring:

``route``
    Submit one task and watch it move. Shows the current state, the next
    permitted action, *why* that action was chosen, and the transition history.
    Runs a bounded number of steps so a developer can see a task end to end.

``demo``
    Runs the five acceptance scenarios from ``Stages/stage3.md`` -- a simple
    documentation task, a bug fix, a failed test, an ambiguous task and a
    high-risk action -- with scripted evidence and scripted human approvals.

Both are offline by default. ``--engine laya`` is the only way to reach a network
endpoint, and it is never used by the tests.

Nothing here executes anything either: the CLI reports what the router *permits*.
It never touches the working tree, never shells out and never runs a test suite --
when the router asks for tests, the CLI records whatever the operator tells it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .contracts import Evidence, TaskKind, TaskState
from .controller import ControllerConfig, WorkflowController
from .engines import DeterministicEngine, LayaHttpEngine
from .errors import DecisionServiceError
from .permissions import ToolPermissionPolicy
from .policy import PolicyConfig
from .router import WorkflowRouter
from .workflow import TaskPhase, WorkflowAction, WorkflowTask, new_task

#: Hard ceiling on how many steps a single invocation will take. Belt and braces
#: against a routing loop; the router has its own budgets, but a CLI that could
#: spin forever would be unusable regardless of who is at fault.
MAX_STEPS = 40


# ======================================================================================
# Building a router
# ======================================================================================


def build_router(*, engine: str = "deterministic", permissions: str = "full",
                 base_url: Optional[str] = None,
                 model: Optional[str] = None) -> WorkflowRouter:
    """Assemble a router for offline use, or for the live endpoint on request.

    Defaults to the full tool allow-list because the router executes nothing:
    ``full`` only widens which *steps may be chosen*. The endpoint, by contrast,
    is never defaulted -- pointing the CLI at a hosted service is an explicit act,
    taken by passing ``--base-url`` or setting ``LAYA_BASE_URL``.
    """
    policy = ToolPermissionPolicy.full() if permissions == "full" \
        else ToolPermissionPolicy.read_only()

    if engine == "laya":
        resolved = base_url or os.environ.get("LAYA_BASE_URL")
        if not resolved:
            raise ValueError(
                "--engine laya needs --base-url (or LAYA_BASE_URL in the "
                "environment); the endpoint is not assumed")
        primary = LayaHttpEngine(
            base_url=resolved,
            model=model or os.environ.get("LAYA_MODEL"),
            api_key=os.environ.get("LAYA_API_KEY"),
        )
    else:
        primary = DeterministicEngine()

    return WorkflowRouter(
        controller=WorkflowController(
            engine=primary,
            config=ControllerConfig(timeout_s=5.0, policy=PolicyConfig()),
            fallback=DeterministicEngine(),
            permissions=policy,
        ),
    )


# ======================================================================================
# Running a task
# ======================================================================================


@dataclass
class RunReport:
    """What one invocation did to one task."""

    task: WorkflowTask
    steps: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def trail(self) -> str:
        """``created --inspect_repository--> inspecting --...``"""
        parts: list[str] = []
        for record in self.task.history:
            parts.append(record.from_phase.value)
            parts.append(f"--{record.action.value}-->")
            parts.append(record.to_phase.value)
        return " ".join(parts) if parts else "(no steps taken)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "steps": self.steps,
            "approvals": self.approvals,
        }


def run_task(task: WorkflowTask, router: WorkflowRouter, *,
             max_steps: int = MAX_STEPS,
             evidence: Optional[Sequence[tuple[str, bool]]] = None,
             approvals: Sequence[bool] = ()) -> RunReport:
    """Advance ``task`` until it settles or ``max_steps`` is reached.

    ``evidence`` is a queue of ``(command, passed)`` pairs handed back after each
    ``RUN_TESTS`` step; anything left over is unused. ``approvals`` is the queue
    of human verdicts, ``True`` to grant. Both are caller-supplied because this
    service does not run tests and cannot approve its own work.
    """
    pending_evidence = list(evidence or [])
    pending_approvals = list(approvals)
    report = RunReport(task=task)

    for _ in range(max_steps):
        route = router.route(task)
        if route is None:
            if task.phase is TaskPhase.AWAITING_APPROVAL and pending_approvals:
                granted = pending_approvals.pop(0)
                if granted:
                    router.grant_approval(task, by="operator",
                                          reason="granted from the CLI")
                else:
                    router.deny_approval(task, by="operator",
                                         reason="denied from the CLI")
                report.approvals.append({"granted": granted, "by": "operator"})
                continue
            break

        step_evidence = None
        if route.action is WorkflowAction.RUN_TESTS and pending_evidence:
            command, passed = pending_evidence.pop(0)
            step_evidence = Evidence.record(command, passed)

        router.apply(task, route, evidence=step_evidence)
        entry = route.to_dict()
        if step_evidence is not None:
            # The router records the evidence on the task; surface it on the step
            # too, so a reader of the trace sees what was actually reported back.
            entry["evidence"] = {
                "test_command": step_evidence.test_command,
                "tests_passed": step_evidence.tests_passed,
            }
        report.steps.append(entry)
        if task.is_terminal:
            break
    else:
        report.steps.append({
            "action": None,
            "source": None,
            "reason": f"stopped: the step budget of {max_steps} was reached",
            "rules": ["cli_step_budget"],
            "to_phase": task.phase.value,
        })

    return report


# ======================================================================================
# Rendering
# ======================================================================================


def _headline(task: WorkflowTask) -> str:
    return (f"task {task.task_id!r}  {task.task.subject!r}\n"
            f"  kind={task.kind.value if task.kind else 'unclassified'}  "
            f"phase={task.phase.value}  safety={task.finding.safety_class.value}  "
            f"verification={task.verification.value}\n"
            f"  permitted: "
            + (", ".join(a.value for a in task.permitted_actions) or "(none)"))


def render_run(report: RunReport, *, title: str = "", as_json: bool = False) -> str:
    if as_json:
        return json.dumps(report.to_dict(), indent=2, sort_keys=False)

    task = report.task
    lines = [f"== {title}" if title else "== task run", _headline(task), ""]

    if not report.steps:
        lines.append("  no action proposed (the task has settled)")

    for index, step in enumerate(report.steps, start=1):
        action = step.get("action") or "(none)"
        lines.append(f"  {index}. {action}  [source={step.get('source')}]")
        lines.append(f"       why : {step.get('reason')}")
        lines.append(f"       rules: {', '.join(step.get('rules') or [])}")
        if step.get("confidence") is not None:
            lines.append(f"       confidence: {step['confidence']:.4f}")
        if step.get("error"):
            lines.append(f"       error: {step['error']}")
        if step.get("evidence"):
            evidence = step["evidence"]
            lines.append(f"       evidence: {evidence['test_command']!r} -> "
                         f"{'passed' if evidence['tests_passed'] else 'FAILED'}")
        lines.append(f"       -> phase={step.get('to_phase')}")

    if report.approvals:
        for approval in report.approvals:
            verdict = "granted" if approval["granted"] else "denied"
            lines.append(f"  approval {verdict} by {approval['by']}")

    lines += [
        "",
        f"final phase : {task.phase.value}",
        f"history     : {len(task.history)} step(s)",
        f"retries     : {task.retries}",
        f"trail       : {report.trail}",
        f"unmet rules : {', '.join(task.unmet_conditions) or '(none)'}",
    ]
    if task.approval is not None:
        verdict = "granted" if task.approval.granted else "denied"
        lines.append(f"approval    : {verdict} by {task.approval.by}")
    return "\n".join(lines)


# ======================================================================================
# The five acceptance scenarios
# ======================================================================================


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    task: TaskState
    kind: Optional[TaskKind]
    permissions: str = "full"
    #: ``(command, passed)`` handed back after each RUN_TESTS step.
    evidence: Sequence[tuple[str, bool]] = ()
    #: Human verdict for each approval request.
    approvals: Sequence[bool] = ()


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="docs",
        title="A simple documentation task",
        task=TaskState(
            task_id="T-DOCS",
            subject="Document the retry budget",
            body="Add a short section to docs/routing.md explaining how many times a "
                 "step may fail before the task is escalated.",
            path="docs/routing.md",
        ),
        kind=TaskKind.DOCUMENTATION,
        evidence=(("pytest -q --collect-only", True),),
    ),
    Scenario(
        key="bugfix",
        title="A bug-fix task requiring repository inspection",
        task=TaskState(
            task_id="T-BUGFIX",
            subject="Checkout throws 500 on promo code",
            body="Applying any promo code raises a 500; the trace shows a None "
                 "discount after the pricing refactor.",
            path="src/billing/pricing.py",
        ),
        kind=TaskKind.BUG_FIX,
        evidence=(("pytest tests/billing", True),),
    ),
    Scenario(
        key="failing-test",
        title="A failed test requiring diagnosis or escalation",
        task=TaskState(
            task_id="T-RED",
            subject="Test suite fails consistently after the merge",
            body="tests/test_pricing.py fails on every run after the merge; it still "
                 "fails when the suite is run in isolation.",
            path="tests/test_pricing.py",
        ),
        kind=TaskKind.BUG_FIX,
        evidence=(("pytest tests/test_pricing.py", False),),
    ),
    Scenario(
        key="ambiguous",
        title="An ambiguous task requiring more information or escalation",
        task=TaskState(
            task_id="T-VAGUE",
            subject="Improve the thing a bit",
            body="The stakeholder wants it improved somehow. The scope was never "
                 "written down and nobody can say which component is meant.",
        ),
        kind=None,
    ),
    Scenario(
        key="high-risk",
        title="A high-risk action requiring approval",
        task=TaskState(
            task_id="T-DEPLOY",
            subject="Deploy the checkout service to production",
            body="Roll out build 4821 to production and enable the new pricing flag.",
        ),
        kind=TaskKind.FEATURE,
        evidence=(("pytest -q", True),),
        approvals=(True,),
    ),
)

_BY_KEY = {scenario.key: scenario for scenario in SCENARIOS}


def run_scenario(scenario: Scenario, *, engine: str = "deterministic") -> RunReport:
    router = build_router(engine=engine, permissions=scenario.permissions)
    task = new_task(scenario.task, kind=scenario.kind)
    return run_task(task, router, evidence=scenario.evidence,
                    approvals=scenario.approvals)


# ======================================================================================
# Commands
# ======================================================================================


def _cmd_route(args: argparse.Namespace) -> int:
    kind = TaskKind.parse(args.kind) if args.kind else None
    state = TaskState(task_id=args.task_id, subject=args.subject,
                      body=args.body or "", path=args.path)
    router = build_router(engine=args.engine, permissions=args.permissions,
                          base_url=args.base_url, model=args.model)
    task = new_task(state, kind=kind)
    approvals: tuple[bool, ...] = () if args.approve is None \
        else (bool(args.approve),)
    report = run_task(task, router, max_steps=args.steps,
                      evidence=((args.test_command, not args.tests_fail),),
                      approvals=approvals)
    print(render_run(report, title=f"route {state.task_id}", as_json=args.json))
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    selected = SCENARIOS if args.scenario is None \
        else tuple(s for s in SCENARIOS if s.key == args.scenario)
    if not selected:
        print(f"unknown scenario {args.scenario!r}; known: "
              + ", ".join(s.key for s in SCENARIOS), file=sys.stderr)
        return 2

    reports = [run_scenario(scenario, engine=args.engine) for scenario in selected]
    if args.json:
        print(json.dumps(
            {scenario.key: report.to_dict()
             for scenario, report in zip(selected, reports)},
            indent=2))
        return 0

    for scenario, report in zip(selected, reports):
        print(render_run(report, title=f"{scenario.key} -- {scenario.title}"))
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="layasdlc",
        description="LayaSDLC workflow router: routes tasks to their next permitted "
                    "step without executing anything.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    route = sub.add_parser("route", help="submit one task and advance it")
    route.add_argument("--task-id", default="T-DEMO")
    route.add_argument("--subject", required=True)
    route.add_argument("--body", default=None)
    route.add_argument("--path", default=None)
    route.add_argument("--kind", default=None,
                       choices=[k.value for k in TaskKind])
    route.add_argument("--steps", type=int, default=MAX_STEPS,
                       help=f"maximum steps to take (default {MAX_STEPS})")
    route.add_argument("--permissions", default="full", choices=("read", "full"),
                       help="tool allow-list offered to the router. The router "
                            "executes nothing, so 'full' only widens which steps "
                            "may be *chosen*; it cannot make anything run.")
    route.add_argument("--engine", default="deterministic",
                       choices=("deterministic", "laya"))
    route.add_argument("--base-url", default=None)
    route.add_argument("--model", default=None)
    route.add_argument("--test-command", default="pytest -q")
    route.add_argument("--tests-fail", action="store_true",
                       help="report the test run as failed")
    approvals = route.add_mutually_exclusive_group()
    approvals.add_argument("--approve", action="store_true", default=None)
    approvals.add_argument("--deny", action="store_true", default=None)
    route.add_argument("--json", action="store_true")
    route.set_defaults(func=_cmd_route)

    demo = sub.add_parser("demo", help="run the five acceptance scenarios")
    demo.add_argument("--scenario", default=None,
                      help="run one scenario; one of " + ", ".join(s.key for s in SCENARIOS))
    demo.add_argument("--engine", default="deterministic",
                      choices=("deterministic", "laya"))
    demo.add_argument("--json", action="store_true")
    demo.set_defaults(func=_cmd_demo)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "deny", None):
        args.approve = False
    try:
        return args.func(args)
    except (DecisionServiceError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
