"""Typed contracts: task vocabulary, the decision envelope, and supporting models.

This module is the vocabulary shared by the controller, the engine adapters and
the OpenCode-facing boundary. It performs no I/O and imports nothing heavy, so
TypeScript-side contract tests and Python unit tests can both load it cheaply.

Two families live here:

* **Task contracts** -- :class:`TaskKind`, :class:`Decision` and the supporting
  enums describing how a routing verdict was reached (gate state, outcome,
  safety class, verification state).
* **Decision schema** (:data:`SCHEMA_VERSION`, :class:`DecisionEnvelope`) -- the
  versioned, validated payload an engine must return. Stage 2 requirement 3.

Not every field is always meaningful. ``confidence`` and ``rationale`` are
nullable *by design*: Laya reports calibrated probabilities but never generates
text, so a rationale is only populated by engines that actually support one.
Populating it because a caller expects it would be inventing data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

#: Version of the decision schema. Bump the minor for additive changes, the
#: major when a field is removed or its meaning changes. Persisted with every
#: envelope so an old record can still be read later.
SCHEMA_VERSION = "1.0"


# ======================================================================================
# Bounded decision types (Stage 2 requirement 4)
# ======================================================================================


class DecisionType(str, Enum):
    """The four bounded decision spaces supported in this stage.

    Every engine answers exactly one of these. The set is closed on purpose: an
    engine asked for anything else is rejected before it is called, and an
    answer outside the caller's option list is rejected after.
    """

    TASK_CLASSIFICATION = "task_classification"
    WORKFLOW_SELECTION = "workflow_selection"
    RETRY_VS_ESCALATE = "retry_vs_escalate"
    CONTEXT_PRIORITY = "context_priority"


#: Canonical option set per decision type. A caller may narrow this (pass a
#: subset) but may never widen it -- widening would let a request introduce an
#: option the type does not define, which is exactly the out-of-scope case the
#: validator exists to catch.
DECISION_SPACE: Mapping[DecisionType, tuple[str, ...]] = {
    DecisionType.TASK_CLASSIFICATION: (
        "bug_fix", "feature", "refactor", "testing", "documentation", "investigation",
    ),
    # Workflow options double as tool identifiers, which is what lets
    # layasdlc.permissions gate them independently of the model.
    DecisionType.WORKFLOW_SELECTION: (
        "edit_code", "run_tests", "read_investigate", "update_docs",
    ),
    DecisionType.RETRY_VS_ESCALATE: ("retry", "escalate"),
    DecisionType.CONTEXT_PRIORITY: ("high", "medium", "low"),
}


# ======================================================================================
# Task vocabulary
# ======================================================================================


class TaskKind(str, Enum):
    """The six bounded engineering task classes (Stage 1 feature 1)."""

    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    INVESTIGATION = "investigation"

    @classmethod
    def parse(cls, value: str) -> "TaskKind":
        """Resolve a raw string into a member, tolerating case/whitespace drift."""
        raw = (value or "").strip().lower()
        for member in cls:
            if raw == member.value:
                return member
        raise ValueError(f"unknown task kind {value!r}; expected one of {[m.value for m in cls]}")


class GateState(str,Enum):
    """Confidence-gate outcome.

    These three names mirror ``laya.confidence.GATE_STATES`` exactly, which
    deliberately has no "gate was not configured" member. We represent the
    unconfigured case as ``None`` rather than inventing a fourth value.
    """

    PASSED = "passed"
    ABSTAINED = "abstained"
    UNEVALUATED = "unevaluated"


class Outcome(str, Enum):
    """What the controller ended up doing with a request."""

    DECIDED = "decided"      # engine answered, validation passed, gate accepted
    FALLBACK = "fallback"    # engine failed/abstained, deterministic baseline answered
    REJECTED = "rejected"    # answer was malformed, unsupported or out of scope
    FAILED = "failed"        # timeout / transport failure with no usable fallback


class Action(str, Enum):
    """Routing instruction only. Nothing is executed by this service (Stage 1 feature 4)."""

    PROCEED = "proceed"
    INVESTIGATE = "investigate"
    ESCALATE = "escalate"
    ABSTAIN = "abstain"


class SafetyClass(str, Enum):
    SAFE = "safe"
    DESTRUCTIVE = "destructive"
    DEPLOYMENT = "deployment"


class VerificationState(str, Enum):
    """Whether a claimed result is backed by test evidence (Stage 1 feature 7)."""

    UNVERIFIED = "unverified"
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"


# ======================================================================================
# Supporting value objects
# ======================================================================================


@dataclass(frozen=True)
class Usage:
    """Token accounting, present only when the engine actually reported it.

    Absent counters stay ``None``. They are never defaulted to ``0``, because a
    stored ``0`` reads as "this was free" rather than "this was not measured".
    """

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

    @property
    def available(self) -> bool:
        return self.input_tokens is not None or self.output_tokens is not None

    @property
    def total(self) -> Optional[int]:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    @classmethod
    def from_mapping(cls, raw: Any) -> "Usage":
        if not isinstance(raw, Mapping):
            return cls()
        return cls(input_tokens=_as_optional_int(raw.get("input_tokens")),
                   output_tokens=_as_optional_int(raw.get("output_tokens")))

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form for logs and API responses.

        The key set is deliberately identical to ``dataclasses.asdict(self)``,
        because ``DecisionEnvelope.to_dict()`` serialises ``usage`` that way.
        Two serialization paths that disagree would let the same object arrive
        on the wire as two different shapes depending on the route it took.

        Absent counters serialise as ``null`` (a real "not measured"), never as
        ``0`` (which would read as "cost nothing"). ``available`` remains a
        derived property rather than a stored field, so it is not repeated here.
        """
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass(frozen=True)
class Alternative:
    """One candidate option and its probability, best first."""

    option: str
    probability: float


