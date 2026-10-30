"""Synthetic Claude Code session for demos when no local transcripts exist."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .parser import parse_session


SESSION_ID = "demo-session-token-graph-001"
PROJECT = "demo-app"


def _ts(base: dt.datetime, minutes: float) -> str:
    return (base + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_demo_jsonl(path: Path) -> Path:
    """Write a realistic-ish Claude Code transcript to path."""
    base = dt.datetime(2026, 10, 29, 14, 0, 0, tzinfo=dt.timezone.utc)
    sid = SESSION_ID
    lines: list[dict[str, Any]] = []

    # Growing context simulation across 12 requests
    files = {
        "src/components/Dashboard.tsx": 18400,
        "src/lib/api/client.ts": 4200,
        "package.json": 800,
        "src/hooks/useSession.ts": 3100,
        "README.md": 2200,
    }
    mcp_payload = "x" * (12000 * 4)  # ~12k tokens
    dashboard = "D" * (18400 * 4)
    api_client = "A" * (4200 * 4)
    pkg = "P" * (800 * 4)
    hook = "H" * (3100 * 4)
    readme = "R" * (2200 * 4)

    def user_text(text: str, minute: float) -> dict:
        return {
            "type": "user",
            "sessionId": sid,
            "timestamp": _ts(base, minute),
            "message": {"role": "user", "content": text},
        }

    def assistant_tools(minute: float, tools: list[tuple[str, str, dict]], model="claude-sonnet-4-20250514"):
        content = []
        for tid, name, inp in tools:
            content.append({"type": "tool_use", "id": tid, "name": name, "input": inp})
        return {
            "type": "assistant",
            "sessionId": sid,
            "timestamp": _ts(base, minute),
            "message": {
                "role": "assistant",
                "model": model,
                "content": content,
                "stop_reason": "tool_use",
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 180,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
            "requestId": f"req-tools-{minute}",
            "costUSD": 0.004,
        }

    def tool_result(minute: float, tool_use_id: str, content: str, is_error=False):
        return {
            "type": "user",
            "sessionId": sid,
            "timestamp": _ts(base, minute),
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": content,
                        "is_error": is_error,
                    }
                ],
            },
        }

    def assistant_text(minute: float, text: str, usage: dict, request_id: str, cost: float, model="claude-sonnet-4-20250514"):
        return {
            "type": "assistant",
            "sessionId": sid,
            "timestamp": _ts(base, minute),
            "message": {
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "usage": usage,
            },
            "requestId": request_id,
            "costUSD": cost,
        }

    # Request 1: start + read package.json
    lines.append(user_text("Help me understand this app's token usage patterns.", 0))
    lines.append(
        assistant_tools(
            0.2,
            [("tu1", "Read", {"file_path": "/workspace/demo-app/package.json"})],
        )
    )
    # Note: assistant_tools already has usage - that's request 1
    lines.append(tool_result(0.4, "tu1", pkg))

    # Request 2: read Dashboard (huge)
    cache = 800
    lines.append(
        assistant_tools(
            1.0,
            [("tu2", "Read", {"file_path": "/workspace/demo-app/src/components/Dashboard.tsx"})],
        )
    )
    # Fix: we need proper growing usage on text responses. Rebuild more carefully.
    # Actually assistant_tools creates usage records. Let me rebuild the whole transcript
    # more carefully so each API response has growing cache.

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")  # reset — rebuild below
    return _build_polished(path, base, sid)


def _build_polished(path: Path, base: dt.datetime, sid: str) -> Path:
    lines: list[str] = []

    dashboard = "D" * (18400 * 4)
    api_client = "A" * (4200 * 4)
    pkg = '{"name":"demo-app","dependencies":{"react":"^19"}}' + ("P" * (800 * 4))
    hook = "H" * (3100 * 4)
    readme = "R" * (2200 * 4)
    mcp_body = json.dumps({"rows": [{"id": i, "blob": "m" * 80} for i in range(150)]})
    # pad mcp to ~12k tokens
    mcp_body = mcp_body + ("M" * max(0, 12000 * 4 - len(mcp_body)))
    bash_out = "file1\nfile2\n" + ("b" * 2000)
    agent_summary = "Subagent findings:\n" + ("S" * (8000 * 4))

    def emit(obj: dict) -> None:
        lines.append(json.dumps(obj))

    # Growing context: track approximate cache_read after each injection
    # We'll script a sequence of (user/tool_result) then assistant with usage.

    timeline = [
        # minute, kind
    ]

    # Turn 0: user prompt
    emit({
        "type": "user",
        "sessionId": sid,
        "timestamp": _ts(base, 0),
        "message": {"role": "user", "content": "Profile this React app and find expensive patterns."},
    })

    # Assistant call 1 — plan + read package.json
    emit({
        "type": "assistant",
        "sessionId": sid,
        "timestamp": _ts(base, 0.1),
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [
                {"type": "text", "text": "I'll start by inspecting the project layout."},
                {"type": "tool_use", "id": "tu_pkg", "name": "Read", "input": {"file_path": "/workspace/demo-app/package.json"}},
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 2400,
                "output_tokens": 120,
                "cache_creation_input_tokens": 2200,
                "cache_read_input_tokens": 0,
            },
        },
        "requestId": "req_001",
        "costUSD": 0.012,
    })
    emit({
        "type": "user",
        "sessionId": sid,
        "timestamp": _ts(base, 0.2),
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu_pkg", "content": pkg}],
        },
    })

    # Call 2 — read Dashboard (big)
    emit({
        "type": "assistant",
        "sessionId": sid,
        "timestamp": _ts(base, 1.0),
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [
                {"type": "tool_use", "id": "tu_dash", "name": "Read", "input": {"file_path": "/workspace/demo-app/src/components/Dashboard.tsx"}},
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 400,
                "output_tokens": 90,
                "cache_creation_input_tokens": 900,
                "cache_read_input_tokens": 2400,
            },
        },
        "requestId": "req_002",
        "costUSD": 0.008,
    })
    emit({
        "type": "user",
        "sessionId": sid,
        "timestamp": _ts(base, 1.1),
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu_dash", "content": dashboard}],
        },
    })

    # Call 3 — MCP query
    emit({
        "type": "assistant",
        "sessionId": sid,
        "timestamp": _ts(base, 2.0),
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [
                {"type": "text", "text": "Pulling recent metrics from the observability MCP."},
                {
                    "type": "tool_use",
                    "id": "tu_mcp",
                    "name": "mcp__datadog__query_metrics",
                    "input": {"query": "avg:tokens.used{*}", "from": "1h"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 500,
                "output_tokens": 140,
                "cache_creation_input_tokens": 18400,
                "cache_read_input_tokens": 3300,
            },
        },
        "requestId": "req_003",
        "costUSD": 0.075,
    })
    emit({
        "type": "user",
        "sessionId": sid,
        "timestamp": _ts(base, 2.2),
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu_mcp", "content": mcp_body}],
        },
    })

    # Call 4 — read api client + bash
    emit({
        "type": "assistant",
        "sessionId": sid,
        "timestamp": _ts(base, 3.0),
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [
                {"type": "tool_use", "id": "tu_api", "name": "Read", "input": {"file_path": "/workspace/demo-app/src/lib/api/client.ts"}},
                {"type": "tool_use", "id": "tu_bash", "name": "Bash", "input": {"command": "find src -name '*.tsx' | head"}},
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 600,
                "output_tokens": 200,
                "cache_creation_input_tokens": 12000,
                "cache_read_input_tokens": 22000,
            },
        },
        "requestId": "req_004",
        "costUSD": 0.055,
    })
    emit({
        "type": "user",
        "sessionId": sid,
        "timestamp": _ts(base, 3.1),
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_api", "content": api_client},
                {"type": "tool_result", "tool_use_id": "tu_bash", "content": bash_out},
            ],
        },
    })

    # Call 5 — subagent
    emit({
        "type": "assistant",
        "sessionId": sid,
        "timestamp": _ts(base, 4.0),
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu_agent",
                    "name": "Task",
                    "input": {
                        "subagent_type": "Explore",
                        "prompt": "Find all token-related counters",
                    },
                },
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 700,
                "output_tokens": 160,
                "cache_creation_input_tokens": 4500,
                "cache_read_input_tokens": 35000,
            },
        },
        "requestId": "req_005",
        "costUSD": 0.035,
    })
    emit({
        "type": "user",
        "sessionId": sid,
        "timestamp": _ts(base, 5.0),
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu_agent", "content": agent_summary}],
        },
    })

    # Call 6 — skill + read hook
    emit({
        "type": "assistant",
        "sessionId": sid,
        "timestamp": _ts(base, 6.0),
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu_skill",
                    "name": "Skill",
                    "input": {"skill_name": "frontend-design"},
                },
                {
                    "type": "tool_use",
                    "id": "tu_hook",
                    "name": "Read",
                    "input": {"file_path": "/workspace/demo-app/src/hooks/useSession.ts"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 800,
                "output_tokens": 220,
                "cache_creation_input_tokens": 9000,
                "cache_read_input_tokens": 42000,
            },
        },
        "requestId": "req_006",
        "costUSD": 0.048,
    })
    skill_text = "Skill instructions:\n" + ("K" * (2500 * 4))
    emit({
        "type": "user",
        "sessionId": sid,
        "timestamp": _ts(base, 6.1),
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_skill", "content": skill_text},
                {"type": "tool_result", "tool_use_id": "tu_hook", "content": hook},
            ],
        },
    })

    # Calls 7-11: continued work with high cache reads (amplification visible)
    for i, (minute, out_tok, cost) in enumerate(
        [
            (8.0, 400, 0.062),
            (10.0, 350, 0.058),
            (12.0, 500, 0.071),
            (14.0, 280, 0.055),
            (16.0, 600, 0.080),
        ],
        start=7,
    ):
        # occasional small read
        tools_content = []
        tool_results = []
        if i == 8:
            tools_content.append(
                {
                    "type": "tool_use",
                    "id": "tu_readme",
                    "name": "Read",
                    "input": {"file_path": "/workspace/demo-app/README.md"},
                }
            )
            tool_results.append(
                {"type": "tool_result", "tool_use_id": "tu_readme", "content": readme}
            )
        tools_content.insert(0, {"type": "text", "text": f"Continuing analysis step {i - 6}."})

        emit({
            "type": "assistant",
            "sessionId": sid,
            "timestamp": _ts(base, minute),
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-20250514" if i == 10 else "claude-sonnet-4-20250514",
                "content": tools_content if tools_content else [{"type": "text", "text": "ok"}],
                "stop_reason": "tool_use" if tool_results else "end_turn",
                "usage": {
                    "input_tokens": 900 + i * 40,
                    "output_tokens": out_tok,
                    "cache_creation_input_tokens": 800 if i == 8 else 200,
                    "cache_read_input_tokens": 48000 + i * 1500,
                },
            },
            "requestId": f"req_{i:03d}",
            "costUSD": cost,
        })
        if tool_results:
            emit({
                "type": "user",
                "sessionId": sid,
                "timestamp": _ts(base, minute + 0.1),
                "message": {"role": "user", "content": tool_results},
            })

    # Final response
    emit({
        "type": "assistant",
        "sessionId": sid,
        "timestamp": _ts(base, 18.0),
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Dashboard.tsx and the Datadog MCP response dominate context. "
                        "Reading the full dashboard early amplified across every later request."
                    ),
                }
            ],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 1100,
                "output_tokens": 450,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 62000,
            },
        },
        "requestId": "req_012",
        "costUSD": 0.068,
    })

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_demo_session(sample_dir: Path | None = None) -> tuple[str, str, list[dict], list[dict]]:
    root = sample_dir or Path(__file__).resolve().parents[2] / "sample_data"
    fp = root / PROJECT / f"{SESSION_ID}.jsonl"
    build_demo_jsonl(fp)
    requests, tools = parse_session(fp, PROJECT)
    # Ensure session id is consistent
    for r in requests:
        r["session"] = SESSION_ID
    for t in tools:
        t["session"] = SESSION_ID
    return SESSION_ID, PROJECT, requests, tools
