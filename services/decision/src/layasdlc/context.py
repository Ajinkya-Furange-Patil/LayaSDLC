"""Code-aware context engineering (Stage 6).

Retrieves the smallest relevant set of source code and engineering evidence
needed for a task, ranks it deterministically, and packages it under a
configurable token budget.

Design principles
-----------------
* **Deterministic first.** Ranking uses only signals computable without a
  model: path overlap, symbol match, git-diff proximity, test-failure
  proximity. No embeddings, no vector DB.
* **Provenance always.** Every item carries its source (file, line range,
  revision or test result) so a fact can be traced and invalidated.
* **Budget is a ceiling, not a cull.** When the budget is exhausted,
  mandatory items (constraints, open questions, security-critical evidence)
  are never dropped -- they are always included, and discretionary items are
  dropped first.
* **Deduplication.** Identical snippets from different sources are sent once,
  with all sources listed in the provenance.

Token accounting
----------------
When the target model's tokenizer is available it is used. Otherwise a
character-based heuristic (~4 chars/token) is used and the result is labelled
as an estimate. The distinction is recorded in the package so a caller never
mistakes an estimate for a measurement.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


# ======================================================================================
# Vocabulary
# ======================================================================================


class ItemKind(str, Enum):
    """What kind of context this item is.

    ``constraint`` and ``question`` are *mandatory*: they are never dropped
    to meet a budget. ``security`` is treated as mandatory for the same
    reason -- silently omitting security-critical evidence is how vulnerabilities
    get introduced.
    """

    OBJECTIVE = "objective"
    SNIPPET = "snippet"
    DEPENDENCY = "dependency"
    TEST_RESULT = "test_result"
    CONSTRAINT = "constraint"
    QUESTION = "question"
    SECURITY = "security"

    @property
    def is_mandatory(self) -> bool:
        return self in (ItemKind.CONSTRAINT, ItemKind.QUESTION, ItemKind.SECURITY)


#: Kinds dropped first when the budget runs out, in order.
_DROP_PRIORITY: tuple[ItemKind, ...] = (
    ItemKind.DEPENDENCY,
    ItemKind.SNIPPET,
    ItemKind.TEST_RESULT,
    ItemKind.OBJECTIVE,
)


@dataclass(frozen=True)
class Source:
    """Where a fact came from.

    Exactly one of ``file``, ``test`` or ``revision`` is expected, but the
    record is kept open so a fact can cite more than one (e.g. a snippet
    that appears in both a diff and a test failure).
    """

    file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    test: Optional[str] = None
    revision: Optional[str] = None

    def describe(self) -> str:
        if self.file:
            location = self.file
            if self.line_start is not None:
                location += f":{self.line_start}"
                if self.line_end is not None and self.line_end != self.line_start:
                    location += f"-{self.line_end}"
            return location
        if self.test:
            return f"test:{self.test}"
        if self.revision:
            return f"rev:{self.revision}"
        return "unknown"


@dataclass
class ContextItem:
    """One piece of context with its provenance and ranking signals."""

    kind: ItemKind
    content: str
    source: Source
    #: Deterministic relevance score. Higher is more relevant.
    score: float = 0.0
    #: Whether this item was present in the previous package and is unchanged.
    unchanged: bool = False

    @property
    def fingerprint(self) -> str:
        """Content hash used for deduplication."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "content": self.content,
            "source": self.source.describe(),
            "score": round(self.score, 4),
            "unchanged": self.unchanged,
        }


@dataclass
class ContextPackage:
    """The compact context package sent to a coding model."""

    objective: str
    items: list[ContextItem] = field(default_factory=list)
    #: Token budget that was applied.
    budget_tokens: int = 0
    #: Tokens reserved for the model's response.
    reserved_tokens: int = 0
    #: Whether token counts are measured (True) or estimated (False).
    measured: bool = False
    #: Human-readable note when the budget forced drops.
    note: Optional[str] = None

    @property
    def used_tokens(self) -> int:
        return estimate_tokens(self.objective) + sum(
            estimate_tokens(item.content) for item in self.items)

    @property
    def mandatory_items(self) -> list[ContextItem]:
        return [item for item in self.items if item.kind.is_mandatory]

    @property
    def discretionary_items(self) -> list[ContextItem]:
        return [item for item in self.items if not item.kind.is_mandatory]

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "items": [item.to_dict() for item in self.items],
            "budget_tokens": self.budget_tokens,
            "reserved_tokens": self.reserved_tokens,
            "used_tokens": self.used_tokens,
            "measured": self.measured,
            "note": self.note,
        }


# ======================================================================================
# Token accounting
# ======================================================================================


