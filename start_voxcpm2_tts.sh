#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TTS_DIR="${TTS_DIR:-/mnt/c/AI/fay}"
TTS_SESSION="${TTS_SESSION:-voxcpm2-nanovllm}"
TTS_HOST="${TTS_HOST:-0.0.0.0}"
TTS_PORT="${TTS_PORT:-50005}"
HEALTH_HOST="${HEALTH_HOST:-127.0.0.1}"
HEALTH_URL="http://${HEALTH_HOST}:${TTS_PORT}/health"
WAIT_ATTEMPTS="${WAIT_ATTEMPTS:-180}"

RESTART=0
NO_WAIT=0
ATTACH=0
STOP=0
STATUS=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--restart] [--no-wait] [--attach] [--stop] [--status]

Starts VoxCPM2 NanoVLLM TTS in tmux.

Environment overrides:
  TTS_DIR      default: /mnt/c/AI/fay
  TTS_SESSION  default: voxcpm2-nanovllm
  TTS_HOST     default: 0.0.0.0
  TTS_PORT     default: 50005
  HEALTH_HOST  default: 127.0.0.1

Examples:
  ./start_voxcpm2_tts.sh
  ./start_voxcpm2_tts.sh --restart
  ./start_voxcpm2_tts.sh --attach
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

is_healthy() {
  curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1
}

print_health() {
  curl -fsS --max-time 2 "$HEALTH_URL"
  echo
}

stop_service() {
  tmux kill-session -t "$TTS_SESSION" 2>/dev/null || true

  local pids
  pids="$(pgrep -f '[v]oxcpm2_nanovllm_http_server.py' 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
  fi
}

wait_for_health() {
  local attempt
  for attempt in $(seq 1 "$WAIT_ATTEMPTS"); do
    if is_healthy; then
      echo "VoxCPM2 NanoVLLM TTS is ready:"
      print_health
      return 0
    fi

    if ! tmux has-session -t "$TTS_SESSION" 2>/dev/null; then
      echo "tmux session exited before TTS became ready: $TTS_SESSION" >&2
      return 1
    fi

    if (( attempt % 10 == 0 )); then
      echo "waiting VoxCPM2 NanoVLLM TTS ($attempt/$WAIT_ATTEMPTS): $HEALTH_URL"
    fi
    sleep 2
  done

  echo "VoxCPM2 NanoVLLM TTS did not become ready: $HEALTH_URL" >&2
  echo "Recent tmux output:" >&2
  tmux capture-pane -t "$TTS_SESSION" -p -S -80 >&2 || true
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart)
      RESTART=1
      ;;
    --no-wait)
      NO_WAIT=1
      ;;
    --attach)
      ATTACH=1
      ;;
    --stop)
      STOP=1
      ;;
    --status)
      STATUS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

require_cmd tmux
require_cmd curl

if (( STOP )); then
  stop_service
  echo "Stopped VoxCPM2 NanoVLLM TTS tmux session/processes."
  exit 0
fi

if (( STATUS )); then
  if is_healthy; then
    print_health
    exit 0
  fi
  echo "VoxCPM2 NanoVLLM TTS is not healthy at $HEALTH_URL" >&2
  exit 1
fi

if (( ATTACH )); then
  exec tmux attach -t "$TTS_SESSION"
fi

if is_healthy && (( ! RESTART )); then
  echo "VoxCPM2 NanoVLLM TTS is already running:"
  print_health
  echo "Logs: tmux attach -t $TTS_SESSION"
  exit 0
fi

if [[ ! -x "$TTS_DIR/Start-VoxCPM2-NanoVLLM-WSL.sh" ]]; then
  echo "Missing executable starter: $TTS_DIR/Start-VoxCPM2-NanoVLLM-WSL.sh" >&2
  exit 1
fi

stop_service
sleep 1

tmux new-session -d -s "$TTS_SESSION" \
  "cd '$TTS_DIR' && \
   VOXCPM2_HOST='$TTS_HOST' \
   VOXCPM2_PORT='$TTS_PORT' \
   VOXCPM2_INFERENCE_TIMESTEPS='${VOXCPM2_INFERENCE_TIMESTEPS:-5}' \
   VOXCPM2_GPU_MEMORY_UTILIZATION='${VOXCPM2_GPU_MEMORY_UTILIZATION:-0.35}' \
   VOXCPM2_MAX_NUM_BATCHED_TOKENS='${VOXCPM2_MAX_NUM_BATCHED_TOKENS:-2304}' \
   VOXCPM2_MAX_NUM_SEQS='${VOXCPM2_MAX_NUM_SEQS:-2}' \
   VOXCPM2_MAX_MODEL_LEN='${VOXCPM2_MAX_MODEL_LEN:-2304}' \
   VOXCPM2_ENFORCE_EAGER='${VOXCPM2_ENFORCE_EAGER:-0}' \
   exec ./Start-VoxCPM2-NanoVLLM-WSL.sh"

echo "Started VoxCPM2 NanoVLLM TTS in tmux session: $TTS_SESSION"
echo "Health: $HEALTH_URL"

if (( NO_WAIT )); then
  echo "Skipped health wait."
  echo "Logs: tmux attach -t $TTS_SESSION"
  exit 0
fi

wait_for_health
echo "Voice lab: http://${HEALTH_HOST}:${TTS_PORT}/"
echo "Logs: tmux attach -t $TTS_SESSION"
