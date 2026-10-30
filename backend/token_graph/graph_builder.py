"""Build execution and attribution graphs from parsed session data."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any, Optional

from .models import (
    AttributionConfidence,
    CostSource,
    EdgeRelation,
    GraphMetric,
    GraphPayload,
    GraphView,
    NodeType,
    TokenBreakdown,
    TokenEdge,
    TokenNode,
)
from .parser import _clip, weight_usd


ASSUMPTIONS = [
    "Tool output tokens are estimated at ~4 characters per token.",
    "Amplified tokens assume tool output remains in context for every subsequent request.",
    "Compaction, /clear, and cache expiry are not yet modeled — amplification may overstate impact.",
    "Request costs use reported costUSD when present; otherwise API-rate estimates.",
    "Never sum tool-attributed cost on top of parent request cost — that double-counts.",
    "Prompt / thinking text is taken from the transcript; truncated in the graph label, full in the inspector.",
]


def _nid(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _ts(v: Any) -> Optional[str]:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _node_type_for_tool(label: str) -> NodeType:
    if label.startswith("Agent:"):
        return NodeType.AGENT
    if label.startswith("Skill:"):
        return NodeType.PROMPT
    if label in ("Read", "Edit", "Write", "NotebookEdit", "MultiEdit"):
        return NodeType.FILE
    if label.startswith("MCP "):
        return NodeType.TOOL
    return NodeType.TOOL


def _confidence(tokens: int, affected: int) -> AttributionConfidence:
    if tokens >= 500 and affected >= 3:
        return AttributionConfidence.HIGH
    if tokens >= 100 or affected >= 2:
        return AttributionConfidence.MEDIUM
    return AttributionConfidence.LOW


def _optimization_hint(
    label: str, detail: Optional[str], injected: int, amplified: int
) -> Optional[str]:
    if amplified < 50_000:
        return None
    if label == "Read" or (detail and injected > 5_000):
        return (
            "Consider reading only the relevant functions or ranges rather than "
            "the entire file. Large early reads amplify across every later request."
        )
    if label.startswith("MCP "):
        return (
            "Trim MCP tool responses or cache results outside the model context "
            "so large payloads are not re-sent on every turn."
        )
    if label.startswith("Agent:"):
        return (
            "Subagent fan-out injects summaries back into the parent. "
            "Prefer narrower tasks or summarize before returning."
        )
    if label == "Bash":
        return "Pipe or truncate command output before it enters the conversation."
    return "Reduce early context injection or clear context between unrelated tasks."


def _allocate_tool_costs(
    requests: list[dict], tools: list[dict]
) -> dict[int, float]:
    """Map tool event index → allocated USD share of the *next* request's cost."""
    out: dict[int, float] = {}
    by_req: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    for i, t in enumerate(tools):
        by_req[t["req_index"]].append((i, t))
    for req_index, items in by_req.items():
        if req_index >= len(requests):
            continue
        req_cost = weight_usd(requests[req_index])
        amp_sum = sum(t["amplified"] or t["tokens"] for _, t in items) or 1
        for i, t in items:
            share = (t["amplified"] or t["tokens"] or 0) / amp_sum
            out[i] = req_cost * share
    return out


