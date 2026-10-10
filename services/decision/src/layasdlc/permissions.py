"""Tool permission enforcement (Stage 2 requirement 8).

The rule this module exists to guarantee:

    **A model-generated decision never widens tool access.**

Two independent layers enforce it:

1. **Pre-narrowing** -- for decision types whose options *are* tools, the
   controller removes non-permitted options from ``allowed_options`` *before*
   asking any engine. The model is then structurally incapable of selecting an
   option it was never offered.
2. **Post-checking** -- after validation, the selected option is asserted
   against the policy again. This is defence in depth: it catches a fallback
   path, a future engine that ignores the question, and any refactor that
   forgets step 1.

The policy is supplied by the *caller* and is never derived from model output,
model confidence, or the decision's own ``rationale``. A confident "run_tests"
is not permission to run tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Optional

from .contracts import DecisionEnvelope, DecisionType
from .errors import PermissionDenied

#: Decision types whose options are executable tool identifiers.
TOOL_BEARING_TYPES: FrozenSet[str] = frozenset({DecisionType.WORKFLOW_SELECTION.value})


@dataclass(frozen=True)
class ToolPermissionPolicy:
    """An explicit allow-list of tools this controller may invoke.

    Immutable and constructed by the caller, so it cannot be mutated by anything
    the engine returns.
    """

    allowed_tools: FrozenSet[str]

    @classmethod
    def of(cls, tools: Iterable[str]) -> "ToolPermissionPolicy":
        return cls(allowed_tools=frozenset(tools))

    @classmethod
    def read_only(cls) -> "ToolPermissionPolicy":
        """The safe default: inspect, but change nothing."""
        return cls.of({"read_investigate"})

    @classmethod
    def full(cls) -> "ToolPermissionPolicy":
        """Every workflow tool. Opt-in; never the default."""
        return cls.of({"edit_code", "run_tests", "read_investigate", "update_docs"})

    def permits(self, tool: str) -> bool:
        return tool in self.allowed_tools

    def guard(self, tool: str, *, context: Optional[str] = None) -> None:
        """Raise :class:`PermissionDenied` unless ``tool`` is allowed."""
        if self.permits(tool):
            return
        where = f" ({context})" if context else ""
        raise PermissionDenied(
            f"tool {tool!r} is not permitted{where}; allowed: {sorted(self.allowed_tools)}",
            tool=tool,
            required_permission=tool,
        )


def narrow_options(decision_type: str, allowed_options: Iterable[str],
                   policy: ToolPermissionPolicy) -> tuple[str, ...]:
    """Layer 1: drop options the policy would refuse, before any engine is called.

    For non-tool-bearing decision types the option list is returned untouched --
    classification choices are not permissions and must not be filtered.

    Raises:
        PermissionDenied: nothing usable remains after filtering.
    """
    options = tuple(allowed_options)
    if decision_type not in TOOL_BEARING_TYPES:
        return options

    permitted = tuple(option for option in options if policy.permits(option))
    if not permitted:
        raise PermissionDenied(
            f"no permitted option remains among {list(options)}; "
            f"allowed: {sorted(policy.allowed_tools)}",
            tool=",".join(options) or "<none>",
        )
    return permitted


def guard_decision(envelope: DecisionEnvelope, policy: ToolPermissionPolicy) -> None:
    """Layer 2: re-assert the policy against a validated envelope."""
    if envelope.decision_type not in TOOL_BEARING_TYPES:
        return
    policy.guard(envelope.selected_option, context=f"decision {envelope.decision_id}")
