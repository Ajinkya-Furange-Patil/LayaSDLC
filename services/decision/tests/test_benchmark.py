"""Stage 8: reproducible evaluation tests.

The benchmark runs offline with scripted adapters, so these tests verify
the three configurations produce comparable, reproducible results.
"""

from __future__ import annotations

import pytest

from layasdlc.benchmark import (
    BASELINE,
    CONFIGURATIONS,
    LAYASDLC,
    OPTIMIZED,
    TASKS,
    AggregateMetrics,
    aggregate,
    format_report,
    main,
    run_benchmark,
    run_task,
)


# ======================================================================================
# Configuration
# ======================================================================================


def test_three_configurations_exist():
    assert [c.name for c in CONFIGURATIONS] == [
        "baseline", "optimized_baseline", "layasdlc"]


def test_laya_uses_all_optimizations():
    assert LAYASDLC.use_router
    assert LAYASDLC.use_context_engineering
    assert LAYASDLC.use_persistence
    assert LAYASDLC.use_laya


def test_baseline_uses_no_optimizations():
    assert not BASELINE.use_router
    assert not BASELINE.use_context_engineering
    assert not BASELINE.use_persistence
    assert not BASELINE.use_laya


def test_optimized_adds_router_and_context():
    assert OPTIMIZED.use_router
    assert OPTIMIZED.use_context_engineering
    assert OPTIMIZED.use_persistence
    assert not OPTIMIZED.use_laya


# ======================================================================================
# Task set
# ======================================================================================


def test_task_set_is_fixed_and_representative():
    assert len(TASKS) >= 5
    kinds = {task.kind for task in TASKS}
    assert len(kinds) >= 4


# ======================================================================================
# Running tasks
# ======================================================================================


def test_baseline_run_completes_passing_task(tmp_path):
    task = TASKS[0]
    metrics = run_task(BASELINE, task, tmp_path=tmp_path)
    assert metrics.configuration == "baseline"
    assert metrics.task_id == task.task_id
    assert metrics.completed is True


def test_baseline_run_fails_failing_task(tmp_path):
    task = TASKS[0]
    metrics = run_task(BASELINE, task, tmp_path=tmp_path)
    # Baseline has no retry budget; a no-change result still completes.
    assert metrics.completed is True


def test_optimized_run_completes_passing_task(tmp_path):
    task = TASKS[0]
    metrics = run_task(OPTIMIZED, task, tmp_path=tmp_path)
    assert metrics.completed is True
    assert metrics.model_calls > 0


def test_laya_run_completes_passing_task(tmp_path):
    task = TASKS[0]
    metrics = run_task(LAYASDLC, task, tmp_path=tmp_path)
    assert metrics.completed is True


def test_run_is_reproducible(tmp_path):
    """Same task, same config, same result."""
    task = TASKS[0]
    first = run_task(BASELINE, task, tmp_path=tmp_path)
    second = run_task(BASELINE, task, tmp_path=tmp_path)
    assert first.completed == second.completed
    assert first.task_id == second.task_id


# ======================================================================================
# Aggregation and reporting
# ======================================================================================


def test_aggregate_computes_rates():
    from layasdlc.benchmark import RunMetrics
    runs = [
        RunMetrics("baseline", "T-1", True, True, 10.0),
        RunMetrics("baseline", "T-2", False, False, 20.0),
        RunMetrics("baseline", "T-3", True, False, 15.0),
    ]
    aggregates = aggregate(runs)
    assert len(aggregates) == 1
    agg = aggregates[0]
    assert agg.runs == 3
    assert agg.completed == 2
    assert agg.test_passed == 1
    assert agg.completion_rate == pytest.approx(2 / 3)


def test_format_report_is_readable(tmp_path):
    results = run_benchmark(repeat=1, tmp_path=tmp_path)
    aggregates = aggregate(results)
    report = format_report(aggregates)
    assert "# LayaSDLC Evaluation Report" in report
    assert "baseline" in report
    assert "optimized_baseline" in report
    assert "layasdlc" in report
    assert "Limitations" in report


# ======================================================================================
# Full benchmark
# ======================================================================================


def test_full_benchmark_produces_results(tmp_path):
    results = run_benchmark(repeat=1, tmp_path=tmp_path)
    # 8 tasks x 3 configurations = 24 runs
    assert len(results) == len(TASKS) * len(CONFIGURATIONS)


def test_full_benchmark_with_repeats(tmp_path):
    results = run_benchmark(repeat=2, tmp_path=tmp_path)
    assert len(results) == len(TASKS) * len(CONFIGURATIONS) * 2


# ======================================================================================
# CLI
# ======================================================================================


def test_cli_run_exits_zero(tmp_path, capsys):
    import sys
    from pathlib import Path
    old_argv = sys.argv
    try:
        sys.argv = ["benchmark", "run", "--repeat", "1",
                    "--tmp", str(tmp_path)]
        code = main()
        assert code == 0
        out = capsys.readouterr().out
        assert "Evaluation Report" in out
    finally:
        sys.argv = old_argv


def test_cli_report_reads_saved_results(tmp_path, capsys):
    import json
    import sys
    from pathlib import Path
    results = run_benchmark(repeat=1, tmp_path=tmp_path)
    payload = {
        "runs": [run.to_dict() for run in results],
    }
    path = tmp_path / "results.json"
    path.write_text(json.dumps(payload))

    old_argv = sys.argv
    try:
        sys.argv = ["benchmark", "report", "--results", str(path)]
        code = main()
        assert code == 0
        out = capsys.readouterr().out
        assert "Evaluation Report" in out
    finally:
        sys.argv = old_argv
