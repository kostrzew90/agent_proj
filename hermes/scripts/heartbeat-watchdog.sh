#!/usr/bin/env bash
# Heartbeat watchdog — invoke killswitch if hermes goes silent for >60 minutes.
# Hermes is expected to write an ISO-8601 timestamp to ./audit/heartbeat.txt periodically.
#
# Run via: */5 * * * * /path/to/hermes/scripts/heartbeat-watchdog.sh >> /var/log/hermes-watchdog.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$SCRIPT_DIR/../audit"
HEARTBEAT_FILE="$AUDIT_DIR/heartbeat.txt"
TIMEOUT_MINUTES=60

# If no heartbeat file exists yet, nothing to check.
if [ ! -f "$HEARTBEAT_FILE" ]; then
    echo "[watchdog] $(date -Iseconds) heartbeat.txt not found — skipping."
    exit 0
fi

LAST_BEAT=$(cat "$HEARTBEAT_FILE" | tr -d '[:space:]')
NOW_EPOCH=$(date +%s)
LAST_EPOCH=$(date -d "$LAST_BEAT" +%s 2>/dev/null || echo 0)
DIFF_MINUTES=$(( (NOW_EPOCH - LAST_EPOCH) / 60 ))

if [ "$DIFF_MINUTES" -ge "$TIMEOUT_MINUTES" ]; then
    echo "[watchdog] $(date -Iseconds) ALERT: last heartbeat was ${DIFF_MINUTES}m ago — triggering killswitch."

    bash "$SCRIPT_DIR/killswitch.sh" || true

    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="${TELEGRAM_CHAT_ID}" \
            -d text="[Hermes watchdog] Container stopped — heartbeat silent for ${DIFF_MINUTES} minutes. $(date -Iseconds)" \
            > /dev/null
    fi
else
    echo "[watchdog] $(date -Iseconds) OK: last heartbeat ${DIFF_MINUTES}m ago."
fi
