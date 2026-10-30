import { useEffect, useMemo } from 'react'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import type { GraphMetric, GraphPayload, GraphView } from '../types'
import { layoutGraph, type SizedNodeData } from '../lib/layout'
import { typeColor } from '../lib/metrics'
import TokenNode from './TokenNode'

const nodeTypes: NodeTypes = {
  token: TokenNode,
}

interface Props {
  graph: GraphPayload | null
  view: GraphView
  metric: GraphMetric
  selectedId: string | null
  query?: string
  onSelect: (id: string | null) => void
}

export function GraphCanvas({ graph, view, metric, selectedId, query = '', onSelect }: Props) {
  const laid = useMemo(
    () => (graph ? layoutGraph(graph, view, metric) : { nodes: [], edges: [] }),
    [graph, view, metric],
  )

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<SizedNodeData>>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  useEffect(() => {
    const q = query.trim().toLowerCase()
    setNodes(
      laid.nodes.map((n) => {
        const hay = `${n.data.label} ${n.data.raw.detail ?? ''} ${n.data.type}`.toLowerCase()
        const match = !q || hay.includes(q)
        return {
          ...n,
          selected: n.id === selectedId,
          style: {
            ...n.style,
            opacity: match ? 1 : 0.22,
          },
        }
      }),
    )
    setEdges(laid.edges)
  }, [laid, selectedId, query, setNodes, setEdges])

  return (
    <div className="tg-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.2}
        maxZoom={1.8}
        onNodeClick={(_, n) => onSelect(n.id)}
        onPaneClick={() => onSelect(null)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={22} size={1} color="rgba(20, 48, 46, 0.08)" />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => typeColor(String((n.data as SizedNodeData)?.type || 'tool'))}
          maskColor="rgba(244, 247, 245, 0.7)"
        />
      </ReactFlow>
    </div>
  )
}
