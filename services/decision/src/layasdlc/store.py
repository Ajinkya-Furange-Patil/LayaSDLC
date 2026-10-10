"""SQLite persistence for workflow tasks (Stage 4).

Standard library only -- ``sqlite3`` ships with Python, so persistence costs no
new dependency and no network access.

What is stored
--------------
Everything :class:`~layasdlc.workflow.WorkflowTask` carries, broken into
normalised rows rather than one opaque JSON blob:

* ``tasks`` -- one row per task: identity, objective, safety finding, policy,
  kind, phase, approval state, retry counters.
* ``history`` -- one row per committed :class:`WorkflowAction`, with the
  justification (source, reason, rules) that produced it.
* ``evidence`` -- one row per test result reported back.
* ``context_facts`` -- concise structured facts with a ``kind`` that
  distinguishes verified facts from requirements, hypotheses, open questions and
  execution results.

What is deliberately *not* stored
---------------------------------
* conversation transcripts -- only structured facts with provenance;
* credentials, API keys or endpoint URLs;
* the full text of a diff or a file -- evidence references a command and its
  outcome, not the payload.

Staleness
---------
Every row carries ``created_at``. A fact's validity is established by comparing
the repository revision and working-tree status recorded on the task against the
current ones; when they differ the fact is marked stale rather than trusted.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .contracts import Evidence, SafetyClass, TaskKind, TaskState
from .errors import DecisionServiceError
from .policy import PolicyConfig
from .safety import SafetyFinding
from .workflow import (
    ActionRecord,
    Approval,
    TaskPhase,
    WorkflowAction,
    WorkflowTask,
    new_task,
)


class StoreError(DecisionServiceError):
    """Persistence failed in a way the caller can act on."""

    reason = "store_error"


# ======================================================================================
# Schema and migrations
# ======================================================================================

#: Bumped on every schema change. Migrations run in order from the stored value
#: to this one, so a database written by an older build is upgraded in place
#: rather than refused.
STORE_SCHEMA_VERSION = 1

_MIGRATIONS: tuple[str, ...] = (
    # 0 -> 1: initial schema
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tasks (
        task_id            TEXT PRIMARY KEY,
        subject            TEXT NOT NULL,
        body               TEXT NOT NULL DEFAULT '',
        path               TEXT,
        safety_class       TEXT NOT NULL,
        safety_reason      TEXT NOT NULL DEFAULT '',
        safety_matched     TEXT NOT NULL DEFAULT '[]',
        requires_approval  INTEGER NOT NULL DEFAULT 0,
        policy             TEXT NOT NULL DEFAULT '{}',
        kind               TEXT,
        phase              TEXT NOT NULL,
        approval_granted   INTEGER,
        approval_by        TEXT,
        approval_reason    TEXT,
        awaiting_from      TEXT,
        retries            INTEGER NOT NULL DEFAULT 0,
        last_error         TEXT,
        last_signature     TEXT,
        failure_signatures TEXT NOT NULL DEFAULT '{}',
        repo_revision      TEXT,
        working_tree       TEXT,
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS history (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id    TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        seq        INTEGER NOT NULL,
        action     TEXT NOT NULL,
        from_phase TEXT NOT NULL,
        to_phase   TEXT NOT NULL,
        source     TEXT NOT NULL,
        reason     TEXT NOT NULL,
        rules      TEXT NOT NULL DEFAULT '[]',
        decision_id TEXT,
        confidence REAL,
        error      TEXT,
        at         TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_history_task ON history(task_id, seq);

    CREATE TABLE IF NOT EXISTS evidence (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id     TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        seq         INTEGER NOT NULL,
        test_command TEXT NOT NULL,
        tests_passed INTEGER NOT NULL,
        artifact    TEXT,
        checked_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence(task_id, seq);

    CREATE TABLE IF NOT EXISTS context_facts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id    TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        kind       TEXT NOT NULL,
        content    TEXT NOT NULL,
        source     TEXT NOT NULL,
        revision   TEXT,
        stale      INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_facts_task ON context_facts(task_id, kind);
    """,
)


