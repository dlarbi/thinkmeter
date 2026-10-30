import dagre from 'dagre'
import type { Edge, Node } from '@xyflow/react'
import type { GraphMetric, GraphPayload, GraphView } from '../types'
import { diameterFor, metricValue } from './metrics'

export interface SizedNodeData {
  label: string
  type: string
  diameter: number
  metricLabel: string
  raw: GraphPayload['nodes'][number]
  [key: string]: unknown
}

export function layoutGraph(
  payload: GraphPayload,
  view: GraphView,
  metric: GraphMetric,
): { nodes: Node<SizedNodeData>[]; edges: Edge[] } {
  const values = payload.nodes.map((n) => metricValue(n, metric))
  const maxVal = Math.max(...values, 1)

  const rfNodes: Node<SizedNodeData>[] = payload.nodes.map((n, i) => {
    const value = values[i]
    const diameter = n.meta?.kind === 'group'
      ? 56
      : n.type === 'session' || (n.meta?.kind === 'sink' && view === 'attribution')
        ? 72
        : diameterFor(value, maxVal, view === 'attribution' ? 44 : 40, view === 'attribution' ? 140 : 110)

    return {
      id: n.id,
      type: 'token',
      position: { x: 0, y: 0 },
      data: {
        label: n.label,
        type: n.type,
        diameter,
        metricLabel: formatMetricLabel(value, metric),
        raw: n,
      },
      style: { width: diameter, height: diameter },
    }
  })

  const rfEdges: Edge[] = payload.edges
    .filter((e) => {
      // Keep the graph readable: skip reverse retain edges in execution view
      if (view === 'execution' && e.relation === 'retains') return false
      return true
    })
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: e.relation === 'follows',
      label: e.label ?? undefined,
      style: {
        stroke:
          e.relation === 'follows'
            ? 'var(--edge-follow)'
            : e.relation === 'calls'
              ? 'var(--edge-call)'
              : 'var(--edge-default)',
        strokeWidth: e.relation === 'follows' ? 2 : 1.25,
      },
    }))

  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({
    rankdir: view === 'execution' ? 'LR' : 'TB',
    nodesep: view === 'execution' ? 28 : 36,
    ranksep: view === 'execution' ? 72 : 64,
    marginx: 40,
    marginy: 40,
  })

  for (const n of rfNodes) {
    const d = n.data.diameter
    g.setNode(n.id, { width: d, height: d })
  }
  for (const e of rfEdges) {
    g.setEdge(e.source, e.target)
  }
  dagre.layout(g)

  return {
    nodes: rfNodes.map((n) => {
      const pos = g.node(n.id)
      const d = n.data.diameter
      return {
        ...n,
        position: { x: pos.x - d / 2, y: pos.y - d / 2 },
      }
    }),
    edges: rfEdges,
  }
}

function formatMetricLabel(value: number, metric: GraphMetric): string {
  if (metric === 'cost') {
    const usd = value / 1_000_000
    return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`
  }
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return `${Math.round(value)}`
}
