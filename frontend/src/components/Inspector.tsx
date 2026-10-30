import type { GraphPayload, InspectorDetail, TokenNode } from '../types'
import { formatCost, formatTokens, typeColor } from '../lib/metrics'

interface Props {
  detail: InspectorDetail | null
  graph: GraphPayload | null
  loading?: boolean
  onClose: () => void
  onSelectRelated: (id: string) => void
}

export function Inspector({ detail, graph, loading, onClose, onSelectRelated }: Props) {
  if (!detail && !loading) {
    return (
      <aside className="tg-inspector is-empty">
        <p className="tg-inspector-empty">
          Select a node to read the prompt, thinking, and token impact for that step.
        </p>
        {graph && (
          <div className="tg-assumptions">
            <h3>Accounting notes</h3>
            <ul>
              {graph.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        )}
      </aside>
    )
  }

  if (!detail) {
    return (
      <aside className="tg-inspector">
        <p className="tg-muted">Loading…</p>
      </aside>
    )
  }

  const { node } = detail
  const amp = node.tokens.amplified
  const inj = node.tokens.injected
  const userPrompt = strMeta(node, 'user_prompt')
  const thinking = strMeta(node, 'thinking')
  const assistantText = strMeta(node, 'assistant_text')
  const intent = strMeta(node, 'intent')
  const toolSummary = strMeta(node, 'tool_summary')

  return (
    <aside className="tg-inspector">
      <header className="tg-inspector-head">
        <div>
          <span className="tg-pill" style={{ ['--pill' as string]: typeColor(node.type) }}>
            {node.type}
          </span>
          {node.attribution_confidence && (
            <span className={`tg-conf conf-${node.attribution_confidence}`}>
              {node.attribution_confidence} confidence
            </span>
          )}
        </div>
        <button type="button" className="tg-icon-btn" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>

      <h2 className="tg-inspector-title">{node.label}</h2>
      {node.detail && node.detail !== node.label && (
        <p className="tg-path">{node.detail}</p>
      )}
      {node.model && <p className="tg-muted">Model · {node.model}</p>}
      {node.cost_usd != null && (
        <p className="tg-cost-banner">
          {formatCost(node.cost_usd)}
          <span> · {node.cost_source}</span>
        </p>
      )}

      <p className="tg-explanation">{detail.explanation}</p>

      {(userPrompt || thinking || assistantText || intent) && (
        <section className="tg-section tg-narrative">
          <h3>What this step means</h3>
          {userPrompt && <NarrativeBlock title="User prompt" body={userPrompt} tone="prompt" />}
          {thinking && <NarrativeBlock title="Thinking" body={thinking} tone="thinking" />}
          {assistantText && (
            <NarrativeBlock title="Assistant" body={assistantText} tone="assistant" />
          )}
          {intent && !userPrompt && (
            <NarrativeBlock title="Tool intent" body={intent} tone="intent" />
          )}
          {toolSummary && (
            <NarrativeBlock title="Tools in this turn" body={toolSummary} tone="intent" />
          )}
        </section>
      )}

      <div className="tg-stat-grid">
        <Stat label="Injected" value={inj ? formatTokens(inj) : '—'} hint="direct" />
        <Stat label="Amplified" value={amp ? formatTokens(amp) : '—'} hint="token-reads" />
        <Stat
          label="Affected reqs"
          value={
            node.meta.affected_requests != null
              ? String(node.meta.affected_requests)
              : node.meta.calls != null
                ? String(node.meta.calls)
                : '—'
          }
          hint="downstream"
        />
        <Stat
          label="Cost"
          value={formatCost(node.cost_usd)}
          hint={node.cost_source}
        />
      </div>

      {(node.tokens.input || node.tokens.output || node.tokens.cache_read) > 0 && (
        <section className="tg-section">
          <h3>Observed usage</h3>
          <dl className="tg-dl">
            <div><dt>Input</dt><dd>{formatTokens(node.tokens.input)}</dd></div>
            <div><dt>Output</dt><dd>{formatTokens(node.tokens.output)}</dd></div>
            <div><dt>Cache read</dt><dd>{formatTokens(node.tokens.cache_read)}</dd></div>
            <div><dt>Cache write</dt><dd>{formatTokens(node.tokens.cache_write)}</dd></div>
          </dl>
        </section>
      )}

      {detail.optimization_hint && (
        <section className="tg-section tg-opt">
          <h3>Potential optimization</h3>
          <p>{detail.optimization_hint}</p>
        </section>
      )}

      {node.assumptions.length > 0 && (
        <section className="tg-section">
          <h3>How this estimate was calculated</h3>
          <ul className="tg-assumptions-list">
            {node.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </section>
      )}

      {detail.connected.length > 0 && (
        <section className="tg-section">
          <h3>Connected</h3>
          <ul className="tg-related">
            {detail.connected.slice(0, 12).map((n: TokenNode) => (
              <li key={n.id}>
                <button type="button" onClick={() => onSelectRelated(n.id)}>
                  <span className="dot" style={{ background: typeColor(n.type) }} />
                  {n.label}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  )
}

function NarrativeBlock({
  title,
  body,
  tone,
}: {
  title: string
  body: string
  tone: 'prompt' | 'thinking' | 'assistant' | 'intent'
}) {
  return (
    <div className={`tg-narr tg-narr-${tone}`}>
      <span className="tg-narr-title">{title}</span>
      <pre>{body}</pre>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="tg-stat">
      <span className="tg-stat-label">{label}</span>
      <span className="tg-stat-value">{value}</span>
      <span className="tg-stat-hint">{hint}</span>
    </div>
  )
}

function strMeta(node: TokenNode, key: string): string | null {
  const v = node.meta?.[key]
  return typeof v === 'string' && v.trim() ? v : null
}
