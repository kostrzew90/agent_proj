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

-- _handle_pool_monitor() always inserts bucketed timestamps (00/30 min) — ON CONFLICT DO NOTHING handles retries
-- Ochrona przed duplikatami przy restarcie/retry
-- recorded_at is always bucketed to exact 00/30-min boundaries by _pool_bucket_ts()
CREATE UNIQUE INDEX IF NOT EXISTS uq_pool_occupancy_bucket
    ON hermes_pool_occupancy (recorded_at);

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------
GRANT SELECT ON hermes_pool_occupancy TO hermes_ro;
GRANT INSERT ON hermes_pool_occupancy TO hermes_ingest;
GRANT USAGE, SELECT ON SEQUENCE hermes_pool_occupancy_id_seq TO hermes_ingest;
