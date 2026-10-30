"""
Claude Code transcript parser.

Adapted from kelviq/tare (ccaudit.py), MIT License.
Copyright (c) 2026 the ccaudit contributors.

Reads ~/.claude/projects/<slug>/<session-id>.jsonl, deduplicates usage
records, estimates tool-result injection size, and computes amplified
token-reads (injected × subsequent requests that re-send context).
Also extracts user prompts, assistant text, and thinking for the UI.
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


def _clip(text: str, n: int = 280) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _tool_intent(tool_input: Any) -> Optional[str]:
    tip = tool_input if isinstance(tool_input, dict) else {}
    for key in ("prompt", "description", "command", "query", "pattern", "content"):
        val = tip.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def extract_text_parts(blocks: list[dict], msg: dict) -> tuple[str, str, str]:
    """Return (text, thinking, tool_summary) from content blocks."""
    texts: list[str] = []
    thoughts: list[str] = []
    tool_bits: list[str] = []

    raw = msg.get("content")
    if isinstance(raw, str) and raw.strip():
        texts.append(raw.strip())

    for b in blocks:
        btype = b.get("type")
        if btype in ("text", "output_text"):
            t = b.get("text") or b.get("content") or ""
            if isinstance(t, str) and t.strip():
                texts.append(t.strip())
        elif btype in ("thinking", "reasoning"):
            t = b.get("thinking") or b.get("text") or b.get("content") or ""
            if isinstance(t, str) and t.strip():
                thoughts.append(t.strip())
        elif btype == "tool_use":
            name = b.get("name") or "tool"
            label, detail = normalize_tool(name, b.get("input"))
            intent = _tool_intent(b.get("input"))
            if detail and intent:
                tool_bits.append(f"{label} → {detail}: {_clip(intent, 100)}")
            elif detail:
                tool_bits.append(f"{label} → {detail}")
            elif intent:
                tool_bits.append(f"{label}: {_clip(intent, 120)}")
            else:
                tool_bits.append(label)

    return "\n\n".join(texts), "\n\n".join(thoughts), "; ".join(tool_bits)


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
    tool_intents: dict[str, str] = {}
    seen: dict[str, int] = {}
    pending_user_prompts: list[str] = []
    session_title: Optional[str] = None

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
            role = msg.get("role") or e.get("type")

            # Capture human prompts (text turns, not pure tool_result turns)
            if role == "user" or e.get("type") == "user":
                has_tool_result = any(b.get("type") == "tool_result" for b in blocks)
                text, _th, _tools = extract_text_parts(blocks, msg)
                if text:
                    pending_user_prompts.append(text)
                    if session_title is None and not has_tool_result:
                        session_title = _clip(text, 96)

            for b in blocks:
                if b.get("type") != "tool_use":
                    continue
                tid = b.get("id")
                tool_names[tid] = normalize_tool(b.get("name"), b.get("input"))
                intent = _tool_intent(b.get("input"))
                if intent and tid:
                    tool_intents[tid] = intent

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
                        "intent": tool_intents.get(b.get("tool_use_id") or ""),
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

            asst_text, thinking, tool_summary = extract_text_parts(blocks, msg)
            user_prompt = "\n\n".join(pending_user_prompts).strip()
            pending_user_prompts.clear()

            key = e.get("requestId") or msg.get("id") or f"{fp.stem}:{lineno}"
            if key in seen:
                prev = requests[seen[key]]
                prev["_dupes"] += 1
                if counts["output_tokens"] > prev["output_tokens"]:
                    for k, v in counts.items():
                        prev[k] = v
                if asst_text and len(asst_text) > len(prev.get("assistant_text") or ""):
                    prev["assistant_text"] = asst_text
                if thinking and len(thinking) > len(prev.get("thinking") or ""):
                    prev["thinking"] = thinking
                if tool_summary and not prev.get("tool_summary"):
                    prev["tool_summary"] = tool_summary
                if user_prompt and not prev.get("user_prompt"):
                    prev["user_prompt"] = user_prompt
                stats["dupes"] += 1
                continue

            preview = (
                _clip(asst_text, 72)
                or _clip(thinking, 72)
                or _clip(tool_summary, 72)
                or _clip(user_prompt, 72)
                or f"Request {len(requests) + 1}"
            )

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
                    "user_prompt": user_prompt or None,
                    "assistant_text": asst_text or None,
                    "thinking": thinking or None,
                    "tool_summary": tool_summary or None,
                    "preview": preview,
                    **counts,
                }
            )
            stats["records"] += 1

    total = len(requests)
    for t in tool_events:
        remaining = max(0, total - t["req_index"])
        t["amplified"] = t["tokens"] * remaining
        t["affected_requests"] = remaining
        tid = t.get("tool_use_id")
        if tid and tid in tool_intents and not t.get("intent"):
            t["intent"] = tool_intents[tid]

    if requests and session_title:
        requests[0]["session_title"] = session_title
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


def session_title_from_requests(requests: list[dict]) -> Optional[str]:
    if not requests:
        return None
    if requests[0].get("session_title"):
        return str(requests[0]["session_title"])
    for r in requests:
        if r.get("user_prompt"):
            return _clip(str(r["user_prompt"]), 96)
    for r in requests:
        if r.get("preview"):
            return _clip(str(r["preview"]), 96)
    return None


def session_preview_from_requests(requests: list[dict]) -> Optional[str]:
    for r in requests:
        bit = r.get("assistant_text") or r.get("thinking") or r.get("user_prompt")
        if bit:
            return _clip(str(bit), 160)
    return None


def default_claude_projects_root() -> Path:
    return Path.home() / ".claude" / "projects"
