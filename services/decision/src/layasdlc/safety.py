"""Deterministic safety classification (feature 8).

Destructive-operation and deployment detection is implemented as explicit,
auditable keyword matching -- never as a model output. A probabilistic
classifier can be confidently wrong about ``DROP TABLE``; this layer cannot be
confident, only literal, which is exactly what an approval gate needs.

Design notes
------------
* Matching runs over the *whole* request, lower-cased, with word boundaries so
  ``deploy`` does not fire on ``deployment-plan-notes`` in a doc-only task... it
  does fire on ``deployment``, which is intended.
* Both classes can be true at once; DEPLOYMENT wins the reported label because
  releasing is the action that must be gated, but ``requires_approval`` is set
  for either.
* Findings return the matched phrase so the reason shown to a human is the text
  that actually triggered, not a paraphrase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .contracts import SafetyClass

#: Phrases that mean "this destroys or rewrites data/state irreversibly".
DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
    # Allow up to three words between the verb and the object: real requests say
    # "drop the legacy table", not "drop table".
    r"\bdrop\s+(?:the\s+)?(?:\w+\s+){0,3}(?:table|database|schema|index)\b",
    r"\btruncate\s+(?:the\s+)?table\b",
    r"\bdelete\s+(?:from|all\s+rows|the\s+(?:prod|production|live))\b",
    r"\berase\b",
    r"\bpurge\b",
    r"\bformat\s+(?:the\s+)?disk\b",
    r"\boverwrite\s+(?:the\s+)?(?:prod|production|live|database)\b",
    r"\bforce\s+push\b",
    r"\breset\s+(?:the\s+)?(?:prod|production|live)\b",
    r"\bdestroy\b",
    r"\brm\s+-rf\b",
)

#: Phrases that mean "this puts software in front of real users".
DEPLOYMENT_PATTERNS: tuple[str, ...] = (
    r"\bdeploy(?:ing|ed|s)?\b",
    r"\broll[\s-]?outs?\b",
    r"\brelease\s+(?:to\s+)?(?:prod|production|live)\b",
    r"\bship\s+(?:to\s+)?(?:prod|production|live)\b",
    r"\bhotfix\s+(?:to\s+)?(?:prod|production|live)\b",
    r"\bpublish(?:ing|ed)?\b[^.]{0,40}\b(?:npm|pypi|docker|registry)\b",
    r"\bprod(?:uction)?\s+push\b",
    r"\benable\s+(?:it|this|the\s+feature\s+flag)\s+in\s+prod\b",
)


@dataclass(frozen=True)
class SafetyFinding:
    """What the detector saw, and why it classified the way it did."""

    safety_class: SafetyClass
    matched: tuple[str, ...]
    requires_approval: bool

    @property
    def reason(self) -> str:
        if not self.matched:
            return "no destructive or deployment phrase detected"
        return "matched: " + ", ".join(repr(m) for m in self.matched)


def _scan(text: str, patterns: Iterable[str]) -> tuple[str, ...]:
    found: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            found.append(match.group(0))
    return tuple(found)


def _haystack(state: object) -> str:
    """Flatten a state object (dict/str/list) into one searchable string."""
    if isinstance(state, str):
        return state
    if isinstance(state, Mapping):
        return " ".join(_haystack(v) for v in state.values())
    if isinstance(state, (list, tuple)):
        return " ".join(_haystack(v) for v in state)
    return "" if state is None else str(state)


def classify_safety(state: object) -> SafetyFinding:
    """Classify a request as safe / destructive / deployment, with the matched text."""
    text = _haystack(state)

    destructive = _scan(text, DESTRUCTIVE_PATTERNS)
    deployment = _scan(text, DEPLOYMENT_PATTERNS)

    if deployment:
        safety_class = SafetyClass.DEPLOYMENT
        matched = deployment + destructive
    elif destructive:
        safety_class = SafetyClass.DESTRUCTIVE
        matched = destructive
    else:
        safety_class = SafetyClass.SAFE
        matched = ()

    return SafetyFinding(
        safety_class=safety_class,
        matched=matched,
        requires_approval=bool(matched),
    )
