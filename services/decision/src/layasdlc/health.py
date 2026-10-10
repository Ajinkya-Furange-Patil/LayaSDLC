"""Health check for the decision service (Stage 1 foundation).

Deliberately cheap: it calls :meth:`DecisionEngine.available`, which every
engine must implement as a probe that does **not** load weights or open a
network connection. A health check that downloads a model is not a health check.

Returned document is JSON-serialisable and reports *verified* state only -- it
never claims an engine is healthy because it was configured.
"""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from .contracts import DECISION_SPACE, SCHEMA_VERSION, DecisionType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .controller import WorkflowController
    from .engine import DecisionEngine

SERVICE_NAME = "layasdlc-decision"
SERVICE_VERSION = "0.1.0"


def _engine_info(engine: Optional["DecisionEngine"]) -> dict[str, Any]:
    if engine is None:
        return {"name": None, "version": None, "available": False}
    available: bool
    try:
        available = bool(engine.available())
    except Exception as exc:  # noqa: BLE001 - a throwing probe is itself a finding
        return {
            "name": getattr(engine, "name", type(engine).__name__),
            "version": getattr(engine, "version", None),
            "available": False,
            "probe_error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "name": getattr(engine, "name", type(engine).__name__),
        "version": getattr(engine, "version", None),
        "available": available,
    }


def health_check(controller: Optional["WorkflowController"] = None, *,
                 engine: Optional["DecisionEngine"] = None,
                 fallback: Optional["DecisionEngine"] = None) -> dict[str, Any]:
    """Build the health document.

    ``status`` is ``ok`` only when the primary engine reports available;
    otherwise ``degraded`` -- the service still works via the deterministic
    fallback, which is reported separately so a caller can tell the difference
    between "Laya is answering" and "we are running on the baseline".
    """
    primary = engine or (controller.engine if controller else None)
    secondary = fallback or (controller.fallback if controller else None)

    primary_info = _engine_info(primary)
    fallback_info = _engine_info(secondary)

    status = "ok" if primary_info["available"] else "degraded"

    document: dict[str, Any] = {
        "status": status,
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": primary_info,
        "fallback": fallback_info,
        "capabilities": {
            "decision_types": [d.value for d in DecisionType],
            "options": {d.value: list(options) for d, options in DECISION_SPACE.items()},
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }

    if controller is not None:
        document["permissions"] = sorted(controller.permissions.allowed_tools)
        document["policy"] = {
            "min_confidence": controller.config.policy.min_confidence,
            "fallback_enabled": controller.config.policy.fallback_enabled,
            "timeout_s": controller.config.timeout_s,
        }
        document["metrics"] = controller.metrics.summary()

    return document


def is_healthy(document: dict[str, Any]) -> bool:
    return document.get("status") == "ok"
