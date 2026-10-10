"""Schema and option validation (Stage 2 requirements 5 and 6).

Nothing an engine returns is trusted until it passes through here. Every check
has a distinct exception so the controller can record *why* something was
rejected rather than a generic "bad answer".

Rejection rules:

* unknown decision type          -> :class:`UnsupportedDecisionType`
* option set widens the registry -> :class:`OutOfScopeOption` (request side)
* selection outside the options  -> :class:`OutOfScopeOption` (answer side)
* missing/ill-typed required     -> :class:`MalformedDecision`
  field
* confidence present but not in
  ``[0, 1]``, NaN or wrong type  -> :class:`InvalidConfidence`
* confidence absent              -> **accepted as ``None``** (requirement 3:
  confidence only when meaningfully supported; missing is not malformed)
* probability distribution absent
  or empty                       -> ``alternatives = None`` (never ``[]``)
* malformed probability          -> :class:`MalformedDecision`
  entries (wrong type, NaN,
  non-finite, outside ``[0, 1]``,
  non-string key)
* probability for an option the
  request did not offer          -> :class:`OutOfScopeOption`

A malformed distribution is **rejected, never repaired**. Dropping the bad
entries and publishing the rest would present a hand-edited distribution as if
the model had produced it, which is exactly the fabrication this project
refuses to do.
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Mapping, Optional, Sequence

from .contracts import (
    DECISION_SPACE,
    SCHEMA_VERSION,
    Alternative,
    DecisionEnvelope,
    DecisionType,
    Usage,
)
from .engine import EngineAnswer, EngineRequest
from .errors import (
    InvalidConfidence,
    MalformedDecision,
    OutOfScopeOption,
    UnsupportedDecisionType,
)


def resolve_allowed_options(decision_type: str,
                            requested: Optional[Sequence[str]] = None) -> tuple[str, ...]:
    """Validate the option set *before* any engine is called.

    A caller may narrow the canonical set but never widen it: widening would let
    a request introduce an option the decision type does not define.

    Raises:
        UnsupportedDecisionType: ``decision_type`` is not in the registry.
        OutOfScopeOption: ``requested`` contains an option the type forbids.
        MalformedDecision: the resulting set is empty or has duplicates.
    """
    try:
        dtype = DecisionType(decision_type)
    except ValueError as exc:
        raise UnsupportedDecisionType(
            f"unknown decision type {decision_type!r}; "
            f"expected one of {[d.value for d in DecisionType]}",
            decision_type=decision_type,
        ) from exc

    canonical = DECISION_SPACE[dtype]
    if requested is None:
        return canonical

    options = tuple(str(option) for option in requested)
    if len(set(options)) != len(options):
        raise MalformedDecision(
            f"allowed_options for {decision_type!r} contains duplicates: {list(options)}",
            decision_type=decision_type,
        )
    if not options:
        raise MalformedDecision(
            f"allowed_options for {decision_type!r} is empty", decision_type=decision_type
        )

    unknown = [option for option in options if option not in canonical]
    if unknown:
        raise OutOfScopeOption(
            f"allowed_options for {decision_type!r} contains options the type does not "
            f"define: {unknown}; canonical set is {list(canonical)}",
            selected=unknown,
            allowed=list(canonical),
            decision_type=decision_type,
        )
    return options


def _probability(value: Any, option: str, decision_type: str) -> float:
    """Coerce one reported probability, rejecting anything that is not a real one.

    ``bool`` is excluded explicitly because in Python ``True`` is an ``int`` and
    would otherwise be read as probability 1.0.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MalformedDecision(
            f"probability for {option!r} must be a number, got {type(value).__name__}",
            decision_type=decision_type,
        )
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise MalformedDecision(
            f"probability for {option!r} is not a finite number",
            decision_type=decision_type,
        )
    if not 0.0 <= number <= 1.0:
        raise MalformedDecision(
            f"probability for {option!r} is outside [0, 1]: {number}",
            decision_type=decision_type,
        )
    return number


def _rank(alternatives: list[Alternative]) -> tuple[Alternative, ...]:
    """Best-first with a tie-break that does not depend on the engine's key order.

    ``(-probability, option)`` makes equal probabilities fall back to option
    name, so two runs of the same response always produce the same envelope
    instead of inheriting JSON object ordering.
    """
    alternatives.sort(key=lambda alt: (-alt.probability, alt.option))
    return tuple(alternatives)