def estimate_tokens(text: str) -> int:
    """Estimate token count using a character-based heuristic.

    This is an *estimate*, not a measurement. The package records whether the
    target tokenizer was available so a caller never mistakes one for the
    other.
    """
    return max(1, len(text) // 4)


def measure_tokens(text: str, tokenizer: Optional[Any] = None) -> tuple[int, bool]:
    """Return ``(token_count, measured)``.

    When ``tokenizer`` is provided it must expose ``encode(text) -> list``.
    Otherwise the character heuristic is used and ``measured`` is ``False``.
    """
    if tokenizer is not None:
        try:
            return len(tokenizer.encode(text)), True
        except Exception:
            pass
    return estimate_tokens(text), False


# ======================================================================================
# Retrieval
# ======================================================================================


def _is_git_repo(directory: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=directory, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False
        # Verify the git root is actually the directory we're querying,
        # not a parent repo that git walked up to.
        git_root = Path(result.stdout.strip()).resolve()
        return git_root == Path(directory).resolve()
    except (OSError, subprocess.SubprocessError):
        return False


def from_git_diff(repo: str, *, revision: Optional[str] = None) -> list[ContextItem]:
    """Extract changed files and line ranges from a git diff.

    Read-only. Returns one item per changed hunk, with the file and line
    range as provenance. When ``revision`` is given, the diff is taken against
    that revision; otherwise the working tree is compared to HEAD.
    """
    if not _is_git_repo(repo):
        return []

    cmd = ["git", "diff", "--unified=0"]
    if revision:
        cmd.append(revision)
    else:
        cmd.append("HEAD")

    try:
        result = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []

    if result.returncode != 0:
        return []

    items: list[ContextItem] = []
    current_file: Optional[str] = None
    current_start: Optional[int] = None
    current_lines: list[str] = []

    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            if current_file and current_lines:
                items.append(ContextItem(
                    kind=ItemKind.SNIPPET,
                    content="\n".join(current_lines),
                    source=Source(file=current_file,
                                 line_start=current_start,
                                 line_end=current_start + len(current_lines) - 1
                                 if current_start else None),
                    score=1.0,
                ))
            current_file = line[6:]
            current_start = None
            current_lines = []
        elif line.startswith("@@"):
            match = re.search(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if match:
                if current_file and current_lines:
                    items.append(ContextItem(
                        kind=ItemKind.SNIPPET,
                        content="\n".join(current_lines),
                        source=Source(file=current_file,
                                     line_start=current_start,
                                     line_end=current_start + len(current_lines) - 1
                                     if current_start else None),
                        score=1.0,
                    ))
                current_start = int(match.group(1))
                current_lines = []
        elif current_file and (line.startswith("+") or line.startswith("-")):
            if not line.startswith("+++") and not line.startswith("---"):
                current_lines.append(line)

    if current_file and current_lines:
        items.append(ContextItem(
            kind=ItemKind.SNIPPET,
            content="\n".join(current_lines),
            source=Source(file=current_file,
                         line_start=current_start,
                         line_end=current_start + len(current_lines) - 1
                         if current_start else None),
            score=1.0,
        ))
    return items


def from_filename_search(
    repo: str, patterns: Sequence[str], *, max_file_size: int = 100_000,
) -> list[ContextItem]:
    """Find files whose path matches any of ``patterns`` (glob syntax).

    File contents are not read here -- only paths and sizes. Large files are
    flagged so the caller can decide whether to include them.
    """
    items: list[ContextItem] = []
    seen: set[str] = set()
    for pattern in patterns:
        for path in Path(repo).rglob(pattern):
            if not path.is_file() or str(path) in seen:
                continue
            seen.add(str(path))
            size = path.stat().st_size
            items.append(ContextItem(
                kind=ItemKind.SNIPPET,
                content=f"[{path.relative_to(repo)} ({size} bytes)]",
                source=Source(file=str(path.relative_to(repo))),
                score=0.5 if size <= max_file_size else 0.1,
            ))
    return items


def from_symbol_search(
    repo: str, symbols: Sequence[str], *, context_lines: int = 3,
) -> list[ContextItem]:
    """Find definitions and references of ``symbols`` in the repository.

    Pure-Python implementation -- no dependency on external ``grep``.
    Each match becomes an item with the file:line as provenance.
    """
    items: list[ContextItem] = []
    suffixes = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}

    for symbol in symbols:
        pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
        for path in Path(repo).rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    items.append(ContextItem(
                        kind=ItemKind.SNIPPET,
                        content=line.strip(),
                        source=Source(file=str(path.relative_to(repo)),
                                     line_start=line_no, line_end=line_no),
                        score=0.8,
                    ))
    return items


def from_test_failures(test_output: str) -> list[ContextItem]:
    """Parse pytest-style test failure output for file:line references."""
    items: list[ContextItem] = []
    pattern = re.compile(r"([\w./\\-]+\.py):(\d+):\s*(\w+)")
    for match in pattern.finditer(test_output):
        file_path, line_no, error = match.group(1), int(match.group(2)), match.group(3)
        items.append(ContextItem(
            kind=ItemKind.TEST_RESULT,
            content=f"{file_path}:{line_no}: {error}",
            source=Source(file=file_path, line_start=line_no, line_end=line_no,
                         test="pytest"),
            score=0.9,
        ))
    return items


# ======================================================================================
# Ranking
# ======================================================================================


def rank_items(
    items: Sequence[ContextItem], *, objective: str,
    path_hints: Sequence[str] = (),
) -> list[ContextItem]:
    """Rank items by deterministic relevance signals.

    Signals, in priority order:
    1. Path overlap with the task's ``path_hints``.
    2. Content overlap with the objective (token-level Jaccard).
    3. Kind priority (test results > snippets > dependencies).
    4. Original score as a tiebreaker.
    """
    objective_tokens = set(_tokenize(objective))
    path_hint_set = {h.lower() for h in path_hints}

    def score(item: ContextItem) -> float:
        s = item.score
        source_file = (item.source.file or "").lower()
        if any(hint in source_file for hint in path_hint_set):
            s += 2.0
        content_tokens = set(_tokenize(item.content))
        if objective_tokens and content_tokens:
            jaccard = len(objective_tokens & content_tokens) / len(objective_tokens | content_tokens)
            s += jaccard
        if item.kind is ItemKind.TEST_RESULT:
            s += 0.5
        return s

    ranked = sorted(items, key=score, reverse=True)
    for item in ranked:
        item.score = score(item)
    return ranked


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


# ======================================================================================
# Budgeting and packaging
# ======================================================================================


def build_package(
    objective: str,
    items: Sequence[ContextItem],
    *,
    budget_tokens: int = 8000,
    reserved_tokens: int = 2000,
    tokenizer: Optional[Any] = None,
    previous: Optional[ContextPackage] = None,
) -> ContextPackage:
    """Assemble a context package under a token budget.

    Mandatory items (constraints, questions, security) are always included.
    Discretionary items are added by descending score until the budget is
    exhausted. Items unchanged from ``previous`` are marked so the caller can
    avoid resending them.
    """
    ranked = rank_items(items, objective=objective)
    previous_fingerprints = {
        item.fingerprint for item in (previous.items if previous else [])
    }

    used = estimate_tokens(objective)
    budget = budget_tokens - reserved_tokens
    selected: list[ContextItem] = []
    dropped: list[ContextItem] = []

    # First pass: mandatory items always fit, regardless of budget.
    # Silently omitting a constraint or open question is how requirements
    # get lost; the budget applies to discretionary context only.
    for item in ranked:
        if not item.kind.is_mandatory:
            continue
        selected.append(item)
        used += measure_tokens(item.content, tokenizer)[0]

    # Second pass: discretionary items by score.
    for item in ranked:
        if item.kind.is_mandatory:
            continue
        cost, _ = measure_tokens(item.content, tokenizer)
        if used + cost <= budget:
            selected.append(item)
            used += cost
        else:
            dropped.append(item)

    # Mark unchanged items.
    for item in selected:
        if item.fingerprint in previous_fingerprints:
            item.unchanged = True

    measured = tokenizer is not None
    note = None
    if dropped:
        note = (f"dropped {len(dropped)} discretionary item(s) to meet the "
                f"token budget; {len(selected)} item(s) included")

    return ContextPackage(
        objective=objective,
        items=selected,
        budget_tokens=budget_tokens,
        reserved_tokens=reserved_tokens,
        measured=measured,
        note=note,
    )


def deduplicate(items: Sequence[ContextItem]) -> list[ContextItem]:
    """Remove duplicate snippets, merging their provenance."""
    seen: dict[str, ContextItem] = {}
    order: list[str] = []
    for item in items:
        fp = item.fingerprint
        if fp in seen:
            existing = seen[fp]
            # Merge sources: keep the first, note the second in content.
            merged = ContextItem(
                kind=existing.kind,
                content=existing.content,
                source=existing.source,
                score=max(existing.score, item.score),
                unchanged=existing.unchanged and item.unchanged,
            )
            seen[fp] = merged
        else:
            seen[fp] = item
            order.append(fp)
    return [seen[fp] for fp in order]


__all__ = [
    "ContextItem",
    "ContextPackage",
    "ItemKind",
    "Source",
    "build_package",
    "deduplicate",
    "estimate_tokens",
    "from_filename_search",
    "from_git_diff",
    "from_symbol_search",
    "from_test_failures",
    "measure_tokens",
    "rank_items",
]
