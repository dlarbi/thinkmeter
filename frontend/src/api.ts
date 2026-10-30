import type {
  GraphMetric,
  GraphPayload,
  GraphView,
  InspectorDetail,
  SessionSummary,
} from './types'

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json() as Promise<T>
}

async function post<T>(url: string, body: unknown = {}): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json() as Promise<T>
}

export const api = {
  sessions: () => get<SessionSummary[]>('/api/sessions'),
  graph: (id: string, view: GraphView, metric: GraphMetric) =>
    get<GraphPayload>(
      `/api/sessions/${encodeURIComponent(id)}/graph?view=${view}&metric=${metric}`,
    ),
  node: (sessionId: string, nodeId: string, view: GraphView, metric: GraphMetric) =>
    get<InspectorDetail>(
      `/api/sessions/${encodeURIComponent(sessionId)}/nodes/${encodeURIComponent(nodeId)}?view=${view}&metric=${metric}`,
    ),
  loadDemo: () => post<SessionSummary>('/api/demo', { force: true }),
  importLocal: (days = 30) =>
    post<{ sessions: SessionSummary[]; message: string }>('/api/import', { days }),
}
