-- hermes/migrations/006_autocentrum.sql
-- Autocentrum.pl knowledge base — car model reviews + owner opinions
-- Idempotent (CREATE ... IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS autocentrum_models (
    id          SERIAL PRIMARY KEY,
    make        VARCHAR(100) NOT NULL,
    model       VARCHAR(100) NOT NULL,
    year_from   INTEGER,
    year_to     INTEGER,
    engine      VARCHAR(100),
    fuel        VARCHAR(50),
    url         TEXT UNIQUE NOT NULL,
    scraped_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS autocentrum_reviews (
    id          SERIAL PRIMARY KEY,
    model_id    INTEGER NOT NULL REFERENCES autocentrum_models(id) ON DELETE CASCADE,
    source      VARCHAR(20) NOT NULL CHECK (source IN ('editorial', 'owner')),
    title       TEXT,
    content     TEXT NOT NULL,
    rating      NUMERIC(3,1),
    review_date DATE,
    url         TEXT,
    embedding   vector(1024),
    scraped_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS autocentrum_reviews_embedding_idx
    ON autocentrum_reviews USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS autocentrum_models_lookup_idx
    ON autocentrum_models (LOWER(make), LOWER(model), year_from, year_to);

-- Grant to existing hermes_ro user (read for VINhunter plugin)
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_ro') THEN
        GRANT SELECT ON autocentrum_models TO hermes_ro;
        GRANT SELECT ON autocentrum_reviews TO hermes_ro;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_ingest') THEN
        GRANT SELECT, INSERT, UPDATE ON autocentrum_models TO hermes_ingest;
        GRANT SELECT, INSERT, UPDATE ON autocentrum_reviews TO hermes_ingest;
        GRANT USAGE, SELECT ON SEQUENCE autocentrum_models_id_seq TO hermes_ingest;
        GRANT USAGE, SELECT ON SEQUENCE autocentrum_reviews_id_seq TO hermes_ingest;
    END IF;
END $$;