def build_execution_graph(
    session_id: str,
    requests: list[dict],
    tools: list[dict],
    metric: GraphMetric = GraphMetric.DIRECT,
) -> GraphPayload:
    nodes: list[TokenNode] = []
    edges: list[TokenEdge] = []
    session_id_node = f"session:{session_id}"
    tool_costs = _allocate_tool_costs(requests, tools)

    req_ids: list[str] = []
    for i, r in enumerate(requests):
        rid = f"req:{r['request_id']}"
        req_ids.append(rid)
        cost = weight_usd(r)
        reported = isinstance(r.get("cost_usd"), (int, float))
        preview = r.get("preview") or f"Request {i + 1}"
        label = f"R{i + 1}: {_clip(str(preview), 42)}"
        node = TokenNode(
            id=rid,
            type=NodeType.REQUEST,
            label=label,
            parent_id=session_id_node,
            tokens=TokenBreakdown(
                input=r["input_tokens"],
                output=r["output_tokens"],
                cache_read=r["cache_read_input_tokens"],
                cache_write=r["cache_creation_input_tokens"],
            ),
            cost_usd=cost,
            cost_source=CostSource.REPORTED if reported else CostSource.ESTIMATED,
            model=r.get("model"),
            timestamp=_ts(r.get("ts")),
            detail=r.get("preview"),
            meta={
                "index": i,
                "sidechain": r.get("sidechain", False),
                "stop_reason": r.get("stop_reason"),
                "dupes": r.get("_dupes", 1),
                "user_prompt": r.get("user_prompt"),
                "thinking": r.get("thinking"),
                "assistant_text": r.get("assistant_text"),
                "tool_summary": r.get("tool_summary"),
                "preview": r.get("preview"),
            },
            assumptions=[
                "Node size scales by the selected metric; cost label is always shown when known.",
            ],
        )
        nodes.append(node)

        # User prompt node feeding this request
        if r.get("user_prompt"):
            pid = f"prompt:{session_id}:{i}"
            nodes.append(
                TokenNode(
                    id=pid,
                    type=NodeType.PROMPT,
                    label=_clip(str(r["user_prompt"]), 48),
                    parent_id=rid,
                    tokens=TokenBreakdown(injected=0),
                    cost_usd=None,
                    cost_source=CostSource.ESTIMATED,
                    timestamp=_ts(r.get("ts")),
                    detail="User prompt",
                    meta={
                        "kind": "narrative",
                        "user_prompt": r.get("user_prompt"),
                        "preview": _clip(str(r["user_prompt"]), 160),
                    },
                    assumptions=["Prompt text from the transcript user turn before this request."],
                )
            )
            edges.append(
                TokenEdge(
                    id=f"e:prompt:{pid}:{rid}",
                    source=pid,
                    target=rid,
                    relation=EdgeRelation.CALLS,
                    label="asks",
                )
            )

        # Thinking node when present
        if r.get("thinking"):
            tid = f"think:{session_id}:{i}"
            nodes.append(
                TokenNode(
                    id=tid,
                    type=NodeType.THINKING,
                    label=_clip(str(r["thinking"]), 48),
                    parent_id=rid,
                    tokens=TokenBreakdown(output=r.get("output_tokens", 0)),
                    cost_usd=None,  # belongs to parent request — not additive
                    cost_source=CostSource.ESTIMATED,
                    timestamp=_ts(r.get("ts")),
                    detail="Model thinking",
                    meta={
                        "kind": "narrative",
                        "thinking": r.get("thinking"),
                        "preview": _clip(str(r["thinking"]), 160),
                        "fixed_size": True,
                    },
                    assumptions=[
                        "Thinking text extracted from transcript thinking/reasoning blocks.",
                        "Cost belongs to the parent request — not added again here.",
                    ],
                )
            )
            edges.append(
                TokenEdge(
                    id=f"e:think:{rid}:{tid}",
                    source=rid,
                    target=tid,
                    relation=EdgeRelation.RETURNS,
                    label="thinks",
                )
            )

        if i > 0:
            edges.append(
                TokenEdge(
                    id=f"e:follow:{req_ids[i - 1]}:{rid}",
                    source=req_ids[i - 1],
                    target=rid,
                    relation=EdgeRelation.FOLLOWS,
                )
            )

    tools_by_req: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    for i, t in enumerate(tools):
        tools_by_req[t["req_index"]].append((i, t))

    for req_index, events in tools_by_req.items():
        parent_req = (
            req_ids[req_index]
            if req_index < len(req_ids)
            else (req_ids[-1] if req_ids else session_id_node)
        )
        for j, (ti, t) in enumerate(events):
            tid = f"tool:{session_id}:{req_index}:{j}:{t.get('tool_use_id') or j}"
            ntype = _node_type_for_tool(t["tool"])
            label = t["detail"] or t["tool"]
            if t["detail"] and ntype == NodeType.FILE:
                label = t["detail"].split("/")[-1]
            allocated = tool_costs.get(ti)
            nodes.append(
                TokenNode(
                    id=tid,
                    type=ntype,
                    label=label,
                    parent_id=parent_req,
                    tokens=TokenBreakdown(
                        injected=t["tokens"],
                        amplified=t["amplified"],
                    ),
                    cost_usd=allocated,
                    cost_source=CostSource.ESTIMATED,
                    attribution_confidence=_confidence(
                        t["tokens"], t.get("affected_requests", 0)
                    ),
                    timestamp=_ts(t.get("ts")),
                    detail=t.get("detail"),
                    meta={
                        "tool": t["tool"],
                        "affected_requests": t.get("affected_requests", 0),
                        "is_error": t.get("is_error", False),
                        "req_index": req_index,
                        "intent": t.get("intent"),
                        "preview": _clip(str(t.get("intent") or label), 160),
                    },
                    assumptions=[
                        "Injected tokens estimated from tool_result content length.",
                        f"Amplified = {t['tokens']:,} × {t.get('affected_requests', 0)} subsequent requests.",
                        "Cost is an allocated share of the parent request — not additive.",
                    ],
                )
            )
            edges.append(
                TokenEdge(
                    id=f"e:calls:{parent_req}:{tid}",
                    source=parent_req,
                    target=tid,
                    relation=EdgeRelation.CALLS,
                    estimated_tokens=t["tokens"],
                )
            )
            edges.append(
                TokenEdge(
                    id=f"e:retains:{tid}:{parent_req}",
                    source=tid,
                    target=parent_req,
                    relation=EdgeRelation.RETAINS,
                    estimated_tokens=t["amplified"],
                    label="context",
                )
            )

    totals = _session_totals(requests, tools)
    return GraphPayload(
        session_id=session_id,
        view=GraphView.EXECUTION,
        metric=metric,
        nodes=nodes,
        edges=edges,
        totals=totals,
        assumptions=ASSUMPTIONS,
    )