@dataclass(frozen=True)
class Evidence:
    """Test evidence backing a success claim.

    ``tests_passed`` alone is never enough: :meth:`Decision.evidence_state` also
    requires a recorded command, so "we think it works" cannot read as passed.
    """

    test_command: str
    tests_passed: bool
    artifact: Optional[str] = None
    checked_at: Optional[str] = None

    @classmethod
    def record(cls, test_command: str, tests_passed: bool,
               artifact: Optional[str] = None) -> "Evidence":
        return cls(test_command=test_command, tests_passed=tests_passed,
                   artifact=artifact, checked_at=utc_now())


# ======================================================================================
# Versioned decision schema (Stage 2 requirement 3)
# ======================================================================================


@dataclass(frozen=True)
class DecisionEnvelope:
    """A validated decision returned by an engine.

    Field policy, per Stage 2 requirement 3:

    * ``confidence`` -- ``None`` when the engine reports no meaningful
      probability. Laya does report one, so the Laya adapters fill it.
    * ``rationale`` -- ``None`` unless the engine can genuinely produce one.
      Laya never generates text, so :class:`~layasdlc.engines.laya_http.LayaHttpEngine`
      always leaves this ``None`` rather than synthesising a sentence.
    * ``latency_ms`` / ``usage`` -- ``None`` when not measurable.
    """

    schema_version: str
    decision_id: str
    task_id: str
    decision_type: str
    allowed_options: tuple[str, ...]
    selected_option: str
    confidence: Optional[float]
    rationale: Optional[str]
    model: Optional[str]
    model_version: Optional[str]
    latency_ms: Optional[float]
    usage: Optional[Usage]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_options"] = list(self.allowed_options)
        if self.usage is not None:
            payload["usage"] = asdict(self.usage)
        return payload

    @property
    def task_kind(self) -> Optional[TaskKind]:
        """Convenience view: the envelope as a :class:`TaskKind`, if it maps to one."""
        if self.decision_type != DecisionType.TASK_CLASSIFICATION.value:
            return None
        try:
            return TaskKind.parse(self.selected_option)
        except ValueError:
            return None


def _as_optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ======================================================================================
# Controller-level contracts
# ======================================================================================


@dataclass(frozen=True)
class TaskState:
    """What is being decided about (Stage 1: task state model)."""

    task_id: str
    subject: str
    body: str = ""
    path: Optional[str] = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def as_prompt_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {"task_id": self.task_id, "subject": self.subject,
                                 "body": self.body}
        if self.path:
            state["path"] = self.path
        if self.context:
            state["context"] = dict(self.context)
        return state


@dataclass(frozen=True)
class ControllerResult:
    """What the workflow controller returns: a decision plus how it was reached."""

    envelope: Optional[DecisionEnvelope]
    outcome: Outcome
    action: Action
    gate: Optional[GateState]
    threshold: Optional[float]
    engine: str
    source: str                      # "engine" | "fallback" | "policy"
    safety_class: SafetyClass
    requires_approval: bool
    approval_reason: Optional[str]
    latency_ms: float
    error: Optional[str] = None
    tool: Optional[str] = None
    evidence: Optional[Evidence] = None

    @property
    def selected_option(self) -> Optional[str]:
        return self.envelope.selected_option if self.envelope else None

    @property
    def confidence(self) -> Optional[float]:
        return self.envelope.confidence if self.envelope else None

    @property
    def decision_id(self) -> Optional[str]:
        return self.envelope.decision_id if self.envelope else None

    @property
    def evidence_state(self) -> VerificationState:
        if self.evidence is None:
            return VerificationState.UNVERIFIED
        if not self.evidence.tests_passed or not self.evidence.test_command.strip():
            return VerificationState.TESTS_FAILED
        return VerificationState.TESTS_PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "action": self.action.value,
            "gate": self.gate.value if self.gate else None,
            "threshold": self.threshold,
            "engine": self.engine,
            "source": self.source,
            "safety_class": self.safety_class.value,
            "requires_approval": self.requires_approval,
            "approval_reason": self.approval_reason,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "tool": self.tool,
            "evidence_state": self.evidence_state.value,
            "decision": self.envelope.to_dict() if self.envelope else None,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
