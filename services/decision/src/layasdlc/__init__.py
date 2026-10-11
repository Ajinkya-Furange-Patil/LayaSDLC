"""LayaSDLC decision service.

Asks one bounded engineering question of a replaceable decision engine (real
Laya, or a deterministic baseline), validates the answer against an explicit
option set, applies a confidence gate, falls back deterministically, and reports
what it did -- without executing anything.

Typical use::

    from layasdlc import (
        WorkflowController, ControllerConfig, TaskState,
        DeterministicEngine, LayaHttpEngine, ToolPermissionPolicy,
    )

    controller = WorkflowController(
        engine=LayaHttpEngine(base_url="https://example.invalid"),
        fallback=DeterministicEngine(),
        permissions=ToolPermissionPolicy.read_only(),
    )
    result = controller.decide(TaskState(task_id="T-1", subject="Fix the crash"),
                               "task_classification")

Public surface is deliberately small; see docs/architecture.md for the layer map.
"""

from __future__ import annotations

from .contracts import (
    DECISION_SPACE,
    SCHEMA_VERSION,
    Action,
    Alternative,
    ControllerResult,
    DecisionEnvelope,
    DecisionType,
    Evidence,
    GateState,
    Outcome,
    SafetyClass,
    TaskKind,
    TaskState,
    Usage,
    VerificationState,
)
from .controller import ControllerConfig, WorkflowController
from .engine import DecisionEngine, EngineAnswer, EngineRequest, answer_confidence
from .engines import (
    DeterministicEngine,
    FakeEngine,
    LayaHttpEngine,
    LayaSdkEngine,
    Scripted,
    UrllibTransport,
    laya_sdk_available,
    score_state,
)
from .errors import (
    CodingError,
    ExecutionError,
    ApprovalRequiredError,
    DecisionRejected,
    DecisionServiceError,
    EngineAuthError,
    EngineFailure,
    EngineRateLimited,
    EngineRejected,
    EngineTimeout,
    EngineUnavailable,
    IncompleteTask,
    InvalidConfidence,
    InvalidTransition,
    MalformedDecision,
    MalformedResponse,
    OutOfScopeOption,
    PermissionDenied,
    UnverifiedClaimError,
    UnsupportedDecisionType,
    WorkflowError,
)
from .health import SERVICE_NAME, SERVICE_VERSION, health_check, is_healthy
from .metrics import Measurement, Metrics, get_logger
from .permissions import ToolPermissionPolicy, guard_decision, narrow_options
from .policy import GateVerdict, PolicyConfig, evaluate_gate, guard_success_claim
from .questions import INSTRUCTIONS, OPTION_DESCRIPTIONS, question_for
from .safety import SafetyFinding, classify_safety
from .validation import resolve_allowed_options, validate_answer, validate_envelope
from .coding import CodingAdapter, CodingResult, CodingError, FakeCodingAdapter, LocalCodingAdapter
from .coding import CodingAdapter, CodingResult, CodingError, FakeCodingAdapter, LocalCodingAdapter
from .execution import CheckResult, ExecutionEngine, ExecutionResult
from .context import (
    ContextItem,
    ContextPackage,
    ItemKind,
    Source,
    build_package,
    deduplicate,
    estimate_tokens,
    from_filename_search,
    from_git_diff,
    from_symbol_search,
    from_test_failures,
    measure_tokens,
    rank_items,
)
from .store import STORE_SCHEMA_VERSION, StoreError, TaskStore
from .workflow import (
    COMPLETION_RULES,
    ActionRecord,
    Approval,
    RouteDecision,
    TaskPhase,
    WorkflowAction,
    WorkflowTask,
    new_task,
    validate_transition,
)
from .router import WorkflowRouter

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # contracts
    "STORE_SCHEMA_VERSION",
    "DECISION_SPACE",
    "DecisionType",
    "DecisionEnvelope",
    "TaskKind",
    "TaskState",
    "ControllerResult",
    "Usage",
    "Alternative",
    "Evidence",
    "Action",
    "Outcome",
    "GateState",
    "SafetyClass",
    "VerificationState",
    # controller
    "WorkflowController",
    "ControllerConfig",
    # engine interface
    "DecisionEngine",
    "EngineRequest",
    "EngineAnswer",
    "answer_confidence",
    # engines
    "FakeEngine",
    "Scripted",
    "DeterministicEngine",
    "score_state",
    "LayaHttpEngine",
    "UrllibTransport",
    "LayaSdkEngine",
    "laya_sdk_available",
    # validation
    "resolve_allowed_options",
    "validate_answer",
    "validate_envelope",
    # policy / permissions / safety
    "PolicyConfig",
    "GateVerdict",
    "evaluate_gate",
    "guard_success_claim",
    "ToolPermissionPolicy",
    "guard_decision",
    "narrow_options",
    "classify_safety",
    "SafetyFinding",
    # questions
    "question_for",
    "INSTRUCTIONS",
    "OPTION_DESCRIPTIONS",
    # observability
    "Metrics",
    "Measurement",
    "get_logger",
    "health_check",
    "is_healthy",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    # errors
    "DecisionServiceError",
    "DecisionRejected",
    "MalformedDecision",
    "UnsupportedDecisionType",
    "OutOfScopeOption",
    "InvalidConfidence",
    "PermissionDenied",
    "EngineTimeout",
    "EngineUnavailable",
    "EngineRateLimited",
    "EngineAuthError",
    "EngineRejected",
    "EngineFailure",
    "MalformedResponse",
    "WorkflowError",
    "InvalidTransition",
    "IncompleteTask",
    "UnverifiedClaimError",
    "ApprovalRequiredError",
    # workflow state machine (Stage 3)
    "WorkflowAction",
    "TaskPhase",
    "WorkflowTask",
    "ActionRecord",
    "Approval",
    "RouteDecision",
    "COMPLETION_RULES",
    "WorkflowRouter",
    "new_task",
    "validate_transition",
]
