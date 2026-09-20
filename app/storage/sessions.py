"""SQLite persistence for short-term sessions and trace events."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.domain.errors import NotFoundError, PolicyDeniedError, StorageError
from app.domain.models import AgentStateModel


class SessionStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.settings.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL DEFAULT '',
                        state_json TEXT NOT NULL DEFAULT '{}',
                        project_id TEXT NOT NULL DEFAULT 'default',
                        mode TEXT NOT NULL DEFAULT 'agent',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS trace_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id TEXT NOT NULL,
                        event_name TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_trace_events ON trace_events(trace_id, id);
                    """
                )
                self._ensure_column(
                    connection, "sessions", "project_id", "TEXT NOT NULL DEFAULT 'default'"
                )
                self._ensure_column(
                    connection, "sessions", "mode", "TEXT NOT NULL DEFAULT 'agent'"
                )
        except sqlite3.Error as exc:
            raise StorageError() from exc

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def ensure_session(
        self,
        session_id: str | None,
        *,
        project_id: str,
        mode: str,
        title: str,
    ) -> str:
        resolved_id = session_id or f"session-{uuid4().hex}"
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT project_id, mode FROM sessions WHERE session_id = ?",
                    (resolved_id,),
                ).fetchone()
                if row is not None:
                    if row["project_id"] != project_id:
                        raise PolicyDeniedError("会话不能跨项目复用")
                    if row["mode"] != mode:
                        raise PolicyDeniedError("会话模式不匹配")
                    return resolved_id
                connection.execute(
                    """INSERT INTO sessions
                       (session_id, title, summary, state_json, project_id, mode, created_at, updated_at)
                       VALUES (?, ?, '', '{}', ?, ?, ?, ?)""",
                    (resolved_id, title[:80], project_id, mode, now, now),
                )
        except PolicyDeniedError:
            raise
        except sqlite3.Error as exc:
            raise StorageError() from exc
        return resolved_id

    def save_state(self, state: AgentStateModel, title: str | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO sessions
                        (session_id, title, summary, state_json, project_id, mode, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'agent', ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        summary = excluded.summary,
                        state_json = excluded.state_json,
                        project_id = excluded.project_id,
                        mode = excluded.mode,
                        updated_at = excluded.updated_at
                    """,
                    (
                        state.session_id,
                        title or state.user_goal[:80],
                        state.summary,
                        state.model_dump_json(),
                        state.project_id,
                        now,
                        now,
                    ),
                )
        except sqlite3.Error as exc:
            raise StorageError() from exc

    def get_state(self, session_id: str) -> AgentStateModel:
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT state_json FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError() from exc
        if row is None:
            raise NotFoundError("会话不存在")
        return AgentStateModel.model_validate_json(row["state_json"])

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        if role not in {"user", "assistant", "tool"}:
            raise StorageError("会话角色无效")
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO turns(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                    (session_id, role, content, datetime.now(UTC).isoformat()),
                )
                rows = connection.execute(
                    "SELECT id, role, content FROM turns WHERE session_id = ? ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
                overflow = rows[:-10]
                if overflow:
                    existing = connection.execute(
                        "SELECT summary FROM sessions WHERE session_id = ?", (session_id,)
                    ).fetchone()
                    previous = existing["summary"] if existing else ""
                    addition = "\n".join(
                        f"{row['role']}: {' '.join(row['content'].split())[:300]}"
                        for row in overflow
                    )
                    summary = "\n".join(part for part in (previous, addition) if part)[-2000:]
                    connection.execute(
                        "UPDATE sessions SET summary = ?, updated_at = ? WHERE session_id = ?",
                        (summary, datetime.now(UTC).isoformat(), session_id),
                    )
                    placeholders = ",".join("?" for _ in overflow)
                    connection.execute(
                        f"DELETE FROM turns WHERE id IN ({placeholders})",
                        tuple(row["id"] for row in overflow),
                    )
        except sqlite3.Error as exc:
            raise StorageError() from exc

    def recent_turns(self, session_id: str) -> list[dict[str, str]]:
        try:
            with closing(self._connect()) as connection, connection:
                rows = connection.execute(
                    "SELECT role, content, created_at FROM turns WHERE session_id = ? ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError() from exc
        return [dict(row) for row in rows]

    def get_context(self, session_id: str) -> dict[str, Any]:
        try:
            with closing(self._connect()) as connection, connection:
                session = connection.execute(
                    "SELECT project_id, mode, summary FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError() from exc
        if session is None:
            raise NotFoundError("会话不存在")
        return {
            "project_id": session["project_id"],
            "mode": session["mode"],
            "summary": session["summary"],
            "turns": self.recent_turns(session_id),
        }

    def record_trace(self, trace_id: str, event_name: str, payload: dict[str, Any] | None = None) -> None:
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO trace_events(trace_id, event_name, payload_json, created_at) VALUES (?, ?, ?, ?)",
                    (trace_id, event_name, json.dumps(payload or {}, ensure_ascii=False), datetime.now(UTC).isoformat()),
                )
        except sqlite3.Error as exc:
            raise StorageError() from exc

    def get_trace(self, trace_id: str) -> list[dict[str, Any]]:
        try:
            with closing(self._connect()) as connection, connection:
                rows = connection.execute(
                    "SELECT event_name, payload_json, created_at FROM trace_events WHERE trace_id = ? ORDER BY id ASC",
                    (trace_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError() from exc
        return [
            {
                "event": row["event_name"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
