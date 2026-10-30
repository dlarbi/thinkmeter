#!/usr/bin/env python3
"""Smoke-test parser + graph builder against the demo transcript."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from token_graph.demo import load_demo_session
from token_graph.graph_builder import build_attribution_graph, build_execution_graph
from token_graph.models import GraphMetric


def main() -> int:
    sid, project, requests, tools = load_demo_session(ROOT / "sample_data")
    assert requests, "expected demo requests"
    assert tools, "expected demo tools"
    assert all("amplified" in t for t in tools)
    assert any(r.get("user_prompt") for r in requests), "expected user prompts"
    assert any(r.get("thinking") for r in requests), "expected thinking blocks"
    assert any(r.get("cost_usd") for r in requests), "expected reported costs"

    ids = [r["request_id"] for r in requests]
    assert len(ids) == len(set(ids)), "duplicate request ids after parse"

    exe = build_execution_graph(sid, requests, tools, GraphMetric.DIRECT)
    attr = build_attribution_graph(sid, requests, tools, GraphMetric.AMPLIFIED)

    assert any(n.type.value == "request" for n in exe.nodes)
    assert any(n.type.value == "prompt" for n in exe.nodes), "expected prompt nodes"
    assert any(n.type.value == "thinking" for n in exe.nodes), "expected thinking nodes"
    assert any(n.cost_usd and n.cost_usd > 0 for n in exe.nodes), "expected cost on nodes"
    assert any(n.tokens.amplified > 0 for n in attr.nodes)

    sources = [n for n in attr.nodes if n.meta.get("kind") == "source"]
    sources.sort(key=lambda n: n.tokens.amplified, reverse=True)
    top = sources[0]
    print(f"session={sid} project={project}")
    print(f"requests={len(requests)} tools={len(tools)}")
    print(f"exe_nodes={len(exe.nodes)} attr_nodes={len(attr.nodes)}")
    print(f"top_source={top.label} injected={top.tokens.injected} amplified={top.tokens.amplified} cost={top.cost_usd}")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
