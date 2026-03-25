#!/bin/bash
set -e

# Create tables for YouTube embeddings
psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Enable pgvector extension
    CREATE EXTENSION IF NOT EXISTS vector;

    -- Tabela metadanych video (1 rekord per video)
    CREATE TABLE IF NOT EXISTS youtube_videos (
        video_id VARCHAR(20) PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        channel_name TEXT,
        channel_id VARCHAR(30),
        upload_date DATE,
        duration_seconds INT,
        view_count BIGINT,
        like_count BIGINT,
        original_language VARCHAR(10),
        subtitle_language VARCHAR(10),
        tags TEXT[],
        categories TEXT[],
        thumbnail_url TEXT,
        is_live BOOLEAN DEFAULT FALSE,
        age_limit INT,
        webpage_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Tabela embeddingów (wiele chunków per video)
    CREATE TABLE IF NOT EXISTS youtube_embeddings (
        id SERIAL PRIMARY KEY,
        video_id VARCHAR(20) NOT NULL REFERENCES youtube_videos(video_id) ON DELETE CASCADE,
        chunk_index INT NOT NULL,
        chunk_text TEXT NOT NULL,
        start_time FLOAT,
        end_time FLOAT,
        embedding vector(1024),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(video_id, chunk_index)
    );

    -- Indeksy
    CREATE INDEX IF NOT EXISTS idx_embeddings_vector ON youtube_embeddings USING ivfflat (embedding vector_cosine_ops);
    CREATE INDEX IF NOT EXISTS idx_videos_upload_date ON youtube_videos (upload_date);
    CREATE INDEX IF NOT EXISTS idx_videos_channel ON youtube_videos (channel_name);
    CREATE INDEX IF NOT EXISTS idx_videos_tags ON youtube_videos USING GIN (tags);
EOSQL

echo "YouTube embeddings tables created successfully"
