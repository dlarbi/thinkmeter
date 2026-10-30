# Token Graph

**A visual profiler for AI agents** — see where tokens go, why they go there, and how context amplifies cost across a session.

Token Graph is a local-first, read-only Claude Code profiler. It reuses [tare](https://github.com/kelviq/tare)-style transcript accounting, then renders two React Flow graphs:

- **Execution** — left-to-right timeline of requests and tools (“what happened?”)
- **Attribution** — grouped sources of context impact (“why was it expensive?”)

Node **area** scales with Direct tokens, Amplified token-reads, or estimated Cost. Click a node for injection size, downstream exposure, cache notes, and optimization hints.

## Quick start

```bash
# Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
export PYTHONPATH=backend
export TOKEN_GRAPH_DB="$PWD/data/token_graph.db"
uvicorn token_graph.main:app --reload --port 8000

# Frontend (another terminal)
cd frontend && npm install && npm run dev
```

Open http://127.0.0.1:5173 — a demo session loads automatically.

Or run both via `./scripts/dev.sh`.

### Import real Claude Code sessions

In the UI click **Import ~/.claude**, or:

```bash
curl -X POST http://127.0.0.1:8000/api/import -H 'content-type: application/json' -d '{"days":30}'
```

Transcripts are read from `~/.claude/projects/**/*.jsonl`. Nothing leaves your machine.

## Architecture

| Layer | Stack |
|---|---|
| Token analysis | Adapted from tare / ccaudit (MIT) |
| API | Python · FastAPI |
| Storage | SQLite (`data/token_graph.db`) |
| UI | React · TypeScript · React Flow · Dagre |

### Data model

```ts
type TokenNode = {
  id: string
  type: 'request' | 'tool' | 'file' | 'agent' | 'prompt' | 'context' | …
  tokens: { input, output, cacheRead, cacheWrite, injected?, amplified? }
  costUsd?: number
  costSource: 'reported' | 'estimated'
  attributionConfidence?: 'high' | 'medium' | 'low'
}
```

**Direct** = tokens a tool/file injects once.  
**Amplified** = injected × subsequent requests assumed to still carry that context.  
Request costs are aggregated once; source costs are *allocated* shares — never double-counted on top of parent requests.

Assumptions (compaction, `/clear`, cache expiry) are shown in the inspector — amplification can overstate impact when context was dropped.

## MVP scope

Shipped:

1. Import / demo Claude Code sessions  
2. Execution + attribution graphs with metric switching  
3. File / MCP / subagent / skill attribution  
4. Detail inspector, zoom, minimap  

Deferred: live OpenTelemetry capture, savings simulation, multi-provider adapters.

## License

MIT. Parser logic adapted from [kelviq/tare](https://github.com/kelviq/tare) (MIT).
