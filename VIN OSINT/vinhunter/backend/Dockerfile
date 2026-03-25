FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright with all system deps (handles library detection automatically)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium firefox

COPY . .

RUN mkdir -p /app/reports /app/screenshots

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8200", "--reload"]
