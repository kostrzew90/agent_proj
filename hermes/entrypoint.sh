#!/usr/bin/env bash
set -euo pipefail

MARKER="/home/hermes/.hermes-installed"

if [ ! -f "$MARKER" ]; then
    echo "[entrypoint] First run — installing hermes-agent..."
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
    touch "$MARKER"
    echo "[entrypoint] Installation complete."
fi

if [ "${HERMES_IDLE:-0}" = "1" ]; then
    echo "[entrypoint] HERMES_IDLE=1 — sleeping for debug."
    exec sleep infinity
fi

exec hermes
