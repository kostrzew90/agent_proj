#!/bin/bash
set -e

# ─── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ─── Helpers ──────────────────────────────────────────────────────────────────
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
hdr()  { echo -e "\n${BOLD}$*${NC}"; }

PSQL="docker exec rag-postgres psql -U rag -d rag"
CELERY="docker exec rag-worker celery -A tasks.celery_app"

# ─── status ───────────────────────────────────────────────────────────────────
cmd_status() {
    hdr "=== Document counts by status ==="
    $PSQL -c "
        SELECT status, COUNT(*) AS count
        FROM documents
        GROUP BY status
        ORDER BY status;
    " 2>/dev/null && ok "documents query OK" || err "Could not query documents table"

    hdr "=== Task counts by status ==="
    $PSQL -c "
        SELECT status, COUNT(*) AS count
        FROM tasks
        GROUP BY status
        ORDER BY status;
    " 2>/dev/null && ok "tasks query OK" || warn "tasks table not found or empty"

    hdr "=== Active Celery tasks ==="
    docker exec rag-worker celery -A tasks.celery_app inspect active --timeout 5 2>/dev/null \
        && ok "celery inspect OK" \
        || warn "Could not reach Celery worker (may be idle or offline)"
}

# ─── stuck ────────────────────────────────────────────────────────────────────
cmd_stuck() {
    hdr "=== Tasks stuck in 'running' for more than 1 hour ==="
    RESULT=$($PSQL -t -c "
        SELECT id, source_url, status, updated_at,
               EXTRACT(EPOCH FROM (NOW() - updated_at))/3600 AS hours_running
        FROM documents
        WHERE status = 'running'
          AND updated_at < NOW() - INTERVAL '1 hour'
        ORDER BY updated_at;
    " 2>/dev/null)

    if [ -z "$(echo "$RESULT" | tr -d '[:space:]')" ]; then
        ok "No stuck documents found"
    else
        warn "Stuck documents:"
        echo "$RESULT"
    fi

    hdr "=== Task records stuck in 'running' for more than 1 hour ==="
    RESULT2=$($PSQL -t -c "
        SELECT id, task_type, status, started_at,
               EXTRACT(EPOCH FROM (NOW() - started_at))/3600 AS hours_running
        FROM tasks
        WHERE status = 'running'
          AND started_at < NOW() - INTERVAL '1 hour'
        ORDER BY started_at;
    " 2>/dev/null)

    if [ -z "$(echo "$RESULT2" | tr -d '[:space:]')" ]; then
        ok "No stuck task records found"
    else
        warn "Stuck task records:"
        echo "$RESULT2"
    fi
}

# ─── cleanup ──────────────────────────────────────────────────────────────────
cmd_cleanup() {
    hdr "=== Cleanup: reset stuck tasks and purge queue ==="

    # Count how many will be affected
    DOC_COUNT=$($PSQL -t -c "
        SELECT COUNT(*) FROM documents
        WHERE status = 'running'
          AND updated_at < NOW() - INTERVAL '1 hour';
    " 2>/dev/null | tr -d '[:space:]')

    TASK_COUNT=$($PSQL -t -c "
        SELECT COUNT(*) FROM tasks
        WHERE status = 'running'
          AND started_at < NOW() - INTERVAL '1 hour';
    " 2>/dev/null | tr -d '[:space:]')

    warn "This will:"
    warn "  - Reset ${DOC_COUNT:-?} stuck documents → 'failed'"
    warn "  - Reset ${TASK_COUNT:-?} stuck task records → 'failed'"
    warn "  - Purge ALL messages from the Celery queue"
    warn "  - Restart the rag-worker container"
    echo ""
    read -r -p "$(echo -e "${YELLOW}Are you sure? [y/N]:${NC} ")" CONFIRM

    if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
        info "Aborted — no changes made."
        exit 0
    fi

    hdr "--- Resetting stuck documents to 'failed' ---"
    $PSQL -c "
        UPDATE documents
        SET status = 'failed',
            error  = 'Reset by maintenance script (stuck in running > 1h)',
            updated_at = NOW()
        WHERE status = 'running'
          AND updated_at < NOW() - INTERVAL '1 hour';
    " && ok "Documents reset" || err "Failed to reset documents"

    hdr "--- Resetting stuck task records to 'failed' ---"
    $PSQL -c "
        UPDATE tasks
        SET status     = 'failed',
            error      = 'Reset by maintenance script (stuck in running > 1h)',
            finished_at = NOW()
        WHERE status = 'running'
          AND started_at < NOW() - INTERVAL '1 hour';
    " 2>/dev/null && ok "Task records reset" || warn "tasks table not found — skipped"

    hdr "--- Purging Celery queue ---"
    docker exec rag-worker celery -A tasks.celery_app purge -f 2>/dev/null \
        && ok "Celery queue purged" \
        || err "Could not purge Celery queue"

    hdr "--- Restarting rag-worker ---"
    docker restart rag-worker && ok "rag-worker restarted" || err "Failed to restart rag-worker"
}

# ─── retry ────────────────────────────────────────────────────────────────────
cmd_retry() {
    local DOC_ID="$1"
    if [ -z "$DOC_ID" ]; then
        err "Usage: $0 retry <document_id>"
        exit 1
    fi

    hdr "=== Retry document ID: ${DOC_ID} ==="

    # Verify document exists
    EXISTS=$($PSQL -t -c "SELECT COUNT(*) FROM documents WHERE id = '${DOC_ID}';" 2>/dev/null | tr -d '[:space:]')
    if [ "$EXISTS" = "0" ] || [ -z "$EXISTS" ]; then
        err "Document '${DOC_ID}' not found in database"
        exit 1
    fi

    # Show current state
    info "Current document state:"
    $PSQL -c "SELECT id, status, error, updated_at FROM documents WHERE id = '${DOC_ID}';"

    # Reset to pending
    $PSQL -c "
        UPDATE documents
        SET status     = 'pending',
            error      = NULL,
            updated_at = NOW()
        WHERE id = '${DOC_ID}';
    " && ok "Document reset to 'pending'" || { err "Failed to reset document"; exit 1; }

    # Trigger reprocessing via API
    hdr "--- Triggering reprocessing via API ---"
    RESPONSE=$(docker exec rag-api curl -s -o /dev/null -w "%{http_code}" \
        -X POST "http://localhost:8000/api/documents/${DOC_ID}/reprocess" \
        -H "Content-Type: application/json" 2>/dev/null) || true

    if [ "$RESPONSE" = "200" ] || [ "$RESPONSE" = "202" ]; then
        ok "Reprocess triggered (HTTP ${RESPONSE})"
    else
        warn "API trigger returned HTTP ${RESPONSE:-unknown} — document is 'pending', worker will pick it up on next poll"
    fi
}

# ─── logs ─────────────────────────────────────────────────────────────────────
cmd_logs() {
    hdr "=== Last 50 lines: rag-api ==="
    docker logs --tail=50 rag-api 2>&1 || err "Could not get rag-api logs"

    hdr "=== Last 50 lines: rag-worker ==="
    docker logs --tail=50 rag-worker 2>&1 || err "Could not get rag-worker logs"
}

# ─── Usage ────────────────────────────────────────────────────────────────────
usage() {
    echo -e "${BOLD}RAG System Maintenance Script${NC}"
    echo ""
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo -e "  ${CYAN}status${NC}       Show document/task counts by status, active Celery tasks"
    echo -e "  ${CYAN}stuck${NC}        Find tasks stuck in 'running' for more than 1 hour"
    echo -e "  ${CYAN}cleanup${NC}      Reset stuck tasks to failed, purge queue, restart worker (asks confirmation)"
    echo -e "  ${CYAN}retry <ID>${NC}   Reset a failed document to pending and re-trigger processing"
    echo -e "  ${CYAN}logs${NC}         Show last 50 lines of rag-api and rag-worker logs"
    echo ""
    echo "Examples:"
    echo "  $0 status"
    echo "  $0 stuck"
    echo "  $0 cleanup"
    echo "  $0 retry 42"
    echo "  $0 logs"
}

# ─── Dispatch ─────────────────────────────────────────────────────────────────
case "${1:-}" in
    status)  cmd_status ;;
    stuck)   cmd_stuck ;;
    cleanup) cmd_cleanup ;;
    retry)   cmd_retry "${2:-}" ;;
    logs)    cmd_logs ;;
    *)       usage; exit 0 ;;
esac
