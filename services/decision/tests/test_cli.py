"""The Stage 3 CLI.

Two things are worth asserting here beyond "it prints": that the commands settle
without ever reaching a shell or the filesystem, and that the human-facing output
actually carries the reasons a route was chosen -- a CLI that hid them would
defeat the point of recording them.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from layasdlc.cli import SCENARIOS, build_parser, build_router, main, render_run, run_scenario

KEYS = [scenario.key for scenario in SCENARIOS]


def test_the_acceptance_scenarios_are_all_present():
    assert KEYS == ["docs", "bugfix", "failing-test", "ambiguous", "high-risk"]


# ======================================================================================
# demo
# ======================================================================================


def test_demo_runs_every_scenario(capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out

    for scenario in SCENARIOS:
        assert scenario.key in out
        assert scenario.title in out
    assert out.count("final phase") == len(SCENARIOS)


def test_demo_reports_why_each_step_was_chosen(capsys):
    assert main(["demo", "--scenario", "bugfix"]) == 0
    out = capsys.readouterr().out

    assert "why :" in out
    assert "rules:" in out
    assert "test_after_change" in out          # a mandatory rule, named
    assert "review_before_completion" in out


def test_demo_shows_the_trail_of_a_complete_task(capsys):
    assert main(["demo", "--scenario", "docs"]) == 0
    out = capsys.readouterr().out

    assert "final phase : complete" in out
    assert "trail       : created --implement_change-->" in out
    assert "unmet rules : (none)" in out


def test_demo_shows_escalation_and_what_was_still_missing(capsys):
    assert main(["demo", "--scenario", "failing-test"]) == 0
    out = capsys.readouterr().out

    assert "final phase : escalated" in out
    assert "escalate" in out


def test_demo_records_the_approval_and_who_gave_it(capsys):
    assert main(["demo", "--scenario", "high-risk"]) == 0
    out = capsys.readouterr().out

    assert "request_approval" in out
    assert "approval granted by operator" in out
    assert "approval    : granted by operator" in out
    assert "safety=deployment" in out


def test_demo_json_is_machine_readable(capsys):
    assert main(["demo", "--scenario", "ambiguous", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert set(payload) == {"ambiguous"}
    task = payload["ambiguous"]["task"]
    assert task["phase"] == "escalated"
    assert task["kind"] is None
    assert task["history"]
    assert all(step["reason"] for step in payload["ambiguous"]["steps"])


def test_an_unknown_scenario_is_refused(capsys):
    assert main(["demo", "--scenario", "nope"]) == 2
    assert "unknown scenario" in capsys.readouterr().err


# ======================================================================================
# route
# ======================================================================================


def test_route_submits_one_task_and_shows_the_state(capsys):
    code = main(["route", "--task-id", "T-1", "--subject", "Fix the typo",
                 "--kind", "documentation", "--steps", "3"])
    assert code == 0
    out = capsys.readouterr().out

    assert "task 'T-1'" in out
    assert "kind=documentation" in out
    assert "permitted:" in out


def test_route_is_offline_by_default_and_makes_no_shell_calls(capsys, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("the CLI must not shell out")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "call", explode)

    assert main(["route", "--subject", "Document the retry budget",
                 "--kind", "documentation"]) == 0
    assert "final phase : complete" in capsys.readouterr().out


def test_route_json_exposes_the_history(capsys):
    assert main(["route", "--subject", "Document the retry budget",
                 "--kind", "documentation", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["task"]["task_id"] == "T-DEMO"
    assert payload["task"]["phase"] == "complete"
    assert [step["action"] for step in payload["steps"]] == [
        "implement_change", "run_tests", "review_diff", "complete"]


def test_route_records_failing_evidence_when_reported(capsys):
    assert main(["route", "--subject", "Deploy the checkout service to production",
                 "--kind", "feature", "--approve", "--tests-fail", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    recorded = [step for step in payload["steps"]
                if step.get("action") == "run_tests"]
    assert recorded and recorded[0]["evidence"]["tests_passed"] is False


def test_route_escalates_a_high_risk_task_when_approval_is_denied(capsys):
    assert main(["route", "--subject", "Deploy checkout to production",
                 "--kind", "feature", "--deny", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["task"]["phase"] == "escalated"
    assert payload["task"]["approval"]["granted"] is False


def test_route_completes_a_high_risk_task_when_approval_is_granted(capsys):
    assert main(["route", "--subject", "Deploy checkout to production",
                 "--kind", "feature", "--approve", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["task"]["phase"] == "complete"
    assert payload["task"]["approval"]["granted"] is True


def test_route_stops_at_the_step_limit_instead_of_spinning(capsys):
    assert main(["route", "--subject", "Deploy checkout to production",
                 "--kind", "feature", "--steps", "1", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    # One real step, plus the marker saying why it stopped.
    assert [step["action"] for step in payload["steps"]] == ["request_approval", None]
    assert payload["task"]["phase"] == "awaiting_approval"


# ======================================================================================
# Engine selection
# ======================================================================================


def test_the_live_engine_is_never_assumed(capsys, monkeypatch):
    monkeypatch.delenv("LAYA_BASE_URL", raising=False)

    assert main(["route", "--subject", "Fix the crash", "--engine", "laya"]) == 1
    error = capsys.readouterr().err
    assert "LAYA_BASE_URL" in error
    assert "not assumed" in error


def test_laya_engine_honours_an_explicit_endpoint(capsys, monkeypatch):
    monkeypatch.setenv("LAYA_BASE_URL", "https://example.invalid")
    router = build_router(engine="laya")
    assert router.controller.engine.base_url == "https://example.invalid"


def test_permissions_default_to_full_because_the_router_executes_nothing():
    router = build_router()
    assert router.controller.permissions.permits("edit_code")
    assert router.controller.permissions.permits("read_investigate")


def test_read_only_permissions_can_only_inspect():
    router = build_router(permissions="read")
    assert router.controller.permissions.permits("read_investigate")
    assert not router.controller.permissions.permits("edit_code")


# ======================================================================================
# Rendering and parsing
# ======================================================================================


def test_rendering_never_hides_an_unmet_condition():
    report = run_scenario(SCENARIOS[3])  # ambiguous -> escalated
    text = render_run(report, title="probe")

    assert "unmet rules" in text
    assert report.task.unmet_conditions


def test_every_scenario_renders_without_raising():
    for scenario in SCENARIOS:
        text = render_run(run_scenario(scenario), title=scenario.key)
        assert "final phase" in text
        assert "history" in text


def test_the_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_route_requires_a_subject():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["route"])


# ======================================================================================
# inspect (Stage 4 item 4.7)
# ======================================================================================


def test_inspect_lists_all_tasks(tmp_path, capsys):
    from layasdlc.cli import main
    store = tmp_path / "test.sqlite3"

    # Save two tasks via the store directly.
    from layasdlc import TaskStore, new_task, TaskState
    s = TaskStore(store)
    s.migrate()
    s.save(new_task(TaskState(task_id="T-A", subject="First")))
    s.save(new_task(TaskState(task_id="T-B", subject="Second")))

    assert main(["inspect", "--store", str(store)]) == 0
    out = capsys.readouterr().out
    assert "T-A" in out
    assert "T-B" in out


def test_inspect_shows_one_task(tmp_path, capsys):
    from layasdlc.cli import main
    from layasdlc import TaskStore, new_task, TaskState, WorkflowAction
    from layasdlc.workflow import ActionRecord, TaskPhase
    store = tmp_path / "test.sqlite3"
    s = TaskStore(store)
    s.migrate()
    task = new_task(TaskState(task_id="T-1", subject="Deploy to production"))
    task.history.append(ActionRecord(
        action=WorkflowAction.REQUEST_APPROVAL,
        from_phase=TaskPhase.CREATED, to_phase=TaskPhase.AWAITING_APPROVAL,
        source="policy", reason="deployment requires approval"))
    task.phase = TaskPhase.AWAITING_APPROVAL
    s.save(task)

    assert main(["inspect", "--store", str(store), "--task-id", "T-1"]) == 0
    out = capsys.readouterr().out
    assert "T-1" in out
    assert "awaiting_approval" in out
    assert "request_approval" in out
    assert "approval required" in out or "deployment" in out


def test_inspect_json_is_machine_readable(tmp_path, capsys):
    from layasdlc.cli import main
    from layasdlc import TaskStore, new_task, TaskState
    store = tmp_path / "test.sqlite3"
    s = TaskStore(store)
    s.migrate()
    s.save(new_task(TaskState(task_id="T-1", subject="Test")))

    assert main(["inspect", "--store", str(store), "--task-id", "T-1", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task"]["task_id"] == "T-1"
    assert payload["task"]["phase"] == "created"


def test_inspect_reports_missing_task(tmp_path, capsys):
    from layasdlc.cli import main
    store = tmp_path / "empty.sqlite3"
    assert main(["inspect", "--store", str(store), "--task-id", "T-404"]) == 1
    assert "no task" in capsys.readouterr().err
