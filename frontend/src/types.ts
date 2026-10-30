export type NodeType =
  | 'request'
  | 'tool'
  | 'file'
  | 'agent'
  | 'prompt'
  | 'thinking'
  | 'context'
  | 'session'
  | 'compaction'

export type EdgeRelation = 'calls' | 'returns' | 'retains' | 'follows' | 'contains'
export type GraphView = 'execution' | 'attribution'
export type GraphMetric = 'direct' | 'amplified' | 'cost'

export interface TokenBreakdown {
  input: number
  output: number
  cache_read: number
  cache_write: number
  injected: number
  amplified: number
}

export interface TokenNode {
  id: string
  type: NodeType
  label: string
  parent_id?: string | null
  tokens: TokenBreakdown
  cost_usd?: number | null
  cost_source: 'reported' | 'estimated'
  attribution_confidence?: 'high' | 'medium' | 'low' | null
  model?: string | null
  timestamp?: string | null
  detail?: string | null
  meta: Record<string, unknown>
  assumptions: string[]
}

export interface TokenEdge {
  id: string
  source: string
  target: string
  relation: EdgeRelation
  estimated_tokens?: number | null
  label?: string | null
}

export interface SessionSummary {
  id: string
  project: string
  title?: string | null
  preview?: string | null
  started_at?: string | null
  ended_at?: string | null
  request_count: number
  tool_count: number
  total_tokens: number
  cost_usd: number
  models: string[]
  source: 'demo' | 'import' | 'claude-code'
}

export interface GraphPayload {
  session_id: string
  view: GraphView
  metric: GraphMetric
  nodes: TokenNode[]
  edges: TokenEdge[]
  totals: Record<string, number>
  assumptions: string[]
}

export interface InspectorDetail {
  node: TokenNode
  connected: TokenNode[]
  edges: TokenEdge[]
  explanation: string
  optimization_hint?: string | null
}
