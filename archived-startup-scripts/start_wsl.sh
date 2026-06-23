#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_SESSION="${BACKEND_SESSION:-open-llm-vtuber}"
FRONTEND_SESSION="${FRONTEND_SESSION:-open-llm-vtuber-frontend}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
CONDA_ENV="${CONDA_ENV:-open-llm-vtuber-py312}"
BACKEND_READY_ATTEMPTS="${BACKEND_READY_ATTEMPTS:-180}"
FRONTEND_READY_ATTEMPTS="${FRONTEND_READY_ATTEMPTS:-40}"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"

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
require_cmd npm
require_cmd curl

ENV_PREFIX=""
if [ -f "$ENV_FILE" ]; then
  ENV_PREFIX="set -a && source '$ENV_FILE' && set +a && "
fi

if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ] && \
  "$CONDA_BASE/bin/conda" env list | awk '{print $1}' | grep -qx "$CONDA_ENV"; then
  BACKEND_COMMAND="${ENV_PREFIX}source '$CONDA_BASE/etc/profile.d/conda.sh' && conda activate '$CONDA_ENV' && cd '$ROOT_DIR' && python run_server.py"
  BACKEND_RUNTIME="conda:$CONDA_ENV"
else
  require_cmd uv
  BACKEND_COMMAND="${ENV_PREFIX}cd '$ROOT_DIR' && uv run run_server.py"
  BACKEND_RUNTIME="uv"
fi

BACKEND_PORT="${BACKEND_PORT:-$(read_backend_port)}"
BACKEND_PORT="${BACKEND_PORT:-18080}"

tmux kill-session -t "$BACKEND_SESSION" 2>/dev/null || true
tmux kill-session -t "$FRONTEND_SESSION" 2>/dev/null || true

tmux new-session -d -s "$BACKEND_SESSION" "$BACKEND_COMMAND"

tmux new-session -d -s "$FRONTEND_SESSION" \
  "cd '$ROOT_DIR/frontend' && npm run dev:web -- --host '$FRONTEND_HOST' --force"

wait_for_url "Backend" "http://$BACKEND_HOST:$BACKEND_PORT/" "$BACKEND_READY_ATTEMPTS"
wait_for_url "Frontend" "http://$FRONTEND_HOST:$FRONTEND_PORT/" "$FRONTEND_READY_ATTEMPTS"

cat <<EOF

Open-LLM-VTuber is running.
Backend runtime: $BACKEND_RUNTIME
Frontend: http://$FRONTEND_HOST:$FRONTEND_PORT/
Backend:  http://$BACKEND_HOST:$BACKEND_PORT/

View logs:
  tmux attach -t $BACKEND_SESSION
  tmux attach -t $FRONTEND_SESSION

Stop:
  tmux kill-session -t $BACKEND_SESSION
  tmux kill-session -t $FRONTEND_SESSION
EOF
