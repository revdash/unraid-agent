#!/bin/bash
# Daily health check via unraid-agent.
# Runs phase-1 read-only check, logs full output, and only sends an
# Unraid notification if the result suggests a real problem -- not a
# clean daily ping regardless of outcome.

set -e

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$AGENT_DIR/logs"
DATE=$(date '+%Y-%m-%d_%H-%M-%S')
OUT_FILE="$LOG_DIR/daily_healthcheck_$DATE.log"

mkdir -p "$LOG_DIR"

"$AGENT_DIR/agent.sh" healthcheck > "$OUT_FILE" 2>&1

SUMMARY=$(grep '^\[done\]' "$OUT_FILE" | tail -1 | sed 's/^\[done\] //')

# Keep only the last 30 days of daily logs.
find "$LOG_DIR" -name "daily_healthcheck_*.log" -mtime +30 -delete

# Flag words that suggest a real problem worth a notification.
if echo "$SUMMARY" | grep -qiE "unhealthy|not running|stopped|restart|fail|error|down"; then
  /usr/local/emhttp/webGui/scripts/notify \
    -e "unraid-agent" \
    -s "Container health check flagged an issue" \
    -d "$SUMMARY" \
    -i "warning"
fi
