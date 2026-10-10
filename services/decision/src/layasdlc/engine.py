"""The decision-engine interface (Stage 1 responsibility 1, Stage 2 requirement 9).

One protocol, many implementations. The controller depends *only* on
:class:`DecisionEngine`, so swapping Laya for a fake, a different checkpoint or
a future in-process runner requires no change to the controller -- which is the
Stage 1 acceptance criterion "the decision engine can be replaced without
rewriting the controller".

Implementations raise the typed errors in :mod:`layasdlc.errors` rather than
returning sentinel values, so callers branch on exception type.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable

from .contracts import Usage
from .errors import MalformedResponse, UnsupportedDecisionType


@dataclass(frozen=True)
class EngineRequest:
    """A single bounded question put to an engine."""

    decision_id: str
    task_id: str
    decision_type: str
    allowed_options: tuple[str, ...]
    state: Mapping[str, Any]
    question: str
    #: Optional per-call hint (e.g. a checkpoint name). Engines may ignore it.
    model: Optional[str] = None
    timeout_s: float = 10.0


@dataclass(frozen=True)
class EngineAnswer:
    """What an engine returns *before* validation.

    Kept deliberately loose: engines differ in what they report, and validation
    is a separate step (Stage 2 requirement 5). ``selected_option`` is required
    but not trusted until :mod:`layasdlc.validation` has checked it.
    """

    selected_option: str
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    model: Optional[str] = None
    model_version: Optional[str] = None
    latency_ms: Optional[float] = None
    usage: Optional[Usage] = None
    #: Full probability distribution over options, when the engine provides one.
    probabilities: Mapping[str, float] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class DecisionEngine(Protocol):
    """Anything that can answer one bounded question."""

    #: Stable identifier recorded alongside every measurement.
    name: str

    #: Version of the underlying model/implementation, when known.
    version: Optional[str]

    def available(self) -> bool:
        """Cheap readiness probe used by the health check. Must not load a model."""
        ...

    def decide(self, request: EngineRequest) -> EngineAnswer:
        """Answer ``request``. Honours ``request.timeout_s``.

        Raises:
            EngineTimeout | EngineUnavailable | EngineRateLimited | EngineAuthError |
            EngineRejected | MalformedResponse | EngineFailure
        """
        ...


def answer_confidence(answer: Any) -> Optional[float]:
    """Read the confidence a Laya-style answer actually supports.

    ``laya.structured`` documents ``DecisionResult.answer_confidence`` as
    ``max(p)`` per field -- "the same decision quantity ``min_confidence``
    compares against and the calibration and eval stack measures". So for a
    ``choice`` answer we take ``max(probabilities)``. The ``confidence`` field
    the endpoint also returns is normalised entropy (``1 - H(p)/log k``), a
    *different* number; using it here would silently mis-gate.

    For ``noul`` the reported value is P(true), and Laya's own gate uses
    ``max(p_true, 1 - p_true)``, so we mirror that.

    Returns ``None`` when no usable probability exists -- never a guessed value.
    """
    if not isinstance(answer, Mapping):
        return None

    kind = answer.get("type")

    if kind == "choice":
        values = _numeric_values(answer.get("probabilities"))
        if values:
            return max(values)
        return _as_float(answer.get("confidence"))

    if kind == "noul":
        value = _as_float(answer.get("noul"))
        if value is None or not 0.0 <= value <= 1.0:
            return None
        return max(value, 1.0 - value)

    if kind == "score":
        values = _numeric_values(answer.get("probabilities"))
        if values:
            return max(values)
        return _as_float(answer.get("confidence"))

    return None


def ranked_probabilities(answer: Any) -> list[tuple[str, float]]:
    """``(option, probability)`` pairs for a choice answer, best first.

    A ``probabilities`` field that is *present* has to be usable in full: every
    entry must be a finite number. Anything else is malformed **response** data
    and is refused here with :class:`~layasdlc.errors.MalformedResponse` --
    which is already the taxonomy this module's engines use for a 2xx body that
    is not the documented payload, and which ``DecisionEngine.decide`` already
    documents as a legal raise.

    This function used to skip entries it could not parse. That let a
    distribution arrive incomplete and leave looking complete: validation only
    ever saw what survived, so ``{"bug_fix": true, "feature": 0.4}`` became a
    confident two-way ranking with ``bug_fix`` erased, and nothing downstream
    could tell that a member had gone missing. Dropping is not an option and
    neither is publishing the remainder, so the parse either succeeds whole or
    fails loud.

    Two things this deliberately does *not* treat as errors:

    * **An absent or ``null`` field.** That is "no distribution reported" --
      honest, and distinct from a malformed one. It yields ``[]``, which the
      validator turns into ``alternatives=None``.
    * **Out-of-range numbers.** ``1.5`` is a representable JSON number that is
      simply not a probability; that is the validator's call, not this
      parser's, and it is rejected there.
    """
    if not isinstance(answer, Mapping):
        return []
    probs = answer.get("probabilities")
    if probs is None:
        return []
    if not isinstance(probs, Mapping):
        raise MalformedResponse(
            f"'probabilities' must be an object or null, got {type(probs).__name__}"
        )
    pairs: list[tuple[str, float]] = []
    for label, value in probs.items():
        pairs.append((str(label), _finite_probability(value, label)))
    pairs.sort(key=lambda item: item[1], reverse=True)
    return pairs


def _finite_probability(value: Any, option: Any) -> float:
    """One reported probability, or :class:`MalformedResponse` if it is not one.

    ``bool`` is excluded explicitly. JSON ``true`` is a well-formed boolean and
    Python models it as ``int`` 1, so without that check a model answering
    ``{"bug_fix": true}`` would be read as certainty instead of as the contract
    violation it is.

    Note this is stricter than :func:`answer_confidence`'s coercion, which is
    deliberate: confidence is allowed to be *absent*, so a value it cannot read
    degrades to ``None``. A distribution cannot -- a missing member changes what
    the remaining members mean.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MalformedResponse(
            f"probability for {option!r} must be a number, got {type(value).__name__}"
        )
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        # JSON has no literal for these, so seeing one means something upstream
        # produced a value off the real line -- not a probability.
        raise MalformedResponse(
            f"probability for {option!r} is not a finite number ({value!r})"
        )
    return number


def require_supported(decision_type: str, supported: Sequence[str]) -> None:
    """Raise :class:`UnsupportedDecisionType` for anything outside ``supported``."""
    if decision_type not in supported:
        raise UnsupportedDecisionType(
            f"decision type {decision_type!r} is not supported; "
            f"expected one of {sorted(supported)}",
            decision_type=decision_type,
        )


def _numeric_values(raw: Any) -> list[float]:
    if not isinstance(raw, Mapping):
        return []
    out: list[float] = []
    for value in raw.values():
        parsed = _as_float(value)
        if parsed is not None:
            out.append(parsed)
    return out


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result
