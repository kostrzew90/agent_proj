#!/usr/bin/env python3
"""
YouTube MCP Server
Exposes youtube-embeddings and youtube-search as MCP tools.
"""

import sys
import json
import subprocess
import tempfile
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import psycopg2
from psycopg2.extras import execute_values

# =============================================================================
# Configuration
# =============================================================================

DB_CONFIG = {
    'host': os.getenv('YT_DB_HOST', 'postgres'),
    'port': int(os.getenv('YT_DB_PORT', '5432')),
    'user': os.getenv('YT_DB_USER', 'n8n'),
    'password': os.getenv('YT_DB_PASSWORD', 'n8npass'),
    'dbname': os.getenv('YT_DB_NAME', 'n8n')
}

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://host.docker.internal:11434')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'qwen3-embedding:0.6b')
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '500'))
CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', '50'))

# =============================================================================
# YouTube Functions
# =============================================================================

def get_video_info(url: str) -> dict:
    """Fetch video metadata via yt-dlp."""
    result = subprocess.run(
        ['yt-dlp', '--dump-json', '--no-download', url],
        capture_output=True,
        text=True,
        encoding='utf-8'
    )
    if result.returncode != 0:
        raise Exception(f"yt-dlp error: {result.stderr}")
    return json.loads(result.stdout)


def parse_timestamp(ts: str) -> float:
    """Convert VTT timestamp to seconds."""
    parts = ts.replace(',', '.').split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_vtt(vtt_path: Path) -> list[dict]:
    """Parse VTT file and return segments with timestamps."""
    content = vtt_path.read_text(encoding='utf-8')
    segments = []
    time_pattern = re.compile(r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})')

    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        match = time_pattern.match(line)

        if match:
            start = parse_timestamp(match.group(1))
            end = parse_timestamp(match.group(2))

            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                text = re.sub(r'<[^>]+>', '', lines[i])
                text = re.sub(r'\{[^}]+\}', '', text)
                text_lines.append(text.strip())
                i += 1

            text = ' '.join(text_lines)
            if text:
                segments.append({'start': start, 'end': end, 'text': text})
        i += 1

    # Deduplicate
    seen = set()
    unique_segments = []
    for seg in segments:
        if seg['text'] not in seen:
            seen.add(seg['text'])
            unique_segments.append(seg)

    return unique_segments


def get_transcript(url: str, temp_dir: str) -> tuple[str, str, list]:
    """Download transcript from YouTube."""
    subprocess.run(
        ['yt-dlp',
         '--write-auto-sub',
         '--write-sub',
         '--sub-lang', 'pl,en',
         '--sub-format', 'vtt',
         '--skip-download',
         '-o', os.path.join(temp_dir, '%(id)s.%(ext)s'),
         url],
        capture_output=True,
        text=True,
        encoding='utf-8'
    )

    vtt_files = list(Path(temp_dir).glob('*.vtt'))
    if not vtt_files:
        raise Exception("No subtitles available for this video")

    vtt_file = vtt_files[0]
    lang = 'unknown'

    if '.pl.' in vtt_file.name:
        lang = 'pl'
    elif '.en.' in vtt_file.name:
        lang = 'en'
    elif 'auto' in vtt_file.name.lower():
        lang = 'auto'

    segments = parse_vtt(vtt_file)
    full_text = ' '.join(seg['text'] for seg in segments)

    return full_text, lang, segments


def chunk_text(segments: list[dict]) -> list[dict]:
    """Split text into chunks while preserving timestamps."""
    if not segments:
        return []

    chunks = []
    current_chunk = []
    current_len = 0
    chunk_start = segments[0]['start']

    for seg in segments:
        seg_len = len(seg['text'])

        if current_len + seg_len > CHUNK_SIZE and current_chunk:
            chunks.append({
                'text': ' '.join(s['text'] for s in current_chunk),
                'start': chunk_start,
                'end': current_chunk[-1]['end'],
                'index': len(chunks)
            })

            overlap_len = 0
            overlap_segs = []
            for s in reversed(current_chunk):
                if overlap_len + len(s['text']) > CHUNK_OVERLAP:
                    break
                overlap_segs.insert(0, s)
                overlap_len += len(s['text'])

            current_chunk = overlap_segs
            current_len = overlap_len
            chunk_start = current_chunk[0]['start'] if current_chunk else seg['start']

        current_chunk.append(seg)
        current_len += seg_len

    if current_chunk:
        chunks.append({
            'text': ' '.join(s['text'] for s in current_chunk),
            'start': chunk_start,
            'end': current_chunk[-1]['end'],
            'index': len(chunks)
        })

    return chunks


