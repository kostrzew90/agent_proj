#!/bin/bash
# RAG System — PostgreSQL Backup Script
# Runs pg_dump inside rag-postgres container, saves to host, rotates old backups.
#
# Usage:
#   ./scripts/backup.sh              # manual run
#   Add to crontab: 0 3 * * * cd /path/to/RAG && ./scripts/backup.sh >> logs/backup.log 2>&1

set -euo pipefail

# Config (override via env vars)
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
CONTAINER="${RAG_DB_CONTAINER:-rag-postgres}"
DB_NAME="${RAG_DB_NAME:-rag}"
DB_USER="${RAG_DB_USER:-rag}"

# Timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="rag_backup_${TIMESTAMP}.sql.gz"

# Ensure backup dir exists
mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting backup of database '$DB_NAME'..."

# pg_dump inside container, gzip on host
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl | gzip > "$BACKUP_DIR/$BACKUP_FILE"

# Check size
SIZE=$(du -h "$BACKUP_DIR/$BACKUP_FILE" | cut -f1)
echo "[$(date)] Backup saved: $BACKUP_DIR/$BACKUP_FILE ($SIZE)"

# Rotate old backups
DELETED=$(find "$BACKUP_DIR" -name "rag_backup_*.sql.gz" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
echo "[$(date)] Rotated $DELETED backup(s) older than $RETENTION_DAYS days."

echo "[$(date)] Backup complete."
