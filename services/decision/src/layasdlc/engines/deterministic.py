"""Deterministic keyword baseline (Stage 1 feature 6, Stage 2 requirement 7).

Serves two roles behind the *same* interface as Laya:

* **fallback** -- when the model times out, fails validation or abstains;
* **comparison baseline** -- feature 6 requires a deterministic router to
  measure the model against.

Properties that make it fit both:

* no network, no model, no randomness: identical input gives identical output;
* it abstains (raises :class:`EngineFailure`) rather than inventing an option
  when there is no signal, so the controller records ``FAILED``/``ABSTAIN``
  instead of a confident guess;
* confidence is ``top_score / total_score`` -- a *share*, not a calibrated
  probability. It is labelled as such everywhere it surfaces, because comparing
  it to Laya's calibrated confidence without saying so would be misleading.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

from ..contracts import DECISION_SPACE, DecisionType, TaskKind
from ..engine import EngineAnswer, EngineRequest
from ..errors import EngineFailure

_STRONG, _MEDIUM, _WEAK = 3.0, 2.0, 1.0

#: Keyword tables for task classification: (regex, weight).
TASK_TERMS: Mapping[TaskKind, tuple[tuple[str, float], ...]] = {
    TaskKind.BUG_FIX: (
        (r"\b(bug|fix(?:es|ed|ing)?|broken|crash(?:es|ed|ing)?|error|exception|traceback)\b", _STRONG),
        (r"\b(regression|reproduce|repro|stack ?trace|segfault|500|404|race condition)\b", _STRONG),
        (r"\b(fails?|failing|failed|not working|incorrect|wrong output)\b", _MEDIUM),
        (r"\b(leak|deadlock|hang|freeze|memory leak|null pointer|typeerror|keyerror)\b", _MEDIUM),
    ),
    TaskKind.FEATURE: (
        (r"\b(add(?:s|ed|ing)?|implement(?:s|ed|ing)?|create(?:s|d|ing)?)\b", _STRONG),
        (r"\b(feature|support for|endpoint|flag|option|toggle|capability)\b", _STRONG),
        # "new" alone is weak -- it also appears in doc updates
        # ("the new install instructions"), where documentation must win.
        (r"\b(new|should be able to|would like to|need(?:s)? a way|let users)\b", _MEDIUM),
    ),
    TaskKind.REFACTOR: (
        (r"\brefactor(?:ing|ed|s)?\b", _STRONG),
        (r"\b(rename(?:s|d|ing)?|extract(?:s|ed|ing)?|restructure)\b", _STRONG),
        (r"\b(cleanup|clean up|tidy|reorgani[sz]e|decouple|tech debt)\b", _MEDIUM),
        (r"\b(no behavior change|same behavior|without changing|simplify)\b", _MEDIUM),
    ),
    TaskKind.TESTING: (
        (r"\b(test(?:s|ing|ed)?|unit test|integration test|e2e)\b", _STRONG),
        # "add unit tests" also fires the generic feature signal ("add"), so this
        # needs its own weight or the two classes tie and order decides the winner.
        (r"\b(?:add|write|create)\s+(?:unit\s+|integration\s+)?tests?\b", _STRONG),
        (r"\b(coverage|fixture(?:s)?|assert(?:ions)?|pytest|jest|flaky)\b", _STRONG),
        (r"\b(add a test|write tests?|test suite|regression test|untested)\b", _MEDIUM),
    ),
    TaskKind.DOCUMENTATION: (
        (r"\b(docs?|documentation|readme|docstring(?:s)?)\b", _STRONG),
        (r"\b(comment(?:s)?|changelog|release notes|guide(?:s)?|tutorial)\b", _STRONG),
        (r"\b(document(?:s|ing)?|annotate)\b", _MEDIUM),
    ),
    TaskKind.INVESTIGATION: (
        (r"\b(investigat(?:e|ion|ing)|why is|find out|determine (why|how|whether))\b", _STRONG),
        (r"\b(research|compare|evaluation|benchmark|measure|analy[sz]e)\b", _STRONG),
        (r"\b(diagnos(?:e|is|ing)|root cause|track down|locate|figure out|audit)\b", _MEDIUM),
    ),
}

_TASK_PATTERNS: dict[TaskKind, tuple[tuple[re.Pattern[str], float], ...]] = {
    # IGNORECASE matters: request text is prose, so "Fix the crash" and "README"
    # must match the same as "fix the crash" and "readme". Without it the
    # baseline silently abstained on any capitalised keyword.
    kind: tuple((re.compile(pattern, re.IGNORECASE), weight) for pattern, weight in entries)
    for kind, entries in TASK_TERMS.items()
}

#: Which workflow step a task most naturally implies, best option first.
_TASK_TO_WORKFLOW: Mapping[TaskKind, tuple[str, ...]] = {
    TaskKind.BUG_FIX: ("edit_code", "run_tests", "read_investigate"),
    TaskKind.FEATURE: ("edit_code", "run_tests", "read_investigate"),
    TaskKind.REFACTOR: ("edit_code", "run_tests", "read_investigate"),
    TaskKind.TESTING: ("run_tests", "edit_code", "read_investigate"),
    TaskKind.DOCUMENTATION: ("update_docs", "read_investigate", "edit_code"),
    TaskKind.INVESTIGATION: ("read_investigate", "run_tests", "update_docs"),
}

_TRANSIENT = re.compile(
    r"\b(timeout|timed out|rate limit(?:ed)?|429|flaky|intermittent|transient|"
    r"network (?:glitch|error|blip)|temporary)\b", re.I)
_PERSISTENT = re.compile(
    r"\b(again|still fail(?:ing|s|ed)|repeatedly|third time|every time|permission denied|"
    r"blocked|consistently|persistent|keeps? happening)\b", re.I)

_HIGH_CONTEXT = re.compile(
    r"\b(unclear|ambiguous|vague|unknown|investigat\w*|why|regression|production|prod)\b", re.I)
_LOW_CONTEXT = re.compile(
    r"\b(typo|renam\w+|comment|obvious|single file|one line|trivial|readme)\b", re.I)


def _flatten(state: Any) -> str:
    if isinstance(state, str):
        return state
    if isinstance(state, Mapping):
        return " ".join(_flatten(value) for value in state.values())
    if isinstance(state, (list, tuple)):
        return " ".join(_flatten(item) for item in state)
    return "" if state is None else str(state)


def score_state(state: Any) -> dict[str, float]:
    """Score every task kind against the state. Exposed for benchmarking."""
    text = _flatten(state)
    scores: dict[str, float] = {}
    for kind, entries in _TASK_PATTERNS.items():
        total = 0.0
        for pattern, weight in entries:
            hits = len(pattern.findall(text))
            if hits:
                # Cap repeats so one repeated word cannot dominate the ranking.
                total += weight * min(hits, 3)
        scores[kind.value] = total
    return scores


def _winning_task(state: Any) -> tuple[Optional[str], float, dict[str, float]]:
    scores = score_state(state)
    total = sum(scores.values())
    if total <= 0:
        return None, 0.0, scores
    winner, top = max(scores.items(), key=lambda item: item[1])
    return winner, top / total, scores


class DeterministicEngine:
    """Keyword baseline satisfying :class:`layasdlc.engine.DecisionEngine`."""

    name = "deterministic"
    version = "keyword-baseline-1"
    #: Below this share of the winning signal the baseline abstains.
    min_share: float = 0.40

    def available(self) -> bool:
        """Always: no dependencies, no network, no weights."""
        return True

    def decide(self, request: EngineRequest) -> EngineAnswer:
        text = _flatten(request.state)
        task, share, scores = _winning_task(request.state)

        option, confidence = self._select(request.decision_type, task, share, text, request)
        if option is None:
            raise EngineFailure(
                f"deterministic baseline found no signal for {request.decision_type!r}"
            )

        return EngineAnswer(
            selected_option=option,
            confidence=round(confidence, 6),
            # The baseline never produces prose; leaving this None is the honest value.
            rationale=None,
            model=self.name,
            model_version=self.version,
            latency_ms=0.0,
            usage=None,  # it is not a model: there are no tokens to report
            probabilities={option: round(confidence, 6)},
            raw={"scores": scores, "share": share} if scores else {},
        )

    # --- per-decision-type derivations --------------------------------------------------

    def _select(self, decision_type: str, task: Optional[str], share: float,
                text: str, request: EngineRequest) -> tuple[Optional[str], float]:
        allowed = tuple(request.allowed_options)
        canonical = DECISION_SPACE.get(DecisionType(decision_type), ())

        if decision_type == DecisionType.TASK_CLASSIFICATION.value:
            if task is None or share < self.min_share:
                return None, 0.0
            return _pick(task, allowed, canonical), share

        if decision_type == DecisionType.WORKFLOW_SELECTION.value:
            if task is None or share < self.min_share:
                return None, 0.0
            for candidate in _TASK_TO_WORKFLOW[TaskKind(task)]:
                if candidate in allowed:
                    # Confidence comes from the underlying task signal, discounted
                    # because this is a derived answer rather than a direct one.
                    return candidate, share * 0.9
            return None, 0.0

        if decision_type == DecisionType.RETRY_VS_ESCALATE.value:
            if _PERSISTENT.search(text):
                candidate, confidence = "escalate", 0.7
            elif _TRANSIENT.search(text):
                candidate, confidence = "retry", 0.7
            else:
                # Unknown failure mode: bias to the safe branch.
                candidate, confidence = "escalate", 0.5
            return _pick(candidate, allowed, canonical), confidence

        if decision_type == DecisionType.CONTEXT_PRIORITY.value:
            if _HIGH_CONTEXT.search(text):
                candidate, confidence = "high", 0.6
            elif _LOW_CONTEXT.search(text):
                candidate, confidence = "low", 0.6
            else:
                candidate, confidence = "medium", 0.5
            return _pick(candidate, allowed, canonical), confidence

        return None, 0.0


def _pick(candidate: str, allowed: Sequence[str], canonical: Sequence[str]) -> str:
    """Return ``candidate`` if permitted, else the earliest canonical option that is."""
    if candidate in allowed:
        return candidate
    for option in canonical:
        if option in allowed:
            return option
    return allowed[0] if allowed else candidate