def _apply_migrations(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` up to :data:`STORE_SCHEMA_VERSION`, returning the new version."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    version = int(row[0]) if row else 0

    for index, sql in enumerate(_MIGRATIONS[version:], start=version):
        conn.executescript(sql)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(index + 1),))
    return version if not _MIGRATIONS[version:] else index + 1


def _coerce_json(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


# ======================================================================================
# The store
# ======================================================================================


@dataclass
class TaskStore:
    """SQLite-backed persistence for workflow tasks.

    Not a repository pattern hiding the domain: it is a faithful projection of
    :class:`WorkflowTask` into rows, so what is written is exactly what
    :meth:`load` reconstructs.
    """

    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # --- connection handling ----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # --- lifecycle --------------------------------------------------------------------

    def migrate(self) -> int:
        """Create or upgrade the schema. Returns the schema version applied."""
        with self._connect() as conn:
            version = _apply_migrations(conn)
            conn.commit()
        return version

    # --- writing ----------------------------------------------------------------------

    def save(self, task: WorkflowTask, *, repo_revision: Optional[str] = None,
             working_tree: Optional[str] = None) -> None:
        """Persist ``task``, replacing any prior state for its id.

        History, evidence and failure signatures are written atomically with the
        task row, so a crash mid-save cannot leave a task whose counters disagree
        with its history.

        ``repo_revision`` and ``working_tree`` default to whatever the task
        already carries, so callers that set them once do not repeat themselves.
        Passing them explicitly overrides -- that is how a caller records a
        revision it has just observed.
        """
        revision = task.repo_revision if repo_revision is None else repo_revision
        tree = task.working_tree if working_tree is None else working_tree
        task.repo_revision = revision
        task.working_tree = tree
        now = _now()
        policy = task.policy
        finding = task.finding
        approval = task.approval
        signatures = json.dumps(dict(task.failure_signatures))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    task_id, subject, body, path,
                    safety_class, safety_reason, safety_matched, requires_approval,
                    policy, kind, phase,
                    approval_granted, approval_by, approval_reason, awaiting_from,
                    retries, last_error, last_signature, failure_signatures,
                    repo_revision, working_tree, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task.task_id, task.task.subject, task.task.body, task.task.path,
                    finding.safety_class.value, finding.reason,
                    json.dumps(list(finding.matched)), int(finding.requires_approval),
                    json.dumps({
                        "min_confidence": policy.min_confidence,
                        "fallback_enabled": policy.fallback_enabled,
                        "missing_confidence_is_abstain": policy.missing_confidence_is_abstain,
                        "enforce_test_evidence": policy.enforce_test_evidence,
                    }),
                    task.kind.value if task.kind else None,
                    task.phase.value,
                    None if approval is None else int(approval.granted),
                    approval.by if approval else None,
                    approval.reason if approval else None,
                    task.awaiting_from.value if task.awaiting_from else None,
                    task.retries, task.last_error, task.last_signature, signatures,
                    revision, tree,
                    now, now,
                ),
            )

            # Replace history and evidence wholesale: they are append-only in the
            # domain model, so a full rewrite is safe and keeps seq contiguous.
            conn.execute("DELETE FROM history WHERE task_id = ?", (task.task_id,))
            for seq, record in enumerate(task.history, start=1):
                conn.execute(
                    """
                    INSERT INTO history
                        (task_id, seq, action, from_phase, to_phase, source,
                         reason, rules, decision_id, confidence, error, at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (task.task_id, seq, record.action.value,
                     record.from_phase.value, record.to_phase.value, record.source,
                     record.reason, json.dumps(list(record.rules)),
                     record.decision_id, record.confidence, record.error, record.at),
                )

            conn.execute("DELETE FROM evidence WHERE task_id = ?", (task.task_id,))
            for seq, item in enumerate(task.evidence, start=1):
                conn.execute(
                    """
                    INSERT INTO evidence
                        (task_id, seq, test_command, tests_passed, artifact, checked_at)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (task.task_id, seq, item.test_command, int(item.tests_passed),
                     item.artifact, item.checked_at),
                )
            conn.commit()

    # --- reading ----------------------------------------------------------------------

    def load(self, task_id: str) -> Optional[WorkflowTask]:
        """Reconstruct the task, or ``None`` if it is not stored."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                return None

            history = [
                ActionRecord(
                    action=WorkflowAction(record["action"]),
                    from_phase=TaskPhase(record["from_phase"]),
                    to_phase=TaskPhase(record["to_phase"]),
                    source=record["source"],
                    reason=record["reason"],
                    rules=tuple(_coerce_json(record["rules"], [])),
                    decision_id=record["decision_id"],
                    confidence=record["confidence"],
                    error=record["error"],
                    evidence=self._evidence_at(conn, task_id, record["seq"]),
                    at=record["at"],
                )
                for record in conn.execute(
                    "SELECT * FROM history WHERE task_id = ? ORDER BY seq", (task_id,))
            ]

            approval: Optional[Approval] = None
            if row["approval_by"] is not None:
                approval = Approval(
                    granted=bool(row["approval_granted"]),
                    by=row["approval_by"],
                    reason=row["approval_reason"],
                    at=row["updated_at"],
                )

            state = TaskState(
                task_id=row["task_id"],
                subject=row["subject"],
                body=row["body"],
                path=row["path"],
            )
            finding = SafetyFinding(
                safety_class=SafetyClass(row["safety_class"]),
                matched=tuple(_coerce_json(row["safety_matched"], [])),
                requires_approval=bool(row["requires_approval"]),
            )
            policy_row = _coerce_json(row["policy"], {})
            policy = PolicyConfig(
                min_confidence=float(policy_row.get("min_confidence", 0.35)),
                fallback_enabled=bool(policy_row.get("fallback_enabled", True)),
                missing_confidence_is_abstain=bool(
                    policy_row.get("missing_confidence_is_abstain", True)),
                enforce_test_evidence=bool(
                    policy_row.get("enforce_test_evidence", True)),
            )

            task = new_task(state, finding=finding, policy=policy)
            task.kind = TaskKind(row["kind"]) if row["kind"] else None
            task.phase = TaskPhase(row["phase"])
            task.history = history
            task.evidence = [
                Evidence(
                    test_command=item["test_command"],
                    tests_passed=bool(item["tests_passed"]),
                    artifact=item["artifact"],
                    checked_at=item["checked_at"],
                )
                for item in conn.execute(
                    "SELECT * FROM evidence WHERE task_id = ? ORDER BY seq", (task_id,))
            ]
            task.approval = approval
            task.awaiting_from = (
                TaskPhase(row["awaiting_from"]) if row["awaiting_from"] else None)
            task.retries = row["retries"]
            task.last_error = row["last_error"]
            task.last_signature = row["last_signature"]
            task.failure_signatures = _coerce_json(row["failure_signatures"], {})
            task.repo_revision = row["repo_revision"]
            task.working_tree = row["working_tree"]
            return task

    def _evidence_at(self, conn: sqlite3.Connection, task_id: str,
                     history_seq: int) -> Optional[Evidence]:
        """Find the evidence attached to a given history entry, if any.

        Evidence rows carry their own ``seq`` ordered the same way as history, so
        the join is positional rather than requiring a separate foreign key.
        """
        row = conn.execute(
            "SELECT * FROM evidence WHERE task_id = ? AND seq = ?",
            (task_id, history_seq)).fetchone()
        if row is None:
            return None
        return Evidence(
            test_command=row["test_command"],
            tests_passed=bool(row["tests_passed"]),
            artifact=row["artifact"],
            checked_at=row["checked_at"],
        )

    # --- listing and deletion ----------------------------------------------------------

    def list_tasks(self) -> list[dict[str, Any]]:
        """Every task, most recently updated first -- the resume menu."""
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT task_id, subject, kind, phase, retries, updated_at "
                "FROM tasks ORDER BY updated_at DESC")]

    def delete(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.commit()

    # --- context facts ----------------------------------------------------------------

    def add_fact(self, task_id: str, *, kind: str, content: str,
                 source: str, revision: Optional[str] = None) -> None:
        """Record one concise, structured fact.

        ``kind`` is one of ``verified`` / ``requirement`` / ``hypothesis`` /
        ``question`` / ``execution``. Never a transcript: a fact is a single
        sentence with provenance, not a conversation log.
        """
        allowed = {"verified", "requirement", "hypothesis", "question", "execution"}
        if kind not in allowed:
            raise StoreError(
                f"unknown fact kind {kind!r}; expected one of {sorted(allowed)}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO context_facts (task_id, kind, content, source, revision,
                                          stale, created_at)
                VALUES (?,?,?,?,?,0,?)
                """,
                (task_id, kind, content, source, revision, _now()),
            )
            conn.commit()

    def facts(self, task_id: str, *, kind: Optional[str] = None,
              include_stale: bool = False) -> list[dict[str, Any]]:
        """Facts for a task, optionally filtered by kind and staleness."""
        query = "SELECT * FROM context_facts WHERE task_id = ?"
        params: list[Any] = [task_id]
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        if not include_stale:
            query += " AND stale = 0"
        query += " ORDER BY id"

        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def mark_stale(self, task_id: str, *, kind: Optional[str] = None) -> int:
        """Invalidate facts whose inputs have changed.

        Returns how many rows were marked. Called with ``kind=None`` to
        invalidate everything when the working tree moves underneath the task.
        """
        query = "UPDATE context_facts SET stale = 1 WHERE task_id = ? AND stale = 0"
        params: list[Any] = [task_id]
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        with self._connect() as conn:
            conn.execute(query, params)
            conn.commit()
            return conn.execute("SELECT changes()").fetchone()[0]


def _now() -> str:
    from .contracts import utc_now
    return utc_now()


__all__ = [
    "STORE_SCHEMA_VERSION",
    "StoreError",
    "TaskStore",
]
