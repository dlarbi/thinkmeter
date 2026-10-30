"""Core data contracts between analysis and rendering."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    REQUEST = "request"
    TOOL = "tool"
    FILE = "file"
    AGENT = "agent"
    PROMPT = "prompt"
    THINKING = "thinking"
    CONTEXT = "context"
    SESSION = "session"
    COMPACTION = "compaction"


class EdgeRelation(str, Enum):
    CALLS = "calls"
    RETURNS = "returns"
    RETAINS = "retains"
    FOLLOWS = "follows"
    CONTAINS = "contains"


class CostSource(str, Enum):
    REPORTED = "reported"
    ESTIMATED = "estimated"


class AttributionConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TokenBreakdown(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    injected: int = 0
    amplified: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    @property
    def direct(self) -> int:
        return self.injected or self.total


class TokenNode(BaseModel):
    id: str
    type: NodeType
    label: str
    parent_id: Optional[str] = None
    tokens: TokenBreakdown = Field(default_factory=TokenBreakdown)
    cost_usd: Optional[float] = None
    cost_source: CostSource = CostSource.ESTIMATED
    attribution_confidence: Optional[AttributionConfidence] = None
    model: Optional[str] = None
    timestamp: Optional[str] = None
    detail: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)


class TokenEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: EdgeRelation
    estimated_tokens: Optional[int] = None
    label: Optional[str] = None


class SessionSummary(BaseModel):
    id: str
    project: str
    title: Optional[str] = None
    preview: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    request_count: int = 0
    tool_count: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    models: list[str] = Field(default_factory=list)
    source: Literal["demo", "import", "claude-code"] = "import"


class GraphView(str, Enum):
    EXECUTION = "execution"
    ATTRIBUTION = "attribution"


class GraphMetric(str, Enum):
    DIRECT = "direct"
    AMPLIFIED = "amplified"
    COST = "cost"


class GraphPayload(BaseModel):
    session_id: str
    view: GraphView
    metric: GraphMetric
    nodes: list[TokenNode]
    edges: list[TokenEdge]
    totals: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)


class InspectorDetail(BaseModel):
    node: TokenNode
    connected: list[TokenNode] = Field(default_factory=list)
    edges: list[TokenEdge] = Field(default_factory=list)
    explanation: str = ""
    optimization_hint: Optional[str] = None


class ImportResult(BaseModel):
    sessions: list[SessionSummary]
    message: str
