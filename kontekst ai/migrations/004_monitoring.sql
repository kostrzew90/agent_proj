-- 004_monitoring.sql — Indexing jobs, LLM call tracking, retrieval log extensions

CREATE TABLE IF NOT EXISTS indexing_jobs (
    id SERIAL PRIMARY KEY,
    repo_id TEXT NOT NULL DEFAULT 'default',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    files_scanned INTEGER DEFAULT 0,
    files_indexed INTEGER DEFAULT 0,
    files_skipped INTEGER DEFAULT 0,
    files_errored INTEGER DEFAULT 0,
    chunks_created INTEGER DEFAULT 0,
    symbols_found INTEGER DEFAULT 0,
    duration_ms REAL,
    status TEXT NOT NULL DEFAULT 'running'  -- running | completed | failed
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT,           -- 'query', 'explain', 'memory_bootstrap', etc.
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms REAL,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT
);

CREATE INDEX idx_llm_calls_ts ON llm_calls(ts);
CREATE INDEX idx_llm_calls_provider ON llm_calls(provider);

-- Extend retrieval_logs with counts and embedding latency
ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS semantic_count INTEGER;
ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS keyword_count INTEGER;
ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS final_count INTEGER;
ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS embedding_ms REAL;
