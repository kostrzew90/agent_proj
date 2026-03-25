CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'python',
    hash TEXT NOT NULL,
    mtime DOUBLE PRECISION NOT NULL,
    repo_id TEXT NOT NULL DEFAULT 'default',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(path, repo_id)
);

CREATE TABLE chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    tokens INTEGER,
    embedding vector(768),
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX idx_chunks_content_fts ON chunks
    USING gin (to_tsvector('simple', content));
CREATE INDEX idx_documents_path ON documents(path);
CREATE INDEX idx_documents_repo ON documents(repo_id);
