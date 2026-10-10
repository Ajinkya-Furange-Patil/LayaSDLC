"""Confidence thresholds, approval rules and evidence gates (Stage 1 features 3, 7, 8).

Pure functions: answers in, verdict out, no I/O. That keeps them unit-testable
without an engine and lets the controller apply identical rules whether an
answer came from Laya, the deterministic fallback or a fake.

Confidence semantics
--------------------
``laya.confidence.GATE_STATES`` is exactly ``("passed", "abstained",
"unevaluated")`` and deliberately has no "gate was not configured" member. This
module mirrors that: the unconfigured case is ``None``, not a fourth sentinel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .contracts import (
    Evidence,
    GateState,
    SafetyClass,
    VerificationState,
)
from .errors import ApprovalRequiredError, UnverifiedClaimError
from .safety import SafetyFinding


@dataclass(frozen=True)
class PolicyConfig:
    """Everything tunable, in one place (Stage 1 feature 3).

    ``min_confidence`` default
    --------------------------
    A six-way choice is uniform at 0.167, so a threshold must sit clearly above
    that. The shipped default is deliberately conservative and is **not**
    calibrated on real traffic -- ADR-0002 records that explicitly. It is a field
    rather than a constant precisely because calibration is a later milestone.
    """

    min_confidence: float = 0.35
    #: When the engine abstains, answer from the deterministic baseline instead.
    fallback_enabled: bool = True
    #: Treat "no usable confidence" as abstention rather than as a pass. Reading
    #: ``unevaluated`` as a pass would be the unsafe interpretation.
    missing_confidence_is_abstain: bool = True
    #: Classes that require explicit approval before any execution.
    approval_classes: frozenset[SafetyClass] = field(
        default_factory=lambda: frozenset({SafetyClass.DESTRUCTIVE, SafetyClass.DEPLOYMENT})
    )
    #: Refuse success claims when no passing test evidence was recorded.
    enforce_test_evidence: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(f"min_confidence must be in [0, 1], got {self.min_confidence}")


@dataclass(frozen=True)
class GateVerdict:
    """What the confidence gate decided, plus the numbers behind it."""

    state: Optional[GateState]
    confidence: Optional[float]
    threshold: float

    @property
    def accepted(self) -> bool:
        return self.state is GateState.PASSED


def evaluate_gate(confidence: Optional[float], config: PolicyConfig) -> GateVerdict:
    """Apply the threshold and report which of Laya's three states we are in."""
    if confidence is None:
        if config.missing_confidence_is_abstain:
            # The gate ran but had no number to judge: it could not decide.
            return GateVerdict(GateState.UNEVALUATED, None, config.min_confidence)
        # Explicitly configured to accept unmeasured answers -- still reported as
        # UNEVALUATED so the record shows the confidence was absent, never as PASSED.
        return GateVerdict(GateState.UNEVALUATED, None, config.min_confidence)
    if confidence >= config.min_confidence:
        return GateVerdict(GateState.PASSED, confidence, config.min_confidence)
    return GateVerdict(GateState.ABSTAINED, confidence, config.min_confidence)


def requires_approval(safety: SafetyFinding, config: PolicyConfig) -> bool:
    """Stage 1 feature 8.

    Decided by *class membership in* ``config.approval_classes`` alone. The
    detector's own flag only records that a phrase matched; folding it in with
    ``or`` would make ``approval_classes`` inert, since a match always implies
    DESTRUCTIVE or DEPLOYMENT.
    """
    return safety.safety_class in config.approval_classes


def guard_approval(safety: SafetyFinding, config: PolicyConfig, *, approved: bool) -> None:
    """Raise unless a gated action has been explicitly approved.

    ``approved`` is caller-supplied; this service never grants it itself.
    """
    if not requires_approval(safety, config) or approved:
        return
    raise ApprovalRequiredError(
        f"acting on a {safety.safety_class.value} task requires approval ({safety.reason})",
        safety_class=safety.safety_class.value,
        requires_approval=True,
    )


def guard_success_claim(evidence: Optional[Evidence], config: PolicyConfig,
                        *, task: Optional[str] = None) -> VerificationState:
    """Stage 1 feature 7: refuse to report "it works" without passing test evidence.

    Fails closed. Absence of a recorded command raises rather than reporting
    ``UNVERIFIED``, because an unrecorded claim must not reach a caller as a
    benign-looking status.
    """
    if not config.enforce_test_evidence:
        return VerificationState.UNVERIFIED

    if evidence is None:
        raise UnverifiedClaimError(
            f"cannot claim {task or 'the change'} works: no test evidence was recorded"
        )
    if not evidence.test_command.strip():
        raise UnverifiedClaimError(
            f"cannot claim {task or 'the change'} works: evidence has no test command"
        )
    return (VerificationState.TESTS_PASSED if evidence.tests_passed
            else VerificationState.TESTS_FAILED)
