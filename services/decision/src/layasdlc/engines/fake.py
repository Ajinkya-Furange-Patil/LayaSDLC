"""Scripted engine for unit tests.

Development rule: tests must not need a paid API or a downloaded model, so unit
tests drive the controller with this engine. It can answer, hesitate or fail in
order, which is how the timeout / malformed / failure paths get covered for real
rather than by mocking the controller itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from ..contracts import Usage
from ..engine import EngineAnswer, EngineRequest


def answer(option: str, *, confidence: Optional[float] = 0.9, allowed: Sequence[str] = (),
           rationale: Optional[str] = None, model: str = "fake/1.0",
           model_version: Optional[str] = "1.0", latency_ms: Optional[float] = 1.0,
           input_tokens: Optional[int] = None, output_tokens: Optional[int] = None,
           probabilities: Optional[dict] = None) -> EngineAnswer:
    """Build an :class:`EngineAnswer`, with usage only when explicitly supplied."""
    probs = dict(probabilities) if probabilities else {}
    if not probs and allowed and confidence is not None:
        # Spread the remainder over the other options so the distribution is sane.
        rest = (1.0 - confidence) / max(1, len(allowed) - 1)
        probs = {candidate: (confidence if candidate == option else rest)
                 for candidate in allowed}
    return EngineAnswer(
        selected_option=option,
        confidence=confidence,
        rationale=rationale,
        model=model,
        model_version=model_version,
        latency_ms=latency_ms,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        probabilities=probs,
    )


@dataclass
class Scripted:
    """One scripted outcome: exactly one of ``answer`` or ``error``."""

    answer: Optional[EngineAnswer] = None
    error: Optional[BaseException] = None
    #: Sleep before responding, used to exercise the controller's watchdog.
    delay_s: float = 0.0

    def __post_init__(self) -> None:
        if (self.answer is None) == (self.error is None):
            raise ValueError("a Scripted step needs exactly one of answer= or error=")


@dataclass
class FakeEngine:
    """Replays a script, then falls back to ``default``.

    Records every :class:`EngineRequest` it receives so a test can assert on what
    the controller actually sent -- option narrowing and timeouts included.
    """

    script: Sequence[Scripted] = field(default_factory=list)
    default: Optional[EngineAnswer] = None
    handler: Optional[Callable[[EngineRequest], EngineAnswer]] = None
    is_available: bool = True
    name: str = "fake"
    version: Optional[str] = "test-only"
    records: list[EngineRequest] = field(default_factory=list)

    def available(self) -> bool:
        return self.is_available

    def decide(self, request: EngineRequest) -> EngineAnswer:
        self.records.append(request)

        if self.handler is not None:
            result = self.handler(request)
            if isinstance(result, BaseException):
                raise result
            return result

        index = len(self.records) - 1
        if index < len(self.script):
            step = self.script[index]
        elif self.default is not None:
            return self.default
        elif self.script:
            step = self.script[-1]
        else:
            raise ValueError("FakeEngine has an empty script and no default")

        if step.delay_s:
            time.sleep(step.delay_s)
        if step.error is not None:
            raise step.error
        assert step.answer is not None
        return step.answer
