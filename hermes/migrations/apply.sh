#!/usr/bin/env bash
# =============================================================================
# apply.sh — Hermes schema migration runner
# Użycie: source ../.env && bash apply.sh
#         lub: PG_RAG_DSN="postgresql://rag:pass@host:5434/rag" bash apply.sh
# =============================================================================
set -euo pipefail

: "${PG_RAG_DSN:?Brakuje zmiennej środowiskowej PG_RAG_DSN. Uruchom: source ../.env}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/3] Aplikuję 001_hermes_tabs.sql ..."
psql "$PG_RAG_DSN" -v ON_ERROR_STOP=1 -f "$DIR/001_hermes_tabs.sql"
echo "    OK"

echo "==> [2/3] Aplikuję 002_domain_weights_seed.sql ..."
psql "$PG_RAG_DSN" -v ON_ERROR_STOP=1 -f "$DIR/002_domain_weights_seed.sql"
echo "    OK"

echo "==> [3/3] Aplikuję create-ro-users.sql ..."
psql "$PG_RAG_DSN" -v ON_ERROR_STOP=1 -f "$DIR/create-ro-users.sql"
echo "    OK"

echo "==> [4/4] Aplikuję 006_autocentrum.sql ..."
psql "$PG_RAG_DSN" -v ON_ERROR_STOP=1 -f "$DIR/006_autocentrum.sql"
echo "    OK"

echo ""
echo "OK — schema Hermesa zastosowana pomyślnie."
echo ""
echo "Weryfikacja tabel:"
psql "$PG_RAG_DSN" -c "\dt hermes_*"
