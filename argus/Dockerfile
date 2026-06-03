FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
COPY argus ./argus
COPY config ./config
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "argus.main"]
