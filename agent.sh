#!/bin/bash
# unraid-agent wrapper
#
# Usage:
#   ./agent "check AI stack"
#   ./agent "repair failed containers" --phase 2
#   ./agent "check container health"          # phase defaults to 1
#
# Common shortcuts (no quotes needed):
#   ./agent healthcheck
#   ./agent repair
#
# Requires a .env file in this directory -- copy env.example to .env
# and fill in your server's details first.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing .env file. Copy env.example to .env and fill in your details first."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${UNRAID_HOST:?Set UNRAID_HOST in .env}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH in .env}"

PHASE="${AGENT_PHASE:-1}"
GOAL=""

case "$1" in
  healthcheck)
    GOAL="check container health, flag anything stopped or unhealthy"
    PHASE=1
    ;;
  repair)
    GOAL="check for stopped or unhealthy containers and start any that should be running"
    PHASE=2
    ;;
  *)
    GOAL="$1"
    ;;
esac

# Optional --phase override, e.g.: ./agent "my goal" --phase 2
if [ "$2" = "--phase" ] && [ -n "$3" ]; then
  PHASE="$3"
fi

if [ -z "$GOAL" ]; then
  echo "Usage: ./agent \"<goal>\" [--phase N]   or   ./agent healthcheck|repair"
  exit 1
fi

if [ -t 0 ]; then
  DOCKER_TTY_FLAGS="-it"
else
  DOCKER_TTY_FLAGS="-i"
fi

RUN_NAME="unraid-agent-run-$$"

docker run --rm $DOCKER_TTY_FLAGS \
  --name "$RUN_NAME" \
  --network host \
  -v "$SCRIPT_DIR:/app" \
  -v "$SSH_KEY_PATH:/root/.ssh/agent_key:ro" \
  -w /app \
  -e UNRAID_HOST="$UNRAID_HOST" \
  -e UNRAID_USER="${UNRAID_USER:-ai-agent}" \
  -e UNRAID_KEY_PATH=/root/.ssh/agent_key \
  -e OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}" \
  -e OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1:8b}" \
  -e AGENT_PHASE="$PHASE" \
  -e AUDIT_LOG_PATH=/app/logs/agent_audit.jsonl \
  -e SELF_CONTAINER_NAME="$RUN_NAME" \
  -e CONTAINER_SCOPE_PREFIX="${CONTAINER_SCOPE_PREFIX:-agent-}" \
  -e DOCKER_PROXY_PORT="${DOCKER_PROXY_PORT:-2375}" \
  python:3.12-slim \
  bash -c "pip install -q -r requirements.txt && python3 agent.py '$GOAL'"
