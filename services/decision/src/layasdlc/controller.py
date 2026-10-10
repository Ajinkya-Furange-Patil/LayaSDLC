"""The workflow controller (Stage 1 responsibility 3).

Sequences one bounded decision end to end and is the *only* place that does so:

1. resolve and validate the option set, then narrow it to permitted tools
   (:mod:`layasdlc.permissions` layer 1) -- **before** any engine is consulted.
   If narrowing leaves exactly one option the answer is already determined, so
   it is settled from the policy without inference (see
   :meth:`WorkflowController._forced_choice`);
2. run a deterministic safety scan (Stage 1 feature 8);
3. call the configured :class:`~layasdlc.engine.DecisionEngine` under a
   configurable timeout;
4. validate the answer against the allowed options (Stage 2 requirements 5, 6);
5. apply the confidence gate; on refusal, fall back to the deterministic engine
   (Stage 2 requirement 7) -- under the same threshold, so "fallback" cannot
   launder an unconfident answer;
6. re-assert tool permissions (layer 2) and choose the action;
7. record latency and usage (Stage 2 acceptance), then return.

It never executes anything (Stage 1 feature 4) and never persists anything
(Stage 1 excludes persistence), so it stays a pure orchestration seam: swapping
the engine implementation requires no change here.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .contracts import (
    Action,
    ControllerResult,
    DecisionEnvelope,
    DecisionType,
    GateState,
    Outcome,
    SafetyClass,
    TaskState,
    Usage,
)
from .engine import DecisionEngine, EngineAnswer, EngineRequest
from .errors import (
    DecisionRejected,
    DecisionServiceError,
    EngineFailure,
    EngineTimeout,
)
from .metrics import Metrics, get_logger
from .permissions import ToolPermissionPolicy, guard_decision, narrow_options
from .policy import GateVerdict, PolicyConfig, evaluate_gate, requires_approval
from .questions import prompt_state, question_for
from .safety import classify_safety
from .validation import resolve_allowed_options, validate_answer

_log = get_logger("controller")


@dataclass(frozen=True)
class ControllerConfig:
    """Controller tunables: timeouts and policy in one object."""

    timeout_s: float = 10.0
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    #: Enforce the timeout with a watchdog thread. Off only for engines that are
    #: known to honour ``EngineRequest.timeout_s`` themselves.
    watchdog: bool = True

    def __post_init__(self) -> None:
        if self.timeout_s <= 0:
            raise ValueError(f"timeout_s must be > 0, got {self.timeout_s}")


@dataclass
class WorkflowController:
    """Asks one bounded question and returns a validated decision."""

    engine: DecisionEngine
    config: ControllerConfig = field(default_factory=ControllerConfig)
    #: Deterministic baseline used when the engine fails, abstains or is rejected.
    fallback: Optional[DecisionEngine] = None
    permissions: ToolPermissionPolicy = field(default_factory=ToolPermissionPolicy.read_only)
    metrics: Metrics = field(default_factory=Metrics)

    # --- public API --------------------------------------------------------------------

    def decide(self, state: TaskState, decision_type: str,
               allowed_options: Optional[Sequence[str]] = None, *,
               request_id: Optional[str] = None,
               model: Optional[str] = None) -> ControllerResult:
        """Answer one bounded question. Never raises for engine failures.

        Caller mistakes *do* raise: an unknown ``decision_type`` or an option
        outside the decision's canonical set is a programming error, not a
        runtime condition, and silently accepting it would defeat the validator.
        """
        started = time.perf_counter()
        decision_id = request_id or uuid.uuid4().hex

        # 1. Option set: validated, then narrowed to permitted tools (layer 1).
        options = resolve_allowed_options(decision_type, allowed_options)
        options = narrow_options(decision_type, options, self.permissions)

        # 2. Deterministic safety scan, independent of any model.
        prompt = prompt_state(state)
        safety = classify_safety(prompt)

        request = EngineRequest(
            decision_id=decision_id,
            task_id=state.task_id,
            decision_type=decision_type,
            allowed_options=options,
            state=prompt,
            question=question_for(decision_type, options)["selection"]["instructions"],
            model=model,
            timeout_s=self.config.timeout_s,
        )

        # 3-5. Ask, validate, gate, maybe fall back.
        if len(options) == 1:
            outcome, envelope, gate, error, source = self._forced_choice(request, options[0])
        else:
            outcome, envelope, gate, error, source = self._resolve(request)

        # 6. Layer 2 permission check, then action.
        if envelope is not None:
            guard_decision(envelope, self.permissions)
        action = _resolve_action(envelope, gate, outcome, safety)

        latency_ms = (time.perf_counter() - started) * 1000.0
        engine_name = getattr(self.engine, "name", type(self.engine).__name__)

        self.metrics.record(
            engine=engine_name,
            decision_type=decision_type,
            outcome=outcome.value,
            latency_ms=latency_ms,
            decision_id=decision_id,
            task_id=state.task_id,
            source=source,
            usage=envelope.usage if envelope else None,
            error=error,
        )
        _log.debug("decision %s type=%s outcome=%s latency=%.1fms",
                   decision_id, decision_type, outcome.value, latency_ms)

        return ControllerResult(
            envelope=envelope,
            outcome=outcome,
            action=action,
            gate=gate.state,
            threshold=gate.threshold,
            engine=engine_name,
            source=source,
            safety_class=safety.safety_class,
            requires_approval=requires_approval(safety, self.config.policy),
            approval_reason=safety.reason if requires_approval(safety, self.config.policy)
            else None,
            latency_ms=latency_ms,
            error=error,
            tool=envelope.selected_option if envelope else None,
        )

    def health(self) -> dict[str, Any]:
        """Delegate to :mod:`layasdlc.health` with everything it needs."""
        from .health import health_check

        return health_check(controller=self)

    # --- internals ---------------------------------------------------------------------

    def _resolve(self, request: EngineRequest):
        """Engine -> validate -> gate -> (fallback).

        Returns ``(outcome, envelope, gate, error, source)``.

        Outcome rules (they differ on purpose):
          * ``REJECTED`` -- an answer arrived but was refused: malformed,
            unsupported, out of scope, or below the confidence threshold;
          * ``FAILED``   -- no answer arrived at all: timeout, transport error,
            or an engine that raised.
        """
        fallback_engine = self.fallback

        envelope, error, kind = self._ask(self.engine, request)
        gate = evaluate_gate(envelope.confidence if envelope else None, self.config.policy)

        if envelope is not None and gate.accepted:
            return Outcome.DECIDED, envelope, gate, None, "engine"

        if envelope is None:
            outcome = Outcome.FAILED if kind == "failed" else Outcome.REJECTED
        else:
            # gate.confidence is None when the engine reported no usable number
            # (UNEVALUATED); formatting it with :.4f would raise TypeError.
            if error is None:
                if gate.confidence is None:
                    error = ("no usable confidence reported by the engine "
                             "(gate: unevaluated)")
                else:
                    error = (f"confidence {gate.confidence:.4f} below threshold "
                             f"{gate.threshold:.4f}")
            outcome = Outcome.REJECTED

        if not self.config.policy.fallback_enabled or fallback_engine is None:
            return outcome, envelope, gate, error, "engine"

        fb_envelope, fb_error, _fb_kind = self._ask(fallback_engine, request)
        if fb_envelope is None:
            return (outcome, envelope, gate, error or fb_error, "engine")

        fb_gate = evaluate_gate(fb_envelope.confidence, self.config.policy)
        if fb_gate.accepted:
            # Keep the original reason so the audit trail explains *why* we fell back.
            return Outcome.FALLBACK, fb_envelope, fb_gate, error, "fallback"
        return outcome, envelope, gate, error or "fallback did not clear the gate", "engine"

    def _forced_choice(self, request: EngineRequest, option: str):
        """Answer a question whose option set has already collapsed to one.

        Two independent reasons this is a real code path and not a shortcut:

        *Logically.* Once layer 1 has narrowed the options to a single permitted
        tool, there is nothing left to infer. The permission policy is the only
        thing that determined the answer, so consulting a model would merely
        dress a constraint up as a judgement. ``confidence`` is therefore 1.0
        **by construction, not by measurement** -- it means "certain because
        there was no alternative", not "the model felt sure".

        *Empirically.* Verified live against the real endpoint during Stage 2
        reconnaissance: ``POST /v1/systemone`` returns HTTP 503
        ``inference_unavailable`` for **every** single-option question -- all
        four decision types, all option contents, 5/5 attempts each -- while
        returning 200 for two or more options (5/5 attempts). This looks like a
        degenerate single-class distribution on the server side. Padding the
        question with a fabricated option to work around it would be inventing
        data, which is exactly what this project refuses to do.

        The answer still travels through :func:`layasdlc.validation.validate_answer`,
        so contract checking and option scoping are not bypassed either; and
        layer 2 re-checks permissions on the resulting envelope as usual.
        """
        answer = EngineAnswer(
            selected_option=option,
            confidence=1.0,
            rationale=None,
            model=None,
            model_version=None,
            latency_ms=0.0,
            usage=None,
            raw={"forced_choice": True, "reason": "single permitted option"},
        )
        envelope = validate_answer(request, answer)
        gate = evaluate_gate(envelope.confidence, self.config.policy)
        return Outcome.DECIDED, envelope, gate, None, "policy"

    def _ask(self, engine: DecisionEngine, request: EngineRequest):
        """Call one engine under the timeout and validate whatever comes back.

        Returns ``(envelope, error, kind)`` where ``kind`` is ``"ok"``,
        ``"rejected"`` (contract violation) or ``"failed"`` (no usable answer).
        """
        name = getattr(engine, "name", type(engine).__name__)
        try:
            answer = self._call_with_timeout(engine, request)
        except EngineTimeout as exc:
            return None, f"EngineTimeout[{name}]: {exc}", "failed"
        except DecisionServiceError as exc:
            return None, f"{type(exc).__name__}[{name}]: {exc}", "failed"
        except Exception as exc:  # noqa: BLE001 - requirement 7: model failures never escape
            _log.warning("engine %s raised unexpectedly: %s", name, exc)
            return None, f"{EngineFailure.__name__}[{name}]: {type(exc).__name__}: {exc}", "failed"

        try:
            return validate_answer(request, answer), None, "ok"
        except DecisionRejected as exc:
            # Stage 2 requirement 6: reject, do not coerce.
            return None, f"{type(exc).__name__}[{name}]: {exc}", "rejected"

    def _call_with_timeout(self, engine: DecisionEngine,
                           request: EngineRequest) -> EngineAnswer:
        if not self.config.watchdog:
            return engine.decide(request)

        # The transport timeout is the engine's own, so it should fire first and
        # produce an accurate "the endpoint did not answer" error. The watchdog is
        # a backstop for engines that ignore ``EngineRequest.timeout_s`` entirely,
        # hence the grace period -- without it the two timeouts race and the
        # backstop masks the real cause.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="layasdlc-engine")
        try:
            future = pool.submit(engine.decide, request)
            try:
                return future.result(timeout=request.timeout_s + self.WATCHDOG_GRACE_S)
            except FutureTimeoutError as exc:
                future.cancel()
                raise EngineTimeout(
                    f"engine {getattr(engine, 'name', '?')} did not answer within "
                    f"{request.timeout_s}s"
                ) from exc
        finally:
            # A watchdog that joined the worker would hang on an engine that ignores
            # its own timeout, so the pool is abandoned rather than awaited.
            pool.shutdown(wait=False, cancel_futures=True)

    #: Extra time the watchdog allows beyond the engine's own timeout.
    WATCHDOG_GRACE_S = 1.0


def _resolve_action(envelope: Optional[DecisionEnvelope], gate: GateVerdict,
                    outcome: Outcome, safety: Any) -> Action:
    """Choose the routing instruction.

    Conservative by construction: anything needing approval, or with no
    trustworthy answer, is never ``PROCEED``.
    """
    if safety.requires_approval:
        return Action.ESCALATE
    if envelope is None:
        return Action.ABSTAIN if outcome in (Outcome.FAILED, Outcome.REJECTED) \
            else Action.INVESTIGATE

    if envelope.decision_type == DecisionType.RETRY_VS_ESCALATE.value:
        if envelope.selected_option == "escalate":
            return Action.ESCALATE
        if not gate.accepted:
            return Action.INVESTIGATE
        return Action.PROCEED

    if not gate.accepted:
        return Action.INVESTIGATE
    if outcome is Outcome.FALLBACK:
        # An answer from the baseline is usable, but it did not come from the model
        # and the record says so via ``source``.
        return Action.PROCEED
    return Action.PROCEED


__all__ = [
    "WorkflowController",
    "ControllerConfig",
    "DecisionEnvelope",
    "GateState",
    "SafetyClass",
    "Usage",
    "Metrics",
]
