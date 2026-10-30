"""SQLite persistence for sessions and graph payloads."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .models import SessionSummary
from .parser import weight_usd

DEFAULT_DB = Path.home() / ".token-graph" / "token_graph.db"


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    project TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    request_count INTEGER DEFAULT 0,
                    tool_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0,
                    models TEXT DEFAULT '[]',
                    source TEXT DEFAULT 'import'
                );
                CREATE TABLE IF NOT EXISTS session_data (
                    session_id TEXT PRIMARY KEY,
                    requests_json TEXT NOT NULL,
                    tools_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                """
            )

    def upsert_session(
        self,
        session_id: str,
        project: str,
        requests: list[dict],
        tools: list[dict],
        source: str = "import",
    ) -> SessionSummary:
        started = None
        ended = None
        models: list[str] = []
        for r in requests:
            ts = r.get("ts")
            iso = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else None)
            if iso:
                started = iso if started is None else min(started, iso)
                ended = iso if ended is None else max(ended, iso)
            m = r.get("model")
            if m and m not in models:
                models.append(m)

        total_tokens = sum(
            r["input_tokens"]
            + r["output_tokens"]
            + r["cache_creation_input_tokens"]
            + r["cache_read_input_tokens"]
            for r in requests
        )
        cost = sum(weight_usd(r) for r in requests)
        summary = SessionSummary(
            id=session_id,
            project=project,
            started_at=started,
            ended_at=ended,
            request_count=len(requests),
            tool_count=len(tools),
            total_tokens=total_tokens,
            cost_usd=round(cost, 4),
            models=models,
            source=source,  # type: ignore[arg-type]
        )

        # Serialize datetimes for JSON storage
        def serialize(obj: Any) -> Any:
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            raise TypeError(type(obj))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, project, started_at, ended_at, request_count, tool_count,
                    total_tokens, cost_usd, models, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project=excluded.project,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    request_count=excluded.request_count,
                    tool_count=excluded.tool_count,
                    total_tokens=excluded.total_tokens,
                    cost_usd=excluded.cost_usd,
                    models=excluded.models,
                    source=excluded.source
                """,
                (
                    summary.id,
                    summary.project,
                    summary.started_at,
                    summary.ended_at,
                    summary.request_count,
                    summary.tool_count,
                    summary.total_tokens,
                    summary.cost_usd,
                    json.dumps(summary.models),
                    summary.source,
                ),
            )
            conn.execute(
                """
                INSERT INTO session_data (session_id, requests_json, tools_json)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    requests_json=excluded.requests_json,
                    tools_json=excluded.tools_json
                """,
                (
                    session_id,
                    json.dumps(requests, default=serialize),
                    json.dumps(tools, default=serialize),
                ),
            )
        return summary

    def list_sessions(self) -> list[SessionSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC NULLS LAST, id"
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                SessionSummary(
                    id=r["id"],
                    project=r["project"],
                    started_at=r["started_at"],
                    ended_at=r["ended_at"],
                    request_count=r["request_count"],
                    tool_count=r["tool_count"],
                    total_tokens=r["total_tokens"],
                    cost_usd=r["cost_usd"],
                    models=json.loads(r["models"] or "[]"),
                    source=r["source"],
                )
            )
        return out

    def get_session_data(self, session_id: str) -> Optional[tuple[list[dict], list[dict]]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT requests_json, tools_json FROM session_data WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["requests_json"]), json.loads(row["tools_json"])

    def get_summary(self, session_id: str) -> Optional[SessionSummary]:
        with self._connect() as conn:
            r = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if not r:
            return None
        return SessionSummary(
            id=r["id"],
            project=r["project"],
            started_at=r["started_at"],
            ended_at=r["ended_at"],
            request_count=r["request_count"],
            tool_count=r["tool_count"],
            total_tokens=r["total_tokens"],
            cost_usd=r["cost_usd"],
            models=json.loads(r["models"] or "[]"),
            source=r["source"],
        )

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.execute(
                "DELETE FROM session_data WHERE session_id = ?", (session_id,)
            )
            return cur.rowcount > 0
