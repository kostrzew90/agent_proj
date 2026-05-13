#!/usr/bin/env bash
# Stop all Hermes-related containers. Idempotent — no error on missing containers.
set -uo pipefail   # NO -e — we want to continue past missing containers
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="${SCRIPT_DIR}/../audit"
mkdir -p "$AUDIT_DIR"
LOG="$AUDIT_DIR/killswitch.log"

TS="$(date -Iseconds)"
echo "[killswitch] $TS initiated by ${USER:-unknown} pid=$$" | tee -a "$LOG"

for svc in hermes mcp-postgres-ro mcp-fs-safe; do
    if docker ps --format '{{.Names}}' | grep -q "^${svc}$"; then
        docker stop "$svc" >/dev/null 2>&1 && \
            echo "[killswitch] $TS stopped $svc" | tee -a "$LOG" || \
            echo "[killswitch] $TS FAILED to stop $svc" | tee -a "$LOG"
    else
        echo "[killswitch] $TS $svc not running" | tee -a "$LOG"
    fi
done

echo "[killswitch] $TS complete" | tee -a "$LOG"
