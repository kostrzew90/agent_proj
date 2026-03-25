FROM python:3.12-slim

WORKDIR /app

# Install yt-dlp and ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir yt-dlp

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY server.py .
COPY http_server.py .

# Environment defaults
ENV HOST=0.0.0.0
ENV PORT=8765
ENV YT_DB_HOST=postgres
ENV YT_DB_PORT=5432
ENV YT_DB_USER=n8n
ENV YT_DB_PASSWORD=n8npass
ENV YT_DB_NAME=n8n
ENV OLLAMA_URL=http://host.docker.internal:11434
ENV EMBEDDING_MODEL=qwen3-embedding:0.6b

EXPOSE 8765

CMD ["python", "http_server.py"]
