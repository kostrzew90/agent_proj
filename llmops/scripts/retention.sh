#!/usr/bin/env bash
# Kasuje wiersze starsze niz LLMOPS_RETENTION_DAYS (domyslnie 90).
set -euo pipefail
DAYS="${LLMOPS_RETENTION_DAYS:-90}"
docker exec llmops-postgres psql -U "${LLMOPS_DB_USER:-llmops}" -d "${LLMOPS_DB_NAME:-llmops}" \
  -c "DELETE FROM llm_calls WHERE ts < now() - interval '${DAYS} days'"
