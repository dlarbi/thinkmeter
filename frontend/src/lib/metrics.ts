import type { GraphMetric, TokenNode } from '../types'

/** Metric value used for node *area* scaling. */
export function metricValue(node: TokenNode, metric: GraphMetric): number {
  if (node.meta?.fixed_size) {
    // Destination sink: use observed total, not amplified sources
    return Math.max(node.tokens.input + node.tokens.output + node.tokens.cache_read, 1)
  }
  switch (metric) {
    case 'amplified':
      return node.tokens.amplified || node.tokens.injected || observedTotal(node)
    case 'cost':
      return node.cost_usd != null ? node.cost_usd * 1_000_000 : observedTotal(node)
    case 'direct':
    default:
      return node.tokens.injected || observedTotal(node)
  }
}

export function observedTotal(node: TokenNode): number {
  const t = node.tokens
  return t.input + t.output + t.cache_read + t.cache_write || t.injected || 1
}

/** Convert value → pixel diameter so *area* ∝ value. */
export function diameterFor(
  value: number,
  maxValue: number,
  minPx = 36,
  maxPx = 120,
): number {
  if (maxValue <= 0) return minPx
  const areaRatio = Math.max(0, value) / maxValue
  const minA = minPx * minPx
  const maxA = maxPx * maxPx
  const area = minA + areaRatio * (maxA - minA)
  return Math.sqrt(area)
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return `${Math.round(n)}`
}

export function formatCost(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

export function typeColor(type: string): string {
  switch (type) {
    case 'request':
      return 'var(--c-request)'
    case 'file':
      return 'var(--c-file)'
    case 'tool':
      return 'var(--c-tool)'
    case 'agent':
      return 'var(--c-agent)'
    case 'prompt':
      return 'var(--c-prompt)'
    case 'thinking':
      return 'var(--c-thinking)'
    case 'context':
      return 'var(--c-context)'
    case 'session':
      return 'var(--c-session)'
    default:
      return 'var(--c-tool)'
  }
}
