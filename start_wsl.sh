#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_SESSION="${BACKEND_SESSION:-open-llm-vtuber}"
FRONTEND_SESSION="${FRONTEND_SESSION:-open-llm-vtuber-frontend}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

read_backend_port() {
  awk '
    /^system_config:/ { in_system = 1; next }
    in_system && /^[^[:space:]]/ { in_system = 0 }
    in_system && /^[[:space:]]+port:[[:space:]]*[0-9]+/ {
      gsub(/[^0-9]/, "", $0)
      print $0
      exit
    }
  ' "$ROOT_DIR/conf.yaml"
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-40}"

  for _ in $(seq 1 "$attempts"); do
    if curl -fsS -I --max-time 2 "$url" >/dev/null 2>&1; then
      echo "$name ready: $url"
      return 0
    fi
    sleep 1
  done

  echo "$name did not become ready in time: $url" >&2
  return 1
}

require_cmd tmux
require_cmd uv
require_cmd npm
require_cmd curl

BACKEND_PORT="${BACKEND_PORT:-$(read_backend_port)}"
BACKEND_PORT="${BACKEND_PORT:-18080}"

tmux kill-session -t "$BACKEND_SESSION" 2>/dev/null || true
tmux kill-session -t "$FRONTEND_SESSION" 2>/dev/null || true

tmux new-session -d -s "$BACKEND_SESSION" \
  "cd '$ROOT_DIR' && uv run run_server.py"

tmux new-session -d -s "$FRONTEND_SESSION" \
  "cd '$ROOT_DIR/frontend' && npm run dev:web -- --host '$FRONTEND_HOST' --force"

wait_for_url "Backend" "http://$BACKEND_HOST:$BACKEND_PORT/"
wait_for_url "Frontend" "http://$FRONTEND_HOST:$FRONTEND_PORT/"

cat <<EOF

Open-LLM-VTuber is running.
Frontend: http://$FRONTEND_HOST:$FRONTEND_PORT/
Backend:  http://$BACKEND_HOST:$BACKEND_PORT/

View logs:
  tmux attach -t $BACKEND_SESSION
  tmux attach -t $FRONTEND_SESSION

Stop:
  tmux kill-session -t $BACKEND_SESSION
  tmux kill-session -t $FRONTEND_SESSION
EOF
