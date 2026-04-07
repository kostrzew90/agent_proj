-- =============================================================
-- RAG System — Database Schema
-- Auto-executed on first container start
-- =============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================
-- Users & Auth
-- =============================================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(200),
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    frequent_topics JSONB DEFAULT '{}',
    preferred_language VARCHAR(10) DEFAULT 'auto',
    settings JSONB DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================
-- Documents
-- =============================================================

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    filename VARCHAR(500) NOT NULL,
    original_path TEXT,
    file_type VARCHAR(50) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    file_size BIGINT,
    page_count INTEGER,
    status VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'ready', 'error')),
    source_type VARCHAR(20) DEFAULT 'upload'
        CHECK (source_type IN ('upload', 'api', 'watch_folder', 'web_crawl', 'youtube', 'xpost')),
    source_url TEXT,
    metadata JSONB DEFAULT '{}',
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(file_hash);

-- =============================================================
-- Document Chunks + Embeddings
-- =============================================================

CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1024),  -- qwen3-embedding:0.6b = 1024 dimensions
    page_number INTEGER,
    section_title VARCHAR(500),
    chunk_type VARCHAR(50) DEFAULT 'text'
        CHECK (chunk_type IN ('text', 'table', 'image_ocr', 'audio_transcript', 'code')),
    token_count INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_type ON document_chunks(chunk_type);

-- HNSW index for vector similarity search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Trigram index for BM25-like keyword search
CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm ON document_chunks
    USING gin (content gin_trgm_ops);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_chunks_content_fts ON document_chunks
    USING gin (to_tsvector('simple', content));

-- =============================================================
-- Folders (hierarchical)
-- =============================================================

CREATE TABLE IF NOT EXISTS folders (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_folders_user ON folders(user_id);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);

-- =============================================================
-- Tags
-- =============================================================

CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#3B82F6',
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(name, user_id)
);

CREATE INDEX IF NOT EXISTS idx_tags_user ON tags(user_id);

-- =============================================================
-- Document <-> Folder/Tag relations
-- =============================================================

CREATE TABLE IF NOT EXISTS document_folders (
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, folder_id)
);

CREATE TABLE IF NOT EXISTS document_tags (
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);

-- =============================================================
-- Chat Sessions & Messages
-- =============================================================

CREATE TABLE IF NOT EXISTS chat_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(300),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id);

-- Chat context: which folders/tags are used in this chat
CREATE TABLE IF NOT EXISTS chat_context (
    id SERIAL PRIMARY KEY,
    chat_id INTEGER REFERENCES chat_sessions(id) ON DELETE CASCADE,
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    tag_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
    CHECK (folder_id IS NOT NULL OR tag_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_chat_context_chat ON chat_context(chat_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    chat_id INTEGER REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    sources JSONB,
    groundedness_score FLOAT,
    completeness_score FLOAT,
    relevance_score FLOAT,
    token_count INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id);

-- =============================================================
-- Processing Tasks (Celery job tracking)
-- =============================================================

CREATE TABLE IF NOT EXISTS processing_tasks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    celery_task_id VARCHAR(255),
    task_type VARCHAR(50) NOT NULL
        CHECK (task_type IN ('parse', 'chunk', 'embed', 'ocr', 'whisper', 'crawl', 'full_pipeline', 'youtube', 'web_crawl', 'xpost')),
    status VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    progress FLOAT DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_document ON processing_tasks(document_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON processing_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_celery ON processing_tasks(celery_task_id);

-- =============================================================
-- Embedding Benchmark Results
-- =============================================================

CREATE TABLE IF NOT EXISTS embedding_benchmarks (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(200) NOT NULL,
    model_dimension INTEGER,
    recall_at_5 FLOAT,
    recall_at_10 FLOAT,
    mrr FLOAT,
    ndcg_at_10 FLOAT,
    avg_latency_ms FLOAT,
    test_set_size INTEGER,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================
-- Seed: default admin user (password: admin — CHANGE IN PRODUCTION)
-- bcrypt hash of 'admin'
-- =============================================================

INSERT INTO users (username, password_hash, display_name, is_admin)
VALUES ('admin', '$2b$12$9JqBT2dzOMODvSMFprVmcu9WS3JmJMWzKnRcOMThbbFskikzzUeIa', 'Administrator', TRUE)
ON CONFLICT (username) DO NOTHING;
