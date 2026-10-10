"""Logging and metrics (Stage 1 responsibility 5).

In-memory only. Stage 1 explicitly excludes database persistence, so this module
records what happened for the current process -- enough for the health endpoint,
for tests, and for a later benchmark script to read -- without introducing a
storage dependency.

What is measured (Stage 2 acceptance: "actual latency and usage measurements
are recorded when obtainable"):

* wall-clock latency per engine call, measured here rather than trusted from
  the engine;
* token usage *when the engine reported it*, otherwise ``None`` -- never ``0``;
* the outcome and, on failure, the rejection reason.

``record`` is called unconditionally by the controller, including on failure, so
abstention and rejection rates are observable rather than inferred.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Optional

from .contracts import Usage, utc_now

_LOGGER_NAME = "layasdlc"
_configured = False


def get_logger(suffix: str = "") -> logging.Logger:
    """Return the service logger, configuring a single stream handler once.

    Configuration is idempotent so importing the package from a test, a CLI and
    a plugin never stacks duplicate handlers.
    """
    global _configured
    if not _configured:
        logger = logging.getLogger(_LOGGER_NAME)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            logger.addHandler(handler)
            logger.setLevel(logging.WARNING)
            logger.propagate = False
        _configured = True
    return logging.getLogger(f"{_LOGGER_NAME}.{suffix}" if suffix else _LOGGER_NAME)


@dataclass(frozen=True)
class Measurement:
    """One observation, as recorded by :meth:`Metrics.record`."""

    at: str
    engine: str
    decision_type: str
    outcome: str
    latency_ms: float
    decision_id: Optional[str] = None
    task_id: Optional[str] = None
    source: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error: Optional[str] = None

    @property
    def usage_available(self) -> bool:
        return self.input_tokens is not None or self.output_tokens is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at, "engine": self.engine, "decision_type": self.decision_type,
            "outcome": self.outcome, "latency_ms": self.latency_ms,
            "decision_id": self.decision_id, "task_id": self.task_id,
            "source": self.source, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens, "error": self.error,
        }


@dataclass
class Metrics:
    """Process-local counters plus a bounded measurement log."""

    #: Cap on retained measurements; oldest are dropped first.
    max_measurements: int = 1000
    measurements: list[Measurement] = field(default_factory=list)
    counters: Counter = field(default_factory=Counter)

    def record(self, *, engine: str, decision_type: str, outcome: str,
               latency_ms: float, decision_id: Optional[str] = None,
               task_id: Optional[str] = None, source: Optional[str] = None,
               usage: Optional[Usage] = None, error: Optional[str] = None) -> Measurement:
        measurement = Measurement(
            at=utc_now(),
            engine=engine,
            decision_type=decision_type,
            outcome=outcome,
            latency_ms=round(latency_ms, 3),
            decision_id=decision_id,
            task_id=task_id,
            source=source,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            error=error,
        )
        self.measurements.append(measurement)
        if len(self.measurements) > self.max_measurements:
            overflow = len(self.measurements) - self.max_measurements
            del self.measurements[:overflow]

        self.counters[f"outcome.{outcome}"] += 1
        self.counters[f"decision_type.{decision_type}"] += 1
        self.counters[f"engine.{engine}"] += 1
        if source:
            # ``engine`` names the configured slot; ``source`` names who actually
            # answered (engine/fallback/policy). They differ whenever the primary
            # engine was bypassed, so "how often did the real model answer?" is
            # only answerable from this counter, not from ``engine.*``.
            self.counters[f"source.{source}"] += 1
        if error:
            self.counters[f"error.{error.split(':', 1)[0]}"] += 1
        if measurement.usage_available:
            self.counters["usage.recorded"] += 1
        else:
            self.counters["usage.missing"] += 1
        return measurement

    @contextmanager
    def timed(self, engine: str, decision_type: str) -> Iterator[dict[str, Any]]:
        """Measure a block. The yielded dict is mutated with ``latency_ms`` on exit."""
        started = time.perf_counter()
        context: dict[str, Any] = {"latency_ms": 0.0}
        try:
            yield context
        finally:
            context["latency_ms"] = (time.perf_counter() - started) * 1000.0

    def counter(self, name: str) -> int:
        return int(self.counters.get(name, 0))

    def summary(self) -> dict[str, Any]:
        """Aggregate view used by the health check and future benchmark script."""
        latencies = [m.latency_ms for m in self.measurements]
        tokens_in = [m.input_tokens for m in self.measurements if m.input_tokens is not None]
        return {
            "counters": dict(self.counters),
            "measurements": len(self.measurements),
            "latency_ms": {
                "min": round(min(latencies), 3) if latencies else None,
                "max": round(max(latencies), 3) if latencies else None,
                "mean": round(sum(latencies) / len(latencies), 3) if latencies else None,
            },
            "usage": {
                "recorded": self.counter("usage.recorded"),
                "missing": self.counter("usage.missing"),
                "input_tokens_total": sum(tokens_in) if tokens_in else None,
            },
        }

    def last(self) -> Optional[Measurement]:
        return self.measurements[-1] if self.measurements else None

    def reset(self) -> None:
        self.measurements.clear()
        self.counters.clear()


def summarise_usage(usage: Optional[Usage]) -> Mapping[str, Optional[int]]:
    """JSON-safe view of usage that keeps ``None`` distinct from ``0``."""
    if usage is None:
        return {"input_tokens": None, "output_tokens": None}
    return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
