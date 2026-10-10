"""Stage 1 feature 6: the deterministic baseline behind the same engine interface."""

from __future__ import annotations

import pytest

from layasdlc import (
    DECISION_SPACE,
    DeterministicEngine,
    EngineFailure,
    EngineRequest,
    score_state,
)
from layasdlc.contracts import DecisionType

ENGINE = DeterministicEngine()

CASES = [
    ("bug_fix", "Fix the NullPointerException when opening the settings page"),
    ("feature", "Add a dark mode toggle to the preferences screen"),
    ("refactor", "Refactor the billing module to extract the invoice formatter"),
    ("testing", "Add unit tests for the timezone conversion helpers"),
    ("documentation", "Update the README with the new install instructions"),
    ("investigation", "Investigate why the nightly sync job intermittently stalls"),
]


def ask(state, decision_type="task_classification", options=None) -> str:
    # Default to the canonical option set for *this* decision type -- sending task
    # options to a workflow question would make the baseline unable to answer.
    if options is None:
        options = DECISION_SPACE[DecisionType(decision_type)]
    request = EngineRequest(
        decision_id="d", task_id="T", decision_type=decision_type,
        allowed_options=tuple(options),
        state=state if isinstance(state, dict) else {"subject": state},
        question="q",
    )
    return ENGINE.decide(request)


@pytest.mark.parametrize("expected,text", CASES)
def test_baseline_classifies_each_of_the_six_kinds(expected, text):
    assert ask(text).selected_option == expected


def test_baseline_is_reproducible_for_identical_input():
    text = "Fix the crash in the export pipeline"
    first, second = ask(text), ask(text)
    assert first.selected_option == second.selected_option
    assert first.confidence == second.confidence


def test_baseline_reads_a_mapping_state_the_same_way_as_flat_text():
    as_dict = {"subject": "Fix the crash", "body": "stack trace shows KeyError in parser"}
    as_text = "Fix the crash stack trace shows KeyError in parser"
    assert score_state(as_dict)["bug_fix"] == score_state(as_text)["bug_fix"]


def test_baseline_abstains_when_there_is_no_signal():
    """No signal must raise, not produce a confident-looking guess."""
    with pytest.raises(EngineFailure, match="no signal"):
        ask("purple elephants_trampoline")


def test_baseline_reports_no_usage_because_it_is_not_a_model():
    answer = ask(CASES[0][1])
    assert answer.usage is None, "a keyword baseline has no tokens to report"
    assert answer.rationale is None


def test_baseline_confidence_is_a_share_not_a_probability():
    answer = ask(CASES[3][1])
    assert answer.confidence is not None
    assert 0.0 <= answer.confidence <= 1.0
    assert answer.confidence >= ENGINE.min_share


def test_baseline_is_marked_available_without_any_probe_cost():
    assert ENGINE.available() is True
    assert ENGINE.name == "deterministic"


def test_repeated_terms_are_capped_so_one_word_cannot_dominate():
    once = score_state("fix the bug")
    repeated = score_state("fix the bug fix the bug fix the bug fix the bug")
    assert repeated["bug_fix"] <= once["bug_fix"] * 3


# --- the other three bounded decision types ---------------------------------------------


def test_workflow_selection_is_derived_from_the_task():
    assert ask("Add unit tests for the parser",
               DecisionType.WORKFLOW_SELECTION.value).selected_option == "run_tests"
    assert ask("Update the README instructions",
               DecisionType.WORKFLOW_SELECTION.value).selected_option == "update_docs"
    assert ask("Fix the crash in the export pipeline",
               DecisionType.WORKFLOW_SELECTION.value).selected_option == "edit_code"


def test_workflow_selection_respects_the_offered_option_set():
    answer = ask("Fix the crash in the export pipeline",
                 DecisionType.WORKFLOW_SELECTION.value,
                 options=("read_investigate", "update_docs"))
    assert answer.selected_option == "read_investigate", \
        "edit_code was not offered, so the baseline must pick an offered option"


def test_retry_vs_escalate_distinguishes_transient_from_persistent():
    transient = ask("The deploy timed out once, a transient network blip",
                    DecisionType.RETRY_VS_ESCALATE.value, options=("retry", "escalate"))
    assert transient.selected_option == "retry"

    persistent = ask("It failed again and still fails on every attempt",
                     DecisionType.RETRY_VS_ESCALATE.value, options=("retry", "escalate"))
    assert persistent.selected_option == "escalate"


def test_retry_vs_escalate_biases_to_safety_when_it_cannot_tell():
    answer = ask("something vague happened", DecisionType.RETRY_VS_ESCALATE.value,
                 options=("retry", "escalate"))
    assert answer.selected_option == "escalate"


def test_context_priority_maps_ambiguity_to_high_and_locality_to_low():
    high = ask("unclear why this regression started in production",
               DecisionType.CONTEXT_PRIORITY.value, options=("high", "medium", "low"))
    assert high.selected_option == "high"

    low = ask("fix this obvious typo in the readme comment",
              DecisionType.CONTEXT_PRIORITY.value, options=("high", "medium", "low"))
    assert low.selected_option == "low"

    mid = ask("adjust the invoice rounding rule",
              DecisionType.CONTEXT_PRIORITY.value, options=("high", "medium", "low"))
    assert mid.selected_option == "medium"
