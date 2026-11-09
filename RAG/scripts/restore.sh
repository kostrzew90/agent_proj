#!/bin/bash
# RAG System — PostgreSQL Restore Script
# Usage: ./scripts/restore.sh backups/rag_backup_20260401_030000.sql.gz

set -euo pipefail

BACKUP_FILE="${1:?Usage: $0 <backup_file.sql.gz>}"
CONTAINER="${RAG_DB_CONTAINER:-rag-postgres}"
DB_NAME="${RAG_DB_NAME:-rag}"
DB_USER="${RAG_DB_USER:-rag}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: File not found: $BACKUP_FILE"
    exit 1
fi

echo "[$(date)] Restoring '$DB_NAME' from $BACKUP_FILE..."
echo "WARNING: This will DROP and recreate the database. Press Ctrl+C to abort (5s)..."
sleep 5

# Drop connections and recreate DB
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -c "
    SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();
    DROP DATABASE IF EXISTS $DB_NAME;
    CREATE DATABASE $DB_NAME OWNER $DB_USER;
"

# Restore
gunzip -c "$BACKUP_FILE" | docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" --quiet

echo "[$(date)] Restore complete."
