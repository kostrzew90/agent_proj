FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY hermes_bridge.py mcp_client.py llm_client.py memory.py /app/
CMD ["python", "-u", "hermes_bridge.py"]
