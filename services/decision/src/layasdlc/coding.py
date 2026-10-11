"""Coding adapter interface and implementations (Stage 7).

The coding adapter is the replaceable bridge to a coding model. Like the
decision engine in Stage 2, it sits behind a protocol so the execution engine
never cares which coding model is in use.

Safety contract
---------------
Implementations MUST treat all repository content, tool output and model
responses as untrusted input. They MUST NOT execute arbitrary shell commands
without passing through the policy checker in :mod:`layasdlc.permissions`.

The fake adapter exists for tests and for the acceptance scenarios that must
run without a paid coding model. It can be scripted to succeed, fail or
return malformed output, which is how the failure paths get covered for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Sequence

from .context import ContextItem
from .errors import CodingError


@dataclass(frozen=True)
class CodingResult:
    """What a coding adapter produced.

    ``changed_files`` lists paths relative to the repository root.
    ``diff`` is the unified diff text (empty when nothing changed).
    ``notes`` is free-form adapter output, treated as untrusted.
    """

    changed_files: tuple[str, ...] = ()
    diff: str = ""
    notes: str = ""
    model: str = "unknown"
    latency_ms: float = 0.0

    @property
    def success(self) -> bool:
        return bool(self.changed_files)


class CodingAdapter(Protocol):
    """The replaceable coding-model boundary.

    Implementations receive a structured prompt and return a
    :class:`CodingResult`. They never execute shell commands directly --
    that is the execution engine's job, behind its policy checks.
    """

    name: str

    def code(self, prompt: str, *, context: Sequence[ContextItem],
             objective: str) -> CodingResult:
        ...


# ======================================================================================
# Fake adapter for tests and offline acceptance scenarios
# ======================================================================================


@dataclass
class FakeCodingAdapter:
    """Scripted adapter: succeeds, fails or returns malformed output on demand.

    ``scripted_results`` is consumed in order; when exhausted the last entry
    repeats. A ``CodingResult`` with no ``changed_files`` models a refusal or
    a model that produced nothing usable.
    """

    name: str = "fake-coder"
    scripted_results: Sequence[CodingResult] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.scripted_results:
            self.scripted_results = [CodingResult(
                changed_files=("src/fix.py",),
                diff="--- a/src/fix.py\n+++ b/src/fix.py\n@@ -1 +1 @@\n-old\n+new",
                notes="fixed",
                model=self.name,
            )]

    def code(self, prompt: str, *, context: Sequence[ContextItem],
             objective: str) -> CodingResult:
        self.calls.append({
            "prompt": prompt,
            "objective": objective,
            "context_kinds": [item.kind.value for item in context],
        })
        if not self.scripted_results:
            raise CodingError("FakeCodingAdapter has no scripted results")
        index = min(len(self.calls) - 1, len(self.scripted_results) - 1)
        return self.scripted_results[index]


# ======================================================================================
# Local adapter: shells out to a configured command
# ======================================================================================


@dataclass
class LocalCodingAdapter:
    """Invokes a local coding command, passing the prompt via stdin.

    The command is configured by the caller and is responsible for making the
    model call. This adapter only handles the plumbing: writing the prompt,
    capturing stdout/stderr, timing the call, and reporting which files
    changed.

    The command is NOT given arbitrary model output to execute -- it receives a
    JSON payload on stdin and is expected to write files itself.
    """

    name: str = "local-coder"
    command: Sequence[str] = ("python", "-m", "layasdlc.coding_local")

    def code(self, prompt: str, *, context: Sequence[ContextItem],
             objective: str) -> CodingResult:
        import json
        import subprocess
        import time

        payload = json.dumps({
            "prompt": prompt,
            "objective": objective,
            "context": [item.to_dict() for item in context],
        })

        start = time.monotonic()
        try:
            result = subprocess.run(
                list(self.command),
                input=payload,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CodingError(f"coding adapter failed: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000

        if result.returncode != 0:
            raise CodingError(
                f"coding adapter exited {result.returncode}: {result.stderr.strip()}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CodingError(
                f"coding adapter returned invalid JSON: {exc}") from exc

        return CodingResult(
            changed_files=tuple(data.get("changed_files", ())),
            diff=data.get("diff", ""),
            notes=data.get("notes", ""),
            model=data.get("model", self.name),
            latency_ms=latency_ms,
        )


__all__ = [
    "CodingAdapter",
    "CodingResult",
    "CodingError",
    "FakeCodingAdapter",
    "LocalCodingAdapter",
]
