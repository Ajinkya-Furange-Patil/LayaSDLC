"""Typed failure vocabulary.

Stage 2 requirement 6: malformed, unsupported or out-of-scope outputs must be
*rejected*, not coerced. Each rejection reason gets its own exception type so the
controller can branch on the cause instead of parsing messages, and so the
metric recorded distinguishes "the model was wrong" from "the network died".
"""

from __future__ import annotations

from typing import Any, Optional, Sequence


class DecisionServiceError(Exception):
    """Base class for every failure this service raises."""


# --- contract violations (the engine answered, but not usefully) ----------------------


class DecisionRejected(DecisionServiceError):
    """Stage 2 req 6: the payload is malformed, unsupported or out of scope.

    Base of the three specific rejections below so a caller can catch broadly.
    """

    retryable = False
    reason = "rejected"

    def __init__(self, message: str, *, decision_type: Optional[str] = None,
                 detail: Any = None):
        super().__init__(message)
        self.decision_type = decision_type
        self.detail = detail


class MalformedDecision(DecisionRejected):
    """Missing/ill-typed fields, unparseable body, or a structurally invalid envelope."""

    reason = "malformed"


class UnsupportedDecisionType(DecisionRejected):
    """The engine was asked for -- or returned -- a decision type outside the registry."""

    reason = "unsupported_type"


class OutOfScopeOption(DecisionRejected):
    """``selected_option`` is not one of ``allowed_options``.

    Carries both sets so a rejection can be logged with exactly what was asked
    versus what came back.
    """

    reason = "out_of_scope"

    def __init__(self, message: str, *, selected: Any, allowed: Sequence[str],
                 decision_type: Optional[str] = None):
        super().__init__(message, decision_type=decision_type)
        self.selected = selected
        self.allowed = list(allowed)


class InvalidConfidence(DecisionRejected):
    """Confidence present but not meaningful (out of range, wrong type, NaN)."""

    reason = "invalid_confidence"


# --- permissions (Stage 2 requirement 8) ----------------------------------------------


class PermissionDenied(DecisionServiceError):
    """A decision would grant access a tool policy does not allow.

    Deliberately not a :class:`DecisionRejected`: the decision itself may be
    perfectly valid, but acting on it is not permitted. The controller never
    lets model output widen this.
    """

    reason = "permission_denied"

    def __init__(self, message: str, *, tool: str, required_permission: Optional[str] = None):
        super().__init__(message)
        self.tool = tool
        self.required_permission = required_permission


# --- transport-side (could be transient) ----------------------------------------------


class EngineTimeout(DecisionServiceError):
    """The engine exceeded its configured timeout."""

    retryable = True
    status = "timeout"


class EngineUnavailable(DecisionServiceError):
    """Connection failed, DNS failed, or the endpoint returned a 5xx."""

    retryable = True
    status = "unavailable"


class EngineRateLimited(DecisionServiceError):
    retryable = True
    status = "rate_limited"


class EngineAuthError(DecisionServiceError):
    retryable = False
    status = "auth"


class EngineRejected(DecisionServiceError):
    """The endpoint understood the request and refused it (HTTP 400/422)."""

    retryable = False
    status = "rejected"

    def __init__(self, message: str, *, http_status: Optional[int] = None,
                 detail: Sequence[Any] = ()):
        super().__init__(message)
        self.http_status = http_status
        self.detail = list(detail)


class MalformedResponse(DecisionServiceError):
    """HTTP 2xx whose body is not the documented decision payload."""

    retryable = False
    status = "malformed"

    def __init__(self, message: str, *, raw: Optional[str] = None):
        super().__init__(message)
        self.raw = raw


class EngineFailure(DecisionServiceError):
    """The engine raised something we do not recognise. Never retried blindly."""

    retryable = False
    status = "engine_error"


# --- workflow routing (Stage 3) ---------------------------------------------------------


class WorkflowError(DecisionServiceError):
    """Base for the Stage 3 state machine's refusals.

    These are *caller* mistakes rather than runtime conditions: asking to do
    something the task's current phase does not permit, or asking to complete
    work that is not finished. They raise rather than degrading, because
    silently accepting either would defeat the very rules this layer exists to
    enforce.
    """

    reason = "workflow"


class InvalidTransition(WorkflowError):
    """The requested action is not permitted from the task's current phase."""

    reason = "invalid_transition"

    def __init__(self, message: str, *, from_phase: str, action: str,
                 permitted: Sequence[str] = ()):
        super().__init__(message)
        self.from_phase = from_phase
        self.action = action
        self.permitted = list(permitted)


class IncompleteTask(WorkflowError):
    """``COMPLETE`` was requested but the task's completion conditions are unmet.

    This is the guard behind "a task cannot be marked complete merely because
    Laya selected COMPLETE": the model's choice is never sufficient on its own.
    """

    reason = "incomplete"

    def __init__(self, message: str, *, unmet: Sequence[str] = ()):
        super().__init__(message)
        self.unmet = list(unmet)


# --- Stage 1 feature 7 / 8 --------------------------------------------------------------


# --- Stage 7: execution ------------------------------------------------------------------


class CodingError(DecisionServiceError):
    """The coding adapter failed: a model call raised, timed out, or returned
    something unusable.

    Distinct from ``EngineFailure`` (which is about the *decision* engine) so
    a caller can tell which adapter broke without parsing messages.
    """

    reason = "coding_error"


class ExecutionError(DecisionServiceError):
    """The execution engine could not complete a step."""

    reason = "execution_error"


class UnverifiedClaimError(DecisionServiceError):
    """Raised when something claims success without passing test evidence."""


class ApprovalRequiredError(DecisionServiceError):
    """Raised when a destructive or deployment action is attempted unapproved."""

    def __init__(self, message: str, *, safety_class: str, requires_approval: bool = True):
        super().__init__(message)
        self.safety_class = safety_class
        self.requires_approval = requires_approval
