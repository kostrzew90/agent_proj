CREATE TABLE project_memory (
    id SERIAL PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    tags TEXT[] DEFAULT '{}',
    source TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE retrieval_logs (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    topk INTEGER DEFAULT 10,
    latency_ms REAL,
    provider_used TEXT DEFAULT 'ollama',
    context_tokens INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE log_events (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    service TEXT,
    level TEXT,
    error_signature TEXT,
    trace_id TEXT,
    message TEXT,
    meta_json JSONB DEFAULT '{}'
);

CREATE INDEX idx_log_events_ts ON log_events(ts);
CREATE INDEX idx_log_events_service ON log_events(service);
CREATE INDEX idx_log_events_signature ON log_events(error_signature);
CREATE INDEX idx_memory_tags ON project_memory USING gin(tags);
CREATE INDEX idx_retrieval_logs_ts ON retrieval_logs(created_at);
