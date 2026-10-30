import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { GraphCanvas } from './components/GraphCanvas'
import { Inspector } from './components/Inspector'
import { formatCost, formatTokens } from './lib/metrics'
import type {
  GraphMetric,
  GraphPayload,
  GraphView,
  InspectorDetail,
  SessionSummary,
} from './types'

export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [view, setView] = useState<GraphView>('execution')
  const [metric, setMetric] = useState<GraphMetric>('direct')
  const [graph, setGraph] = useState<GraphPayload | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<InspectorDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const refreshSessions = useCallback(async (preferId?: string) => {
    const list = await api.sessions()
    setSessions(list)
    setSessionId((prev) => preferId || prev || list[0]?.id || null)
  }, [])

  useEffect(() => {
    refreshSessions().catch((e: Error) => setError(e.message))
  }, [refreshSessions])

  useEffect(() => {
    if (!sessionId) return
    setBusy(true)
    setError(null)
    api
      .graph(sessionId, view, metric)
      .then((g) => {
        setGraph(g)
        setSelectedId(null)
        setDetail(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [sessionId, view, metric])

  useEffect(() => {
    if (!sessionId || !selectedId) {
      setDetail(null)
      return
    }
    api
      .node(sessionId, selectedId, view, metric)
      .then(setDetail)
      .catch((e: Error) => setError(e.message))
  }, [sessionId, selectedId, view, metric])

  // Attribution view defaults to amplified metric
  useEffect(() => {
    if (view === 'attribution' && metric === 'direct') {
      setMetric('amplified')
    }
  }, [view, metric])

  const active = sessions.find((s) => s.id === sessionId)

  async function onDemo() {
    setBusy(true)
    setStatus(null)
    try {
      const s = await api.loadDemo()
      await refreshSessions(s.id)
      setStatus('Loaded demo session.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function onImport() {
    setBusy(true)
    setStatus(null)
    try {
      const res = await api.importLocal(30)
      await refreshSessions(res.sessions[0]?.id)
      setStatus(res.message)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="tg-app">
      <header className="tg-hero">
        <div className="tg-hero-copy">
          <p className="tg-brand">Token Graph</p>
          <h1>See where agent tokens go — and why they keep costing.</h1>
          <p className="tg-lede">
            A local-first profiler for Claude Code sessions. Execution shows what happened;
            attribution shows which files, tools, and subagents amplified the bill.
          </p>
        </div>
        <div className="tg-hero-actions">
          <button type="button" className="tg-btn primary" onClick={onDemo} disabled={busy}>
            Load demo
          </button>
          <button type="button" className="tg-btn" onClick={onImport} disabled={busy}>
            Import ~/.claude
          </button>
        </div>
        <div className="tg-hero-glow" aria-hidden />
      </header>

      <div className="tg-toolbar">
        <label className="tg-field">
          <span>Session</span>
          <select
            value={sessionId ?? ''}
            onChange={(e) => setSessionId(e.target.value || null)}
          >
            {sessions.length === 0 && <option value="">No sessions</option>}
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.project} · {s.id.slice(0, 10)} · {s.request_count} reqs
              </option>
            ))}
          </select>
        </label>

        <div className="tg-segment" role="group" aria-label="Graph view">
          <button
            type="button"
            className={view === 'execution' ? 'active' : ''}
            onClick={() => {
              setView('execution')
              setMetric('direct')
            }}
          >
            Execution
          </button>
          <button
            type="button"
            className={view === 'attribution' ? 'active' : ''}
            onClick={() => setView('attribution')}
          >
            Attribution
          </button>
        </div>

        <div className="tg-segment" role="group" aria-label="Metric">
          {(['direct', 'amplified', 'cost'] as GraphMetric[]).map((m) => (
            <button
              key={m}
              type="button"
              className={metric === m ? 'active' : ''}
              onClick={() => setMetric(m)}
            >
              {m === 'direct' ? 'Direct' : m === 'amplified' ? 'Amplified' : 'Cost'}
            </button>
          ))}
        </div>

        <label className="tg-field tg-search">
          <span>Search</span>
          <input
            type="search"
            placeholder="File, tool, request…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>

        {active && graph && (
          <div className="tg-totals">
            <span>{formatTokens(graph.totals.amplified || 0)} amp</span>
            <span>{formatTokens(graph.totals.injected || 0)} injected</span>
            <span>{formatCost(graph.totals.cost_usd)}</span>
          </div>
        )}
      </div>

      {(error || status) && (
        <div className={`tg-banner ${error ? 'is-error' : ''}`}>
          {error || status}
          <button type="button" onClick={() => { setError(null); setStatus(null) }}>
            dismiss
          </button>
        </div>
      )}

      <main className="tg-main">
        <GraphCanvas
          graph={graph}
          view={view}
          metric={metric}
          selectedId={selectedId}
          query={query}
          onSelect={setSelectedId}
        />
        <Inspector
          detail={detail}
          graph={graph}
          onClose={() => setSelectedId(null)}
          onSelectRelated={setSelectedId}
        />
      </main>

      <footer className="tg-footer">
        <span>
          Area scales with the selected metric · Parser adapted from{' '}
          <a href="https://github.com/kelviq/tare" target="_blank" rel="noreferrer">
            tare
          </a>{' '}
          (MIT)
        </span>
        {busy && <span className="tg-muted">Working…</span>}
      </footer>
    </div>
  )
}