def build_attribution_graph(
    session_id: str,
    requests: list[dict],
    tools: list[dict],
    metric: GraphMetric = GraphMetric.AMPLIFIED,
) -> GraphPayload:
    """Group sources of context consumption: files, MCP, skills, agents, tools."""
    nodes: list[TokenNode] = []
    edges: list[TokenEdge] = []
    session_cost = sum(weight_usd(r) for r in requests)

    root = TokenNode(
        id=f"attr:{session_id}",
        type=NodeType.CONTEXT,
        label="Context sources",
        tokens=TokenBreakdown(
            injected=sum(t["tokens"] for t in tools),
            amplified=sum(t["amplified"] for t in tools),
        ),
        cost_usd=session_cost,
        cost_source=CostSource.ESTIMATED,
        assumptions=ASSUMPTIONS,
    )
    nodes.append(root)

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for t in tools:
        ntype = _node_type_for_tool(t["tool"])
        if ntype == NodeType.FILE and t.get("detail"):
            key = ("file", t["detail"])
            label = t["detail"]
        elif t["tool"].startswith("MCP "):
            key = ("mcp", t["tool"])
            label = t["tool"]
        elif t["tool"].startswith("Agent:"):
            key = ("agent", t["tool"])
            label = t["tool"]
        elif t["tool"].startswith("Skill:"):
            key = ("skill", t["tool"])
            label = t["tool"]
        else:
            detail = t.get("detail")
            key = ("tool", f"{t['tool']}::{detail or ''}")
            label = f"{t['tool']}" + (f" · {detail}" if detail else "")

        b = buckets.setdefault(
            key,
            {
                "label": label,
                "type": ntype,
                "injected": 0,
                "amplified": 0,
                "calls": 0,
                "affected_max": 0,
                "errors": 0,
                "detail": t.get("detail"),
                "tool": t["tool"],
                "intents": [],
            },
        )
        b["injected"] += t["tokens"]
        b["amplified"] += t["amplified"]
        b["calls"] += 1
        b["affected_max"] = max(b["affected_max"], t.get("affected_requests", 0))
        b["errors"] += 1 if t.get("is_error") else 0
        if t.get("intent"):
            b["intents"].append(t["intent"])

    # Also attribute user prompts as a prompt bucket (direct tokens estimated)
    prompt_injected = 0
    prompt_texts: list[str] = []
    for r in requests:
        if r.get("user_prompt"):
            from .parser import est_tokens

            prompt_injected += est_tokens(r["user_prompt"])
            prompt_texts.append(str(r["user_prompt"]))
    if prompt_texts:
        buckets[("skill", "__user_prompts__")] = {
            "label": "User prompts",
            "type": NodeType.PROMPT,
            "injected": prompt_injected,
            "amplified": prompt_injected * max(1, len(requests) // 2),
            "calls": len(prompt_texts),
            "affected_max": len(requests),
            "errors": 0,
            "detail": "User prompts across the session",
            "tool": "Prompt",
            "intents": prompt_texts[:5],
        }

    categories = {
        "file": ("Files", NodeType.FILE),
        "mcp": ("MCP tools", NodeType.TOOL),
        "agent": ("Subagents", NodeType.AGENT),
        "skill": ("Skills / prompts", NodeType.PROMPT),
        "tool": ("Other tools", NodeType.TOOL),
    }
    cat_nodes: dict[str, str] = {}
    total_amp = sum(x["amplified"] for x in buckets.values()) or 1

    for cat, (title, ntype) in categories.items():
        items = [v for (c, _), v in buckets.items() if c == cat]
        if not items:
            continue
        cid = f"cat:{session_id}:{cat}"
        cat_nodes[cat] = cid
        cat_amp = sum(i["amplified"] for i in items)
        nodes.append(
            TokenNode(
                id=cid,
                type=ntype,
                label=title,
                parent_id=root.id,
                tokens=TokenBreakdown(
                    injected=sum(i["injected"] for i in items),
                    amplified=cat_amp,
                ),
                cost_usd=session_cost * (cat_amp / total_amp),
                cost_source=CostSource.ESTIMATED,
                meta={"kind": "group", "members": len(items)},
            )
        )
        edges.append(
            TokenEdge(
                id=f"e:{root.id}:{cid}",
                source=root.id,
                target=cid,
                relation=EdgeRelation.CONTAINS,
                estimated_tokens=cat_amp,
            )
        )

    for (cat, raw_key), b in sorted(
        buckets.items(), key=lambda kv: -kv[1]["amplified"]
    ):
        nid = f"src:{_nid(session_id, cat, raw_key)}"
        parent = cat_nodes.get(cat, root.id)
        short = b["label"]
        if cat == "file":
            short = b["label"].split("/")[-1]
        hint = _optimization_hint(
            b["tool"], b.get("detail"), b["injected"], b["amplified"]
        )
        allocated = session_cost * (b["amplified"] / total_amp)
        intent_preview = b["intents"][0] if b.get("intents") else None

        nodes.append(
            TokenNode(
                id=nid,
                type=b["type"],
                label=short,
                parent_id=parent,
                tokens=TokenBreakdown(
                    injected=b["injected"],
                    amplified=b["amplified"],
                ),
                cost_usd=allocated,
                cost_source=CostSource.ESTIMATED,
                attribution_confidence=_confidence(b["injected"], b["affected_max"]),
                detail=b.get("detail") or b["label"],
                meta={
                    "calls": b["calls"],
                    "affected_requests": b["affected_max"],
                    "errors": b["errors"],
                    "tool": b["tool"],
                    "optimization_hint": hint,
                    "kind": "source",
                    "intent": intent_preview,
                    "user_prompt": "\n\n---\n\n".join(b["intents"][:8])
                    if cat == "skill" and raw_key == "__user_prompts__"
                    else None,
                    "preview": _clip(str(intent_preview or short), 160),
                },
                assumptions=[
                    "Cost is allocated from session request totals by amplified share — not additive.",
                    f"Direct injection: {b['injected']:,} estimated tokens across {b['calls']} calls.",
                    f"Amplified token-reads: {b['amplified']:,} "
                    f"(assumes retention across subsequent requests).",
                ],
            )
        )
        edges.append(
            TokenEdge(
                id=f"e:{parent}:{nid}",
                source=parent,
                target=nid,
                relation=EdgeRelation.CONTAINS,
                estimated_tokens=b["amplified"],
            )
        )

    sink = TokenNode(
        id=f"sink:{session_id}",
        type=NodeType.REQUEST,
        label=f"{len(requests)} model calls",
        parent_id=root.id,
        tokens=TokenBreakdown(
            input=sum(r["input_tokens"] for r in requests),
            output=sum(r["output_tokens"] for r in requests),
            cache_read=sum(r["cache_read_input_tokens"] for r in requests),
            cache_write=sum(r["cache_creation_input_tokens"] for r in requests),
        ),
        cost_usd=session_cost,
        cost_source=CostSource.REPORTED
        if any(isinstance(r.get("cost_usd"), (int, float)) for r in requests)
        else CostSource.ESTIMATED,
        meta={"kind": "sink", "fixed_size": True},
        assumptions=[
            "Model-call node is a destination sink; size reflects observed usage, not amplified source area.",
        ],
    )
    nodes.append(sink)
    edges.append(
        TokenEdge(
            id=f"e:{root.id}:{sink.id}",
            source=root.id,
            target=sink.id,
            relation=EdgeRelation.RETAINS,
            estimated_tokens=sum(t["amplified"] for t in tools),
            label="feeds",
        )
    )

    return GraphPayload(
        session_id=session_id,
        view=GraphView.ATTRIBUTION,
        metric=metric,
        nodes=nodes,
        edges=edges,
        totals=_session_totals(requests, tools),
        assumptions=ASSUMPTIONS,
    )


def _session_totals(requests: list[dict], tools: list[dict]) -> dict[str, Any]:
    return {
        "requests": len(requests),
        "tools": len(tools),
        "input": sum(r["input_tokens"] for r in requests),
        "output": sum(r["output_tokens"] for r in requests),
        "cache_read": sum(r["cache_read_input_tokens"] for r in requests),
        "cache_write": sum(r["cache_creation_input_tokens"] for r in requests),
        "injected": sum(t["tokens"] for t in tools),
        "amplified": sum(t["amplified"] for t in tools),
        "cost_usd": round(sum(weight_usd(r) for r in requests), 4),
    }


def build_graph(
    session_id: str,
    requests: list[dict],
    tools: list[dict],
    view: GraphView,
    metric: GraphMetric,
) -> GraphPayload:
    if view == GraphView.ATTRIBUTION:
        return build_attribution_graph(session_id, requests, tools, metric)
    return build_execution_graph(session_id, requests, tools, metric)


def inspector_for(node: TokenNode, graph: GraphPayload) -> dict[str, Any]:
    connected_ids = set()
    related_edges = []
    for e in graph.edges:
        if e.source == node.id or e.target == node.id:
            related_edges.append(e)
            connected_ids.add(e.source)
            connected_ids.add(e.target)
    connected_ids.discard(node.id)
    connected = [n for n in graph.nodes if n.id in connected_ids]

    amp = node.tokens.amplified
    inj = node.tokens.injected
    affected = node.meta.get("affected_requests")
    explanation_parts = [
        f"{node.type.value.title()} · {node.label}",
    ]
    if inj:
        explanation_parts.append(f"Initial injection ≈ {inj:,} estimated tokens.")
    if amp:
        explanation_parts.append(
            f"Downstream exposure ≈ {amp:,} estimated token-reads."
        )
    if affected is not None:
        explanation_parts.append(f"Affected subsequent requests: {affected}.")
    if node.tokens.total:
        explanation_parts.append(
            f"Observed usage — in {node.tokens.input:,}, out {node.tokens.output:,}, "
            f"cache_r {node.tokens.cache_read:,}, cache_w {node.tokens.cache_write:,}."
        )
    if node.cost_usd is not None:
        explanation_parts.append(
            f"Cost {_fmt_cost(node.cost_usd)} ({node.cost_source.value})."
        )

    hint = node.meta.get("optimization_hint")
    if not hint and amp and amp >= 50_000:
        hint = _optimization_hint(
            str(node.meta.get("tool") or node.type.value),
            node.detail,
            inj or 0,
            amp,
        )

    return {
        "node": node,
        "connected": connected,
        "edges": related_edges,
        "explanation": " ".join(explanation_parts),
        "optimization_hint": hint,
    }


def _fmt_cost(v: float) -> str:
    if v < 0.01:
        return f"${v:.4f}"
    return f"${v:.2f}"
