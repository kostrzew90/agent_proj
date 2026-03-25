#!/bin/bash
# Initialize YouTube MCP tables with pgvector support
# This script handles migration for existing tables

set -e

echo "Initializing YouTube MCP tables..."

PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<EOF

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create youtube_videos table if it doesn't exist
CREATE TABLE IF NOT EXISTS youtube_videos (
    id SERIAL PRIMARY KEY,
    video_id VARCHAR(20) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    channel_name VARCHAR(255),
    channel_id VARCHAR(50),
    upload_date DATE,
    duration_seconds INTEGER,
    view_count BIGINT,
    like_count BIGINT,
    original_language VARCHAR(10),
    subtitle_language VARCHAR(10),
    tags TEXT[],
    categories TEXT[],
    thumbnail_url TEXT,
    is_live BOOLEAN DEFAULT FALSE,
    age_limit INTEGER,
    webpage_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add updated_at column if it doesn't exist
ALTER TABLE youtube_videos
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Create youtube_embeddings table if it doesn't exist
CREATE TABLE IF NOT EXISTS youtube_embeddings (
    id SERIAL PRIMARY KEY,
    video_id VARCHAR(20) NOT NULL REFERENCES youtube_videos(video_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    start_time FLOAT,
    end_time FLOAT,
    embedding vector(1024),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(video_id, chunk_index)
);

-- Create index for vector search if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_youtube_embeddings_vector
ON youtube_embeddings USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Create other useful indexes
CREATE INDEX IF NOT EXISTS idx_youtube_videos_video_id
ON youtube_videos(video_id);

CREATE INDEX IF NOT EXISTS idx_youtube_videos_upload_date
ON youtube_videos(upload_date);

CREATE INDEX IF NOT EXISTS idx_youtube_embeddings_video_id
ON youtube_embeddings(video_id);

-- Ensure constraints are in place
ALTER TABLE youtube_embeddings
DROP CONSTRAINT IF EXISTS youtube_embeddings_video_id_fkey,
ADD CONSTRAINT youtube_embeddings_video_id_fkey
    FOREIGN KEY (video_id) REFERENCES youtube_videos(video_id) ON DELETE CASCADE;

GRANT ALL PRIVILEGES ON youtube_videos TO "$POSTGRES_USER";
GRANT ALL PRIVILEGES ON youtube_embeddings TO "$POSTGRES_USER";
GRANT ALL PRIVILEGES ON youtube_videos_id_seq TO "$POSTGRES_USER";
GRANT ALL PRIVILEGES ON youtube_embeddings_id_seq TO "$POSTGRES_USER";

EOF

echo "✓ YouTube tables initialized successfully"
