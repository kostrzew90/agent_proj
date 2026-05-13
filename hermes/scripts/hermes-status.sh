#!/usr/bin/env bash
# Print current status of hermes containers, recent audit events, and weekly cost.
# Usage: ./scripts/hermes-status.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$SCRIPT_DIR/../audit"

echo "=== Container status ==="
docker ps --filter "name=hermes" --filter "name=mcp-postgres-ro" --filter "name=mcp-fs-safe" \
    --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"

echo ""
echo "=== Recent audit log (last 20 lines) ==="
if [ -f "$AUDIT_DIR/killswitch.log" ]; then
    tail -n 20 "$AUDIT_DIR/killswitch.log"
else
    echo "(no killswitch.log yet)"
fi

echo ""
echo "=== Weekly LLM cost ==="
COSTS_FILE="$AUDIT_DIR/costs.jsonl"
if [ -f "$COSTS_FILE" ]; then
    # Sum cost_usd field for entries within the last 7 days.
    # Requires python3 on the host.
    python3 - "$COSTS_FILE" <<'EOF'
import sys, json, datetime

now = datetime.datetime.utcnow()
week_ago = now - datetime.timedelta(days=7)
total = 0.0
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = datetime.datetime.fromisoformat(entry.get("ts", ""))
            if ts >= week_ago:
                total += float(entry.get("cost_usd", 0))
        except Exception:
            pass
print(f"Weekly total: ${total:.4f} USD")
EOF
else
    echo "(no costs.jsonl yet — $COSTS_FILE not found)"
fi
