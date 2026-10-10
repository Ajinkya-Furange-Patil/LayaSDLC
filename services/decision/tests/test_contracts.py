"""Stage 1: typed task/decision contracts import cleanly. Stage 2: schema shape."""

from __future__ import annotations

import json

import pytest

import layasdlc
from layasdlc import (
    DECISION_SPACE,
    SCHEMA_VERSION,
    DecisionEnvelope,
    DecisionType,
    TaskKind,
    Usage,
)


def test_package_exports_its_documented_surface():
    missing = [name for name in layasdlc.__all__ if not hasattr(layasdlc, name)]
    assert missing == [], f"__all__ names that do not exist: {missing}"


def test_schema_version_is_declared_and_semver_shaped():
    # Shape first: a version that stops looking like "major.minor" means the
    # scheme itself changed, which is a bigger event than a field being added.
    assert SCHEMA_VERSION.count(".") == 1
    major, minor = SCHEMA_VERSION.split(".")
    assert major.isdigit() and minor.isdigit()
    # 1.1 added DecisionEnvelope.alternatives (additive, nullable). Bumping this
    # literal should be a deliberate act of noticing a schema change, so the
    # value is pinned rather than inferred.
    assert SCHEMA_VERSION == "1.1"


def test_exactly_four_bounded_decision_types():
    assert [d.value for d in DecisionType] == [
        "task_classification", "workflow_selection", "retry_vs_escalate", "context_priority",
    ]


def test_every_decision_type_has_a_non_empty_option_set():
    assert set(DECISION_SPACE) == set(DecisionType)
    for dtype, options in DECISION_SPACE.items():
        assert options, f"{dtype} has no options"
        assert len(set(options)) == len(options), f"{dtype} has duplicate options"


def test_task_classification_is_exactly_the_six_required_kinds():
    assert DECISION_SPACE[DecisionType.TASK_CLASSIFICATION] == tuple(
        k.value for k in TaskKind
    )


def test_workflow_options_are_the_tool_identifiers():
    # permissions.py gates these by name; renaming them silently would break that.
    assert set(DECISION_SPACE[DecisionType.WORKFLOW_SELECTION]) == {
        "edit_code", "run_tests", "read_investigate", "update_docs",
    }


def test_usage_distinguishes_absent_tokens_from_zero():
    empty = Usage()
    assert empty.available is False
    assert empty.total is None, "unmeasured usage must not read as 0 tokens"

    zero = Usage(input_tokens=0, output_tokens=0)
    assert zero.available is True
    assert zero.total == 0


def test_usage_coerces_garbage_to_none_rather_than_zero():
    assert Usage.from_mapping(None).input_tokens is None
    assert Usage.from_mapping({"input_tokens": "not-a-number"}).input_tokens is None
    assert Usage.from_mapping({"input_tokens": True}).input_tokens is None  # bool is not a count
    assert Usage.from_mapping({"input_tokens": "12"}).input_tokens == 12


def _envelope() -> DecisionEnvelope:
    return DecisionEnvelope(
        schema_version=SCHEMA_VERSION,
        decision_id="d1",
        task_id="T-1",
        decision_type="task_classification",
        allowed_options=("bug_fix", "feature"),
        selected_option="bug_fix",
        confidence=0.81,
        rationale=None,
        model="laya",
        model_version="0.3.4",
        latency_ms=12.5,
        usage=Usage(input_tokens=120, output_tokens=0),
    )


def test_envelope_serialises_to_json_with_list_options():
    payload = json.loads(json.dumps(_envelope().to_dict()))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["allowed_options"] == ["bug_fix", "feature"]
    assert payload["rationale"] is None, "absent rationale must round-trip as null"
    assert payload["usage"] == {"input_tokens": 120, "output_tokens": 0}


def test_envelope_exposes_task_kind_only_for_classification():
    assert _envelope().task_kind is TaskKind.BUG_FIX

    workflow = DecisionEnvelope(
        schema_version=SCHEMA_VERSION, decision_id="d2", task_id="T-1",
        decision_type="workflow_selection", allowed_options=("run_tests",),
        selected_option="run_tests", confidence=0.7, rationale=None,
        model=None, model_version=None, latency_ms=None, usage=None,
    )
    assert workflow.task_kind is None, "a workflow choice is not a TaskKind"