def _build_alternatives(request: EngineRequest,
                        raw: Any) -> Optional[tuple[Alternative, ...]]:
    """The engine's probability distribution, ranked best-first, or ``None``.

    ``None`` covers three distinct-but-equivalent cases: no field, an explicit
    ``null``, and an empty mapping. None of them is a distribution, and ``[]``
    would overstate what was reported.

    Engines normalise through :func:`layasdlc.engine.ranked_probabilities`
    first, which silently discards entries it cannot parse. Anything that
    survives that and is *still* malformed is rejected here rather than
    repaired -- see the module docstring.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise MalformedDecision(
            f"probabilities must be an object or null, got {type(raw).__name__}",
            decision_type=request.decision_type,
        )
    if not raw:
        return None

    allowed = tuple(request.allowed_options)
    built: list[Alternative] = []
    for label, value in raw.items():
        if not isinstance(label, str) or not label.strip():
            raise MalformedDecision(
                "probability keys must be non-empty strings",
                decision_type=request.decision_type,
            )
        option = label.strip()
        # A distribution over options the caller never offered is an answer to a
        # different question, and would contradict the envelope's own
        # allowed_options -- so it is refused, not filtered.
        if option not in allowed:
            raise OutOfScopeOption(
                f"engine reported a probability for {option!r} which is not in "
                f"allowed_options {list(allowed)}",
                selected=option,
                allowed=list(allowed),
                decision_type=request.decision_type,
            )
        built.append(Alternative(
            option=option,
            probability=_probability(value, option, request.decision_type),
        ))
    return _rank(built)


def _alternatives_from_payload(raw: Any, options: tuple[str, ...],
                               decision_type: str) -> Optional[tuple[Alternative, ...]]:
    """Rebuild alternatives from a serialised envelope that crossed a boundary."""
    if raw is None or raw == []:
        # An empty list carries the same information as null, and rejecting a
        # correct decision over a serialisation detail would be pedantry. It is
        # normalised rather than passed through, so ``[]`` never reaches a
        # caller as a claim that nothing was ranked.
        return None
    if not isinstance(raw, (list, tuple)):
        raise MalformedDecision("field 'alternatives' must be a list or null",
                                decision_type=decision_type)

    built: list[Alternative] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise MalformedDecision(
                "each alternative must be an object with 'option' and 'probability'",
                decision_type=decision_type,
            )
        if "option" not in entry or "probability" not in entry:
            raise MalformedDecision(
                "each alternative needs an 'option' and a 'probability'",
                decision_type=decision_type,
            )
        raw_option = entry["option"]
        if not isinstance(raw_option, str) or not raw_option.strip():
            raise MalformedDecision("alternative 'option' must be a non-empty string",
                                    decision_type=decision_type)
        option = raw_option.strip()
        if option in seen:
            raise MalformedDecision(f"alternative {option!r} appears more than once",
                                    decision_type=decision_type)
        seen.add(option)
        if option not in options:
            raise OutOfScopeOption(
                f"alternative {option!r} is not in allowed_options {list(options)}",
                selected=option,
                allowed=list(options),
                decision_type=decision_type,
            )
        built.append(Alternative(
            option=option,
            probability=_probability(entry["probability"], option, decision_type),
        ))
    return _rank(built)


def validate_answer(request: EngineRequest, answer: EngineAnswer) -> DecisionEnvelope:
    """Turn an untrusted :class:`EngineAnswer` into a validated envelope.

    Raises a :class:`~layasdlc.errors.DecisionRejected` subclass on any
    violation. On success the envelope carries the request's ids and option set,
    so an engine cannot influence which options it was supposed to choose among.
    """
    if answer is None:
        raise MalformedDecision("engine returned no answer", decision_type=request.decision_type)

    # --- required, well-typed fields ---------------------------------------------------
    option = answer.selected_option
    if option is None or not isinstance(option, str) or not option.strip():
        raise MalformedDecision(
            "selected_option is missing or empty", decision_type=request.decision_type
        )
    option = option.strip()

    # --- scope -------------------------------------------------------------------------
    allowed = tuple(request.allowed_options)
    if not allowed:
        raise MalformedDecision(
            "request carried no allowed_options", decision_type=request.decision_type
        )
    if option not in allowed:
        raise OutOfScopeOption(
            f"engine selected {option!r} which is not in allowed_options {list(allowed)}",
            selected=option,
            allowed=list(allowed),
            decision_type=request.decision_type,
        )

    # --- confidence (optional, but must be meaningful when present) --------------------
    confidence = answer.confidence
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise InvalidConfidence(
                f"confidence must be a number or null, got {type(confidence).__name__}",
                decision_type=request.decision_type,
            )
        value = float(confidence)
        if math.isnan(value) or math.isinf(value):
            raise InvalidConfidence(
                "confidence is not a finite number", decision_type=request.decision_type
            )
        if not 0.0 <= value <= 1.0:
            raise InvalidConfidence(
                f"confidence {value} is outside [0, 1]",
                decision_type=request.decision_type,
            )
        confidence = value

    # --- rationale (only when genuinely supported) --------------------------------------
    rationale = answer.rationale
    if rationale is not None and not isinstance(rationale, str):
        raise MalformedDecision(
            f"rationale must be a string or null, got {type(rationale).__name__}",
            decision_type=request.decision_type,
        )

    # --- alternatives (the distribution the engine actually reported) -------------------
    alternatives = _build_alternatives(request, answer.probabilities)

    return DecisionEnvelope(
        schema_version=SCHEMA_VERSION,
        decision_id=request.decision_id or uuid.uuid4().hex,
        task_id=request.task_id,
        decision_type=request.decision_type,
        allowed_options=allowed,
        selected_option=option,
        confidence=confidence,
        rationale=rationale,
        model=answer.model,
        model_version=answer.model_version,
        latency_ms=answer.latency_ms,
        usage=answer.usage if isinstance(answer.usage, Usage) else None,
        alternatives=alternatives,
    )


def validate_envelope(payload: Mapping[str, Any]) -> DecisionEnvelope:
    """Re-validate an envelope that arrived from elsewhere (JSON, storage, a plugin).

    Used by the OpenCode-side boundary so a decision that has crossed a process
    boundary is checked again rather than assumed intact.
    """
    if not isinstance(payload, Mapping):
        raise MalformedDecision("envelope payload must be an object")

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise MalformedDecision(
            f"unsupported schema_version {version!r}; this build speaks {SCHEMA_VERSION!r}"
        )

    required_strings = ("decision_id", "task_id", "decision_type", "selected_option")
    for name in required_strings:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise MalformedDecision(f"field {name!r} must be a non-empty string")

    raw_options = payload.get("allowed_options")
    if not isinstance(raw_options, (list, tuple)) or not raw_options:
        raise MalformedDecision("field 'allowed_options' must be a non-empty list")
    options = tuple(str(option) for option in raw_options)

    # Re-resolve against the registry so a stale/forged option list cannot slip through.
    resolve_allowed_options(payload["decision_type"], options)

    if payload["selected_option"] not in options:
        raise OutOfScopeOption(
            f"selected_option {payload['selected_option']!r} is not in allowed_options "
            f"{list(options)}",
            selected=payload["selected_option"],
            allowed=list(options),
            decision_type=payload["decision_type"],
        )

    confidence = payload.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise InvalidConfidence("confidence must be a number or null",
                                    decision_type=payload["decision_type"])
        value = float(confidence)
        if math.isnan(value) or math.isinf(value) or not 0.0 <= value <= 1.0:
            raise InvalidConfidence(f"confidence {value} is outside [0, 1]",
                                    decision_type=payload["decision_type"])
        confidence = value

    usage_raw = payload.get("usage")
    usage = Usage.from_mapping(usage_raw) if usage_raw is not None else None

    latency = payload.get("latency_ms")
    if latency is not None:
        if isinstance(latency, bool) or not isinstance(latency, (int, float)):
            raise MalformedDecision("latency_ms must be a number or null")
        latency = float(latency)

    alternatives = _alternatives_from_payload(payload.get("alternatives"), options,
                                              payload["decision_type"])

    return DecisionEnvelope(
        schema_version=SCHEMA_VERSION,
        decision_id=payload["decision_id"],
        task_id=payload["task_id"],
        decision_type=payload["decision_type"],
        allowed_options=options,
        selected_option=str(payload["selected_option"]),
        confidence=confidence,
        rationale=payload.get("rationale"),
        model=payload.get("model"),
        model_version=payload.get("model_version"),
        latency_ms=latency,
        usage=usage,
        alternatives=alternatives,
    )
