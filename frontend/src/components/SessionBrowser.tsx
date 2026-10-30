import { useMemo, useState } from 'react'
import type { SessionSummary } from '../types'
import { formatCost, formatTokens } from '../lib/metrics'

type SortKey = 'recent' | 'cost' | 'tokens' | 'requests'

interface Props {
  sessions: SessionSummary[]
  activeId: string | null
  onSelect: (id: string) => void
  collapsed?: boolean
  onToggle?: () => void
}

export function SessionBrowser({
  sessions,
  activeId,
  onSelect,
  collapsed,
  onToggle,
}: Props) {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<SortKey>('recent')
  const [projectFilter, setProjectFilter] = useState<string>('all')

  const projects = useMemo(() => {
    const set = new Set(sessions.map((s) => s.project))
    return ['all', ...Array.from(set).sort()]
  }, [sessions])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    let list = sessions.filter((s) => {
      if (projectFilter !== 'all' && s.project !== projectFilter) return false
      if (!needle) return true
      const hay = [
        s.title,
        s.preview,
        s.project,
        s.id,
        s.source,
        ...(s.models || []),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return hay.includes(needle)
    })
    list = [...list].sort((a, b) => {
      switch (sort) {
        case 'cost':
          return (b.cost_usd || 0) - (a.cost_usd || 0)
        case 'tokens':
          return (b.total_tokens || 0) - (a.total_tokens || 0)
        case 'requests':
          return (b.request_count || 0) - (a.request_count || 0)
        case 'recent':
        default:
          return (b.started_at || '').localeCompare(a.started_at || '')
      }
    })
    return list
  }, [sessions, q, sort, projectFilter])

  const grouped = useMemo(() => {
    const map = new Map<string, SessionSummary[]>()
    for (const s of filtered) {
      const key = s.project || '(unknown)'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(s)
    }
    return Array.from(map.entries())
  }, [filtered])

  if (collapsed) {
    return (
      <aside className="tg-sessions is-collapsed">
        <button type="button" className="tg-sessions-expand" onClick={onToggle}>
          Sessions ({sessions.length})
        </button>
      </aside>
    )
  }

  return (
    <aside className="tg-sessions">
      <header className="tg-sessions-head">
        <div>
          <h2>Sessions</h2>
          <p className="tg-muted">{sessions.length} loaded</p>
        </div>
        {onToggle && (
          <button type="button" className="tg-icon-btn" onClick={onToggle} aria-label="Collapse">
            ‹
          </button>
        )}
      </header>

      <input
        className="tg-sessions-search"
        type="search"
        placeholder="Search title, project, id…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />

      <div className="tg-sessions-filters">
        <select value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p === 'all' ? 'All projects' : decodeProject(p)}
            </option>
          ))}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          <option value="recent">Newest</option>
          <option value="cost">Highest cost</option>
          <option value="tokens">Most tokens</option>
          <option value="requests">Most requests</option>
        </select>
      </div>

      <div className="tg-sessions-list">
        {filtered.length === 0 && (
          <p className="tg-sessions-empty">No sessions match. Import ~/.claude or load the demo.</p>
        )}
        {grouped.map(([project, items]) => (
          <section key={project} className="tg-sessions-group">
            <h3>{decodeProject(project)}</h3>
            <ul>
              {items.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className={`tg-session-card ${s.id === activeId ? 'is-active' : ''}`}
                    onClick={() => onSelect(s.id)}
                  >
                    <span className="tg-session-title">
                      {s.title || shortId(s.id)}
                    </span>
                    {s.preview && s.preview !== s.title && (
                      <span className="tg-session-preview">{s.preview}</span>
                    )}
                    <span className="tg-session-meta">
                      <span>{formatCost(s.cost_usd)}</span>
                      <span>{formatTokens(s.total_tokens)}</span>
                      <span>{s.request_count} reqs</span>
                      <span className="tg-session-source">{s.source}</span>
                    </span>
                    <span className="tg-session-when">{formatWhen(s.started_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  )
}

function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}

function decodeProject(p: string): string {
  try {
    return decodeURIComponent(p.replace(/-/g, '%'))
  } catch {
    return p.length > 40 ? `…${p.slice(-36)}` : p
  }
}

function formatWhen(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 16)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
