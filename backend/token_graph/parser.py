"""
Claude Code transcript parser.

Adapted from kelviq/tare (ccaudit.py), MIT License.
Copyright (c) 2026 the ccaudit contributors.

Reads ~/.claude/projects/<slug>/<session-id>.jsonl, deduplicates usage
records, estimates tool-result injection size, and computes amplified
token-reads (injected × subsequent requests that re-send context).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

CHARS_PER_TOKEN = 4.0
USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)

# Relative weight proxy (USD / MTok). Subscription limits meter compute.
MODEL_RATES = {
    "opus": {"in": 15.00, "out": 75.00},
    "sonnet": {"in": 3.00, "out": 15.00},
    "haiku": {"in": 0.80, "out": 4.00},
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10


def parse_ts(raw: Any) -> Optional[dt.datetime]:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        return dt.datetime.fromtimestamp(
            raw / 1000.0 if raw > 1e11 else raw, dt.timezone.utc
        )
    try:
        p = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return p if p.tzinfo else p.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def content_blocks(entry: dict) -> list[dict]:
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    c = msg.get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def normalize_tool(name: Optional[str], tool_input: Any) -> tuple[str, Optional[str]]:
    ti = tool_input if isinstance(tool_input, dict) else {}
    if not name:
        return "unknown", None
    m = re.match(r"^mcp__(.+?)__(.+)$", name)
    if m:
        return f"MCP {m.group(1)}/{m.group(2)}", None
    if name in ("Task", "Agent"):
        return f"Agent:{ti.get('subagent_type') or 'unnamed'}", None
    if name == "Skill":
        return f"Skill:{ti.get('skill_name') or ti.get('command') or 'unnamed'}", None
    if name in ("Read", "Edit", "Write", "NotebookEdit", "MultiEdit"):
        return name, ti.get("file_path") or ti.get("notebook_path")
    if name == "Bash":
        cmd = (ti.get("command") or "").strip().split()
        return "Bash", (cmd[0] if cmd else None)
    if name == "WebFetch":
        url = ti.get("url") or ""
        return "WebFetch", (re.sub(r"^https?://([^/]+).*$", r"\1", url) or None)
    if name == "WebSearch":
        return "WebSearch", None
    return name, None


def est_tokens(obj: Any) -> int:
    if obj is None:
        return 0
    if isinstance(obj, str):
        return int(len(obj) / CHARS_PER_TOKEN)
    try:
        return int(len(json.dumps(obj, default=str)) / CHARS_PER_TOKEN)
    except (TypeError, ValueError):
        return int(len(str(obj)) / CHARS_PER_TOKEN)


def rate_for(model: str) -> Optional[dict]:
    m = model.lower()
    for k in sorted(MODEL_RATES, key=len, reverse=True):
        if k in m:
            return MODEL_RATES[k]
    return None


def weight_usd(r: dict) -> float:
    if isinstance(r.get("cost_usd"), (int, float)):
        return float(r["cost_usd"])
    rt = rate_for(str(r.get("model") or ""))
    if not rt:
        return 0.0
    return (
        r["input_tokens"] * rt["in"]
        + r["cache_creation_input_tokens"] * rt["in"] * CACHE_WRITE_MULT
        + r["cache_read_input_tokens"] * rt["in"] * CACHE_READ_MULT
        + r["output_tokens"] * rt["out"]
    ) / 1_000_000


def parse_session(
    fp: Path,
    project: str,
    since: Optional[dt.datetime] = None,
    stats: Optional[Counter] = None,
) -> tuple[list[dict], list[dict]]:
    """Walk one transcript. Returns (requests, tool_events)."""
    stats = stats if stats is not None else Counter()
    requests: list[dict] = []
    tool_events: list[dict] = []
    tool_names: dict[str, tuple[str, Optional[str]]] = {}
    seen: dict[str, int] = {}

    try:
        fh = open(fp, "r", encoding="utf-8", errors="replace")
    except OSError:
        return [], []

    with fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            stats["lines"] += 1
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                stats["lines_bad_json"] += 1
                continue
            if not isinstance(e, dict):
                stats["lines_not_object"] += 1
                continue

            ts = parse_ts(e.get("timestamp"))
            msg = e.get("message") if isinstance(e.get("message"), dict) else {}
            blocks = content_blocks(e)

            for b in blocks:
                if b.get("type") == "tool_use":
                    tool_names[b.get("id")] = normalize_tool(
                        b.get("name"), b.get("input")
                    )

            for b in blocks:
                if b.get("type") != "tool_result":
                    continue
                label, detail = tool_names.get(
                    b.get("tool_use_id"), ("unknown tool", None)
                )
                tokens = est_tokens(b.get("content"))
                if not tokens and e.get("toolUseResult") is not None:
                    tokens = est_tokens(e.get("toolUseResult"))
                tool_events.append(
                    {
                        "session": e.get("sessionId") or fp.stem,
                        "project": project,
                        "ts": ts,
                        "tool": label,
                        "detail": detail,
                        "tokens": tokens,
                        "is_error": bool(b.get("is_error")),
                        "req_index": len(requests),
                        "tool_use_id": b.get("tool_use_id"),
                    }
                )

            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
            if not usage:
                continue
            counts = {k: int(usage.get(k) or 0) for k in USAGE_KEYS}
            if sum(counts.values()) == 0:
                stats["lines_zero_usage"] += 1
                continue
            if since and ts and ts < since:
                stats["records_old"] += 1
                continue

            key = e.get("requestId") or msg.get("id") or f"{fp.stem}:{lineno}"
            if key in seen:
                prev = requests[seen[key]]
                prev["_dupes"] += 1
                if counts["output_tokens"] > prev["output_tokens"]:
                    prev.update(counts)
                stats["dupes"] += 1
                continue

            seen[key] = len(requests)
            requests.append(
                {
                    "file": str(fp),
                    "project": project,
                    "session": e.get("sessionId") or fp.stem,
                    "ts": ts,
                    "model": str(msg.get("model") or "unknown"),
                    "request_id": key,
                    "sidechain": bool(e.get("isSidechain")),
                    "version": e.get("version") or "",
                    "stop_reason": msg.get("stop_reason"),
                    "cost_usd": e.get("costUSD"),
                    "_dupes": 1,
                    **counts,
                }
            )
            stats["records"] += 1

    total = len(requests)
    for t in tool_events:
        remaining = max(0, total - t["req_index"])
        t["amplified"] = t["tokens"] * remaining
        t["affected_requests"] = remaining
    return requests, tool_events


def load_transcripts(
    root: Path,
    since: Optional[dt.datetime] = None,
) -> tuple[list[dict], list[dict], Counter]:
    stats: Counter = Counter()
    requests: list[dict] = []
    tools: list[dict] = []
    for fp in sorted(root.rglob("*.jsonl")):
        try:
            mtime = dt.datetime.fromtimestamp(fp.stat().st_mtime, dt.timezone.utc)
        except OSError:
            continue
        if since and mtime < since:
            stats["files_skipped_old"] += 1
            continue
        stats["files_read"] += 1
        try:
            rel = fp.relative_to(root)
            project = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        except ValueError:
            project = fp.parent.name
        r, t = parse_session(fp, project, since, stats)
        requests.extend(r)
        tools.extend(t)
    requests.sort(
        key=lambda x: x["ts"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    )
    return requests, tools, stats


def group_by_session(
    requests: list[dict], tools: list[dict]
) -> dict[str, dict[str, Any]]:
    sessions: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"requests": [], "tools": [], "project": "(unknown)"}
    )
    for r in requests:
        sid = r["session"]
        sessions[sid]["requests"].append(r)
        sessions[sid]["project"] = r.get("project") or sessions[sid]["project"]
    for t in tools:
        sessions[t["session"]]["tools"].append(t)
        if t.get("project"):
            sessions[t["session"]]["project"] = t["project"]
    return dict(sessions)


def default_claude_projects_root() -> Path:
    return Path.home() / ".claude" / "projects"
