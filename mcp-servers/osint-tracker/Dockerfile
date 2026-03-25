FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Phoneinfoga (Go binary)
RUN curl -sSL https://raw.githubusercontent.com/sundowndev/phoneinfoga/master/support/scripts/install | bash \
    && mv ./phoneinfoga /usr/local/bin/

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py ./
COPY scripts/ ./scripts/

# Environment defaults
ENV HOST=0.0.0.0
ENV PORT=8766
ENV OSINT_DB_HOST=postgres
ENV OSINT_DB_PORT=5432
ENV OSINT_DB_USER=n8n
ENV OSINT_DB_PASSWORD=n8npass
ENV OSINT_DB_NAME=n8n

EXPOSE 8766

CMD ["python", "http_server.py"]
