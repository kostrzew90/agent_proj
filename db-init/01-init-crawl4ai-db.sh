#!/bin/bash
set -e

# Create database for crawl4ai
# This script runs only on first initialization
psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE crawl4ai;
EOSQL