def get_embedding(text: str) -> list[float]:
    """Generate embedding via Ollama."""
    response = requests.post(
        f'{OLLAMA_URL}/api/embed',
        json={'model': EMBEDDING_MODEL, 'input': text},
        timeout=120
    )
    response.raise_for_status()
    return response.json()['embeddings'][0]


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts."""
    return [get_embedding(text) for text in texts]


def parse_upload_date(date_str: str) -> str | None:
    """Convert YYYYMMDD to YYYY-MM-DD."""
    if not date_str or len(date_str) != 8:
        return None
    try:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    except:
        return None


def ensure_tables_exist():
    """Create tables if they don't exist."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    try:
        # Enable pgvector
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        # Create youtube_videos table
        cur.execute("""
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
            )
        """)

        # Create youtube_embeddings table
        cur.execute("""
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
            )
        """)

        # Create index for vector search
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_youtube_embeddings_vector
            ON youtube_embeddings USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)

        conn.commit()
        print("Tables ensured")
    except Exception as e:
        print(f"Warning: Could not create tables: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def save_to_db(info: dict, chunks: list[dict], embeddings: list[list[float]], subtitle_lang: str):
    """Save video and embeddings to PostgreSQL."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO youtube_videos (
                video_id, title, description, channel_name, channel_id,
                upload_date, duration_seconds, view_count, like_count,
                original_language, subtitle_language, tags, categories,
                thumbnail_url, is_live, age_limit, webpage_url
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (video_id) DO UPDATE SET
                title = EXCLUDED.title,
                view_count = EXCLUDED.view_count,
                like_count = EXCLUDED.like_count,
                updated_at = CURRENT_TIMESTAMP
        """, (
            info['id'],
            info['title'],
            info.get('description'),
            info.get('channel') or info.get('uploader'),
            info.get('channel_id'),
            parse_upload_date(info.get('upload_date')),
            info.get('duration'),
            info.get('view_count'),
            info.get('like_count'),
            info.get('language'),
            subtitle_lang,
            info.get('tags', []),
            info.get('categories', []),
            info.get('thumbnail'),
            info.get('is_live', False),
            info.get('age_limit'),
            info.get('webpage_url')
        ))

        cur.execute("DELETE FROM youtube_embeddings WHERE video_id = %s", (info['id'],))

        data = [
            (info['id'], chunk['index'], chunk['text'], chunk['start'], chunk['end'], embedding)
            for chunk, embedding in zip(chunks, embeddings)
        ]

        execute_values(
            cur,
            """INSERT INTO youtube_embeddings
               (video_id, chunk_index, chunk_text, start_time, end_time, embedding)
               VALUES %s""",
            data,
            template="(%s, %s, %s, %s, %s, %s::vector)"
        )

        conn.commit()
    finally:
        cur.close()
        conn.close()


def youtube_embed(url: str) -> dict:
    """Main function to process YouTube video."""
    ensure_tables_exist()

    info = get_video_info(url)

    with tempfile.TemporaryDirectory() as temp_dir:
        full_text, lang, segments = get_transcript(url, temp_dir)

    chunks = chunk_text(segments)
    texts = [c['text'] for c in chunks]
    embeddings = get_embeddings(texts)

    save_to_db(info, chunks, embeddings, lang)

    return {
        'video_id': info['id'],
        'title': info['title'],
        'channel': info.get('channel') or info.get('uploader'),
        'upload_date': parse_upload_date(info.get('upload_date')),
        'chunks_count': len(chunks),
        'subtitle_language': lang
    }


def youtube_search(query: str, year: int = None, title_filter: str = None, limit: int = 8) -> list[dict]:
    """Semantic search in YouTube transcripts."""
    embedding = get_embedding(query)

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    sql = """
        SELECT
            v.title,
            v.channel_name,
            v.upload_date,
            e.chunk_text,
            e.start_time,
            1 - (e.embedding <=> %s::vector) as similarity
        FROM youtube_embeddings e
        JOIN youtube_videos v ON e.video_id = v.video_id
        WHERE 1=1
    """
    params = [embedding]

    if year:
        sql += " AND EXTRACT(YEAR FROM v.upload_date) = %s"
        params.append(year)

    if title_filter:
        sql += " AND LOWER(v.title) LIKE LOWER(%s)"
        params.append(f"%{title_filter}%")

    sql += """
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
    """
    params.extend([embedding, limit])

    cur.execute(sql, params)
    results = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            'title': r[0],
            'channel': r[1],
            'date': str(r[2]) if r[2] else None,
            'text': r[3],
            'timestamp': f"{int(r[4]//60)}:{int(r[4]%60):02d}" if r[4] else None,
            'similarity': round(r[5] * 100, 1)
        }
        for r in results
    ]


def youtube_list() -> list[dict]:
    """List all indexed YouTube videos."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute("""
        SELECT v.video_id, v.title, v.channel_name, v.upload_date,
               COUNT(e.id) as chunks
        FROM youtube_videos v
        LEFT JOIN youtube_embeddings e ON v.video_id = e.video_id
        GROUP BY v.video_id, v.title, v.channel_name, v.upload_date
        ORDER BY v.upload_date DESC
    """)

    results = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            'video_id': r[0],
            'title': r[1],
            'channel': r[2],
            'date': str(r[3]) if r[3] else None,
            'chunks': r[4]
        }
        for r in results
    ]
