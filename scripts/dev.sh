#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export TOKEN_GRAPH_DB="${TOKEN_GRAPH_DB:-$ROOT/data/token_graph.db}"
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -r "$ROOT/backend/requirements.txt"
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

uvicorn token_graph.main:app --reload --host 127.0.0.1 --port 8000 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run dev -- --host 127.0.0.1 --port 5173
