CREATE TABLE IF NOT EXISTS llm_calls (
    id               BIGSERIAL PRIMARY KEY,
    ts               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    project          TEXT         NOT NULL,
    service          TEXT         NOT NULL,
    environment      TEXT         NOT NULL,
    host             TEXT         NOT NULL,
    provider         TEXT         NOT NULL,
    model            TEXT         NOT NULL,
    call_type        TEXT         NOT NULL,
    tokens_in        INTEGER      NOT NULL DEFAULT 0,
    tokens_out       INTEGER      NOT NULL DEFAULT 0,
    tokens_estimated BOOLEAN      NOT NULL DEFAULT FALSE,
    cost_usd         NUMERIC(12,6),
    latency_ms       INTEGER,
    ok               BOOLEAN      NOT NULL,
    error            TEXT,
    trace_id         TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_ts         ON llm_calls (ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_project_ts ON llm_calls (project, ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model_ts   ON llm_calls (model, ts DESC);

CREATE TABLE IF NOT EXISTS model_pricing (
    id               SERIAL PRIMARY KEY,
    provider         TEXT NOT NULL,
    model            TEXT NOT NULL,
    usd_per_mtok_in  NUMERIC(10,4) NOT NULL,
    usd_per_mtok_out NUMERIC(10,4) NOT NULL,
    valid_from       TIMESTAMPTZ   NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    UNIQUE (provider, model, valid_from)
);

CREATE OR REPLACE VIEW v_llm_calls_costed AS
SELECT
    c.*,
    COALESCE(
        c.cost_usd,
        p.usd_per_mtok_in  * c.tokens_in  / 1e6
      + p.usd_per_mtok_out * c.tokens_out / 1e6
    )                                        AS effective_cost_usd,
    (c.cost_usd IS NULL AND p.id IS NULL)    AS pricing_missing
FROM llm_calls c
LEFT JOIN LATERAL (
    SELECT mp.id, mp.usd_per_mtok_in, mp.usd_per_mtok_out
    FROM model_pricing mp
    WHERE mp.provider = c.provider
      AND mp.model = c.model
      AND mp.valid_from <= c.ts
    ORDER BY mp.valid_from DESC
    LIMIT 1
) p ON TRUE;
