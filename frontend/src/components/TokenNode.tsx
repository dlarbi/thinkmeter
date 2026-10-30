import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { SizedNodeData } from '../lib/layout'
import { typeColor } from '../lib/metrics'

function TokenNodeComponent({ data, selected }: NodeProps) {
  const d = data as SizedNodeData
  const size = d.diameter
  const color = typeColor(d.type)
  const isGroup = d.raw.meta?.kind === 'group'
  const isSink = d.raw.meta?.kind === 'sink' || d.raw.meta?.fixed_size
  const isNarrative = d.type === 'thinking' || d.type === 'prompt' || d.raw.meta?.kind === 'narrative'

  return (
    <div
      className={`tg-node ${selected ? 'is-selected' : ''} ${isGroup ? 'is-group' : ''} ${isSink ? 'is-sink' : ''} ${isNarrative ? 'is-narrative' : ''}`}
      style={{
        width: size,
        height: size,
        ['--node-accent' as string]: color,
      }}
      title={[d.label, d.metricLabel, d.costLabel, d.preview].filter(Boolean).join(' · ')}
    >
      <Handle type="target" position={Position.Left} className="tg-handle" />
      <div className="tg-node-inner">
        <span className="tg-node-type">{d.type}</span>
        <span className="tg-node-label">{d.label}</span>
        <span className="tg-node-metric">
          {d.metricLabel}
          {d.costLabel ? <span className="tg-node-cost"> · {d.costLabel}</span> : null}
        </span>
      </div>
      <Handle type="source" position={Position.Right} className="tg-handle" />
    </div>
  )
}

export default memo(TokenNodeComponent)
