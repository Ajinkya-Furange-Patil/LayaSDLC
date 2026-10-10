"""Structured engineering questions: one bounded question per decision type.

Stage 2 requirement 1 asks the controller to pose structured questions; this
module owns their wording and the per-option descriptions handed to the model.

The shape produced for a Laya-style engine is the verified ``system_one``
contract: ``{"type": "choice", "instructions": ..., "criteria": {option: desc}}``,
with ``type`` restricted to ``choice``/``score``/``noul``. That contract was
confirmed against a live ``POST /v1/systemone`` before this file was written
(see docs/adr/0002-laya-inference-path.md).

Descriptions are written to be discriminative rather than flattering: each says
when the option does *not* apply, which is what stops a classifier from
collapsing everything onto one label.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .contracts import DECISION_SPACE, DecisionType, TaskState

#: The question text for each decision type. ``state`` refers to the payload.
INSTRUCTIONS: Mapping[DecisionType, str] = {
    DecisionType.TASK_CLASSIFICATION: (
        "Classify the engineering task described in `state`."
    ),
    DecisionType.WORKFLOW_SELECTION: (
        "Given the task in `state`, select the single next workflow step to take."
    ),
    DecisionType.RETRY_VS_ESCALATE: (
        "The last attempt on `state` did not succeed. Should the next attempt retry "
        "the same approach, or escalate to a human?"
    ),
    DecisionType.CONTEXT_PRIORITY: (
        "How much surrounding context should be gathered before acting on `state`?"
    ),
}

#: Per-option descriptions. Keys must match DECISION_SPACE exactly -- asserted by tests.
OPTION_DESCRIPTIONS: Mapping[DecisionType, Mapping[str, str]] = {
    DecisionType.TASK_CLASSIFICATION: {
        "bug_fix": "Repair behavior that is currently broken: errors, crashes, "
                   "regressions, wrong results. Not for missing capability.",
        "feature": "Add capability that does not exist yet. Not for repairing "
                   "existing behavior.",
        "refactor": "Change structure with no behavior change: rename, extract, "
                    "move, re-typed. Not for fixing a defect.",
        "testing": "The deliverable is the test itself: new tests, fixtures, "
                   "coverage. Not for changing product code.",
        "documentation": "The deliverable is prose: README, docstrings, ADRs, "
                         "changelogs, examples. Not for changing code behavior.",
        "investigation": "Research with no intended code change: find a cause, "
                         "compare options, measure, answer a question.",
    },
    DecisionType.WORKFLOW_SELECTION: {
        "edit_code": "Change product source code. Requires write permission on "
                     "the target paths.",
        "run_tests": "Execute the test suite to gather evidence. Requires "
                     "permission to run commands.",
        "read_investigate": "Read and inspect only; no mutation of any kind.",
        "update_docs": "Edit documentation files only.",
    },
    DecisionType.RETRY_VS_ESCALATE: {
        "retry": "Attempt the same approach again -- appropriate for a transient "
                 "failure such as a timeout or rate limit.",
        "escalate": "Stop and hand to a human -- appropriate for a repeated "
                    "failure, a destructive request, or missing permissions.",
    },
    DecisionType.CONTEXT_PRIORITY: {
        "high": "Gather broadly before acting; the task is ambiguous or "
                "high-blast-radius.",
        "medium": "Gather the immediately related files; the task is well scoped.",
        "low": "Almost no gathering needed; the change is local and obvious.",
    },
}


def question_for(decision_type: str, allowed_options: Sequence[str]) -> dict[str, Any]:
    """Build the Laya-shaped question payload for one bounded decision.

    Only the requested options appear as criteria, so the model's answer space is
    exactly the caller's ``allowed_options`` -- narrowing the question and the
    validation agree by construction.
    """
    dtype = DecisionType(decision_type)
    descriptions = OPTION_DESCRIPTIONS[dtype]
    return {
        "selection": {
            "type": "choice",
            "instructions": INSTRUCTIONS[dtype],
            "criteria": {option: descriptions[option] for option in allowed_options},
        }
    }


def prompt_state(state: TaskState) -> dict[str, Any]:
    """Render a :class:`TaskState` as the JSON-ish state an engine consumes."""
    return state.as_prompt_state()


def canonical_options(decision_type: str) -> tuple[str, ...]:
    """The full option set for a decision type, from the registry."""
    return DECISION_SPACE[DecisionType(decision_type)]
