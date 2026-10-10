"""Contract parity: the Python and TypeScript representations must not drift.

OpenCode speaks TypeScript and the decision service speaks Python, so
``packages/contracts/src/decision.ts`` is a *mirror* of ``contracts.py``. A
mirror that can silently diverge is worse than no mirror at all, because the
caller would keep typing against a shape the service no longer produces.

This module compares them mechanically: same field names, in the same order,
plus the same schema version, enum values and decision space.
"""

from __future__ import annotations

import re
from dataclasses import asdict, fields
from pathlib import Path

import pytest

from layasdlc.contracts import (
    DECISION_SPACE,
    SCHEMA_VERSION,
    Action,
    ControllerResult,
    DecisionEnvelope,
    DecisionType,
    Evidence,
    GateState,
    Outcome,
    SafetyClass,
    TaskKind,
    TaskState,
    Usage,
    VerificationState,
)

#: services/decision/tests/this_file.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
TS_SOURCE = REPO_ROOT / "packages" / "contracts" / "src" / "decision.ts"
TS_CONTROLLER = REPO_ROOT / "services" / "decision" / "src" / "layasdlc" / "controller.py"


@pytest.fixture(scope="module")
def ts_text() -> str:
    if not TS_SOURCE.is_file():
        pytest.skip(
            f"TypeScript boundary not present at {TS_SOURCE.relative_to(REPO_ROOT)}; "
            "clone the full repository to run contract-parity checks"
        )
    return TS_SOURCE.read_text(encoding="utf-8")


def ts_interface_fields(text: str, interface: str) -> list[str]:
    match = re.search(rf"export interface {interface} \{{(.*?)\n\}}", text, re.S)
    assert match, f"interface {interface} not found in {TS_SOURCE.name}"
    return re.findall(r"^\s*(\w+)\??:", match.group(1), re.M)


def py_interface_fields(cls) -> list[str]:
    return [f.name for f in fields(cls)]


# --- structural parity ------------------------------------------------------------------


def test_decision_envelope_fields_match_in_name_and_order(ts_text):
    assert py_interface_fields(DecisionEnvelope) == ts_interface_fields(
        ts_text, "DecisionEnvelope"
    ), "DecisionEnvelope drifted: Python and TypeScript describe different fields"


def test_controller_result_fields_match_in_name_and_order(ts_text):
    assert py_interface_fields(ControllerResult) == ts_interface_fields(
        ts_text, "ControllerResult"
    ), "ControllerResult drifted"


def test_usage_fields_match_in_name_and_order(ts_text):
    assert py_interface_fields(Usage) == ts_interface_fields(ts_text, "Usage")


def test_task_state_fields_match_in_name_and_order(ts_text):
    assert py_interface_fields(TaskState) == ts_interface_fields(ts_text, "TaskState")


def test_evidence_fields_match_in_name_and_order(ts_text):
    assert py_interface_fields(Evidence) == ts_interface_fields(ts_text, "Evidence")


def test_usage_serialisation_paths_agree():
    """Usage has two serialisers (``to_dict`` and ``asdict``); they must not diverge.

    ``DecisionEnvelope.to_dict()`` serialises ``usage`` via ``asdict``, while
    callers use ``to_dict()`` directly. If the two ever disagreed, the same
    object would arrive on the wire as two different shapes depending on which
    route it took -- the kind of drift a mirror exists to prevent.
    """
    empty, filled = Usage(), Usage(input_tokens=7, output_tokens=0)

    assert list(empty.to_dict()) == py_interface_fields(Usage)
    assert list(asdict(empty)) == py_interface_fields(Usage)
    assert list(filled.to_dict()) == list(asdict(filled))
    assert filled.to_dict() == {"input_tokens": 7, "output_tokens": 0}
    assert empty.to_dict() == {"input_tokens": None, "output_tokens": None}, \
        "absent usage must serialise as null, never as 0"


# --- schema version ---------------------------------------------------------------------


def test_schema_version_is_identical_on_both_sides(ts_text):
    match = re.search(r'export const SCHEMA_VERSION = "([^"]+)"', ts_text)
    assert match, "SCHEMA_VERSION not declared in the TypeScript contract"
    assert match.group(1) == SCHEMA_VERSION


# --- enum parity -------------------------------------------------------------------------


def _ts_const_array(text: str, name: str) -> list[str]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", text, re.S)
    assert match, f"export const {name} not found in {TS_SOURCE.name}"
    return re.findall(r'"([^"]+)"', match.group(1))


@pytest.mark.parametrize(
    "python_enum,ts_name",
    [
        (DecisionType, "DECISION_TYPES"),
        (TaskKind, "TASK_KINDS"),
        (GateState, "GATE_STATES"),
        (Outcome, "OUTCOMES"),
        (Action, "ACTIONS"),
        (SafetyClass, "SAFETY_CLASSES"),
        (VerificationState, "VERIFICATION_STATES"),
    ],
)
def test_enum_members_match(ts_text, python_enum, ts_name):
    expected = [member.value for member in python_enum]
    assert _ts_const_array(ts_text, ts_name) == expected, (
        f"{ts_name} drifted: TypeScript and {python_enum.__name__} disagree"
    )


def test_decision_source_vocabulary_matches_what_the_controller_can_produce(ts_text):
    """``source`` is how 'did the real model answer?' is answered, so it must match."""
    declared = _ts_const_array(ts_text, "SOURCES")
    # The controller has exactly three return sites for source. If a fourth is
    # added, this fails until the TypeScript side learns about it too.
    controller_src = TS_CONTROLLER.read_text(encoding="utf-8") if TS_CONTROLLER.is_file() else ""
    produced = {
        literal
        for literal in re.findall(r'"(engine|fallback|policy)"', controller_src)
    }
    assert produced, "could not find source literals in controller.py"
    assert produced == set(declared), (
        f"controller produces {sorted(produced)} but TypeScript declares {declared}"
    )


# --- decision space ----------------------------------------------------------------------


def _ts_decision_space(text: str) -> dict[str, list[str]]:
    match = re.search(r"DECISION_SPACE[^=]*=\s*\{(.*?)\n\};", text, re.S)
    assert match, "DECISION_SPACE not found in the TypeScript contract"
    return {
        key: re.findall(r'"([^"]+)"', values)
        for key, values in re.findall(r"(\w+)\s*:\s*\[([^\]]*)\]", match.group(1), re.S)
    }


def test_decision_space_is_identical_on_both_sides(ts_text):
    python_space = {kind.value: list(options) for kind, options in DECISION_SPACE.items()}
    assert _ts_decision_space(ts_text) == python_space


def test_every_decision_type_has_a_canonical_option_set():
    """Both sides rely on this being total; a gap would fail open."""
    for kind in DecisionType:
        assert DECISION_SPACE[kind], f"{kind.value} has no canonical options"
