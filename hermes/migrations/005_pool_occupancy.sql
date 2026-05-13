-- hermes/migrations/005_pool_occupancy.sql
-- Pool occupancy monitoring table for Hermes Agent
-- Records scraping results from https://cr.nieporet.pl/ every ~30 minutes

CREATE TABLE IF NOT EXISTS hermes_pool_occupancy (
    id           SERIAL PRIMARY KEY,
    recorded_at  TIMESTAMPTZ NOT NULL,
    people_count INTEGER,
    scrape_ok    BOOLEAN NOT NULL DEFAULT TRUE,
    scrape_ms    INTEGER,
    error        TEXT
);

-- Index for time-series queries (latest readings first)
CREATE INDEX IF NOT EXISTS idx_pool_occupancy_time
    ON hermes_pool_occupancy (recorded_at DESC);

-- Deduplication strategy: application inserts with 1-minute window check
-- Query: SELECT * FROM hermes_pool_occupancy
--        WHERE recorded_at > now() - interval '1 minute'
--        ORDER BY recorded_at DESC LIMIT 1
-- If exists, skip INSERT; else proceed with upsert or insert new row
