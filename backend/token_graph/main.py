"""FastAPI application for Token Graph."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .db import Store
from .demo import load_demo_session
from .graph_builder import build_graph, inspector_for
from .models import (
    GraphMetric,
    GraphPayload,
    GraphView,
    ImportResult,
    InspectorDetail,
    SessionSummary,
)
from .parser import default_claude_projects_root, group_by_session, load_transcripts

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
SAMPLE_DIR = REPO_ROOT / "sample_data"
DB_PATH = Path(os.environ.get("TOKEN_GRAPH_DB", REPO_ROOT / "data" / "token_graph.db"))
STATIC_DIR = Path(os.environ.get("TOKEN_GRAPH_STATIC", REPO_ROOT / "frontend" / "dist"))

app = FastAPI(title="Token Graph", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store(DB_PATH)


class ImportBody(BaseModel):
    path: Optional[str] = Field(
        default=None,
        description="Claude Code projects root. Defaults to ~/.claude/projects",
    )
    days: Optional[int] = Field(default=30, ge=1, le=365)


class DemoBody(BaseModel):
    force: bool = False


@app.on_event("startup")
def seed_demo_if_empty() -> None:
    if not store.list_sessions():
        sid, project, requests, tools = load_demo_session(SAMPLE_DIR)
        store.upsert_session(sid, project, requests, tools, source="demo")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/sessions", response_model=list[SessionSummary])
def list_sessions() -> list[SessionSummary]:
    return store.list_sessions()


@app.get("/api/sessions/{session_id}", response_model=SessionSummary)
def get_session(session_id: str) -> SessionSummary:
    s = store.get_summary(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s


@app.get("/api/sessions/{session_id}/graph", response_model=GraphPayload)
def get_graph(
    session_id: str,
    view: GraphView = Query(GraphView.EXECUTION),
    metric: GraphMetric = Query(GraphMetric.DIRECT),
) -> GraphPayload:
    data = store.get_session_data(session_id)
    if not data:
        raise HTTPException(404, "Session not found")
    requests, tools = data
    return build_graph(session_id, requests, tools, view, metric)


@app.get(
    "/api/sessions/{session_id}/nodes/{node_id}",
    response_model=InspectorDetail,
)
def get_node_detail(
    session_id: str,
    node_id: str,
    view: GraphView = Query(GraphView.EXECUTION),
    metric: GraphMetric = Query(GraphMetric.DIRECT),
) -> InspectorDetail:
    data = store.get_session_data(session_id)
    if not data:
        raise HTTPException(404, "Session not found")
    requests, tools = data
    graph = build_graph(session_id, requests, tools, view, metric)
    node = next((n for n in graph.nodes if n.id == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")
    payload = inspector_for(node, graph)
    return InspectorDetail(**payload)


@app.post("/api/import", response_model=ImportResult)
def import_sessions(body: ImportBody) -> ImportResult:
    root = Path(body.path) if body.path else default_claude_projects_root()
    if not root.exists():
        raise HTTPException(
            400,
            f"Claude Code projects path not found: {root}. "
            "Load the demo session instead, or pass a valid --path.",
        )
    since = None
    if body.days:
        import datetime as dt

        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=body.days)

    requests, tools, stats = load_transcripts(root, since)
    grouped = group_by_session(requests, tools)
    summaries: list[SessionSummary] = []
    for sid, payload in grouped.items():
        if not payload["requests"]:
            continue
        summaries.append(
            store.upsert_session(
                sid,
                payload["project"],
                payload["requests"],
                payload["tools"],
                source="claude-code",
            )
        )
    return ImportResult(
        sessions=summaries,
        message=(
            f"Imported {len(summaries)} session(s) from {root} "
            f"({stats.get('files_read', 0)} files, {stats.get('records', 0)} requests, "
            f"{stats.get('dupes', 0)} deduped)."
        ),
    )


@app.post("/api/demo", response_model=SessionSummary)
def load_demo(body: DemoBody = DemoBody()) -> SessionSummary:
    existing = store.get_summary("demo-session-token-graph-001")
    if existing and not body.force:
        return existing
    sid, project, requests, tools = load_demo_session(SAMPLE_DIR)
    return store.upsert_session(sid, project, requests, tools, source="demo")


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    if not store.delete_session(session_id):
        raise HTTPException(404, "Session not found")
    return {"ok": True}


# Serve built frontend when present
if STATIC_DIR.exists():
    assets = STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
