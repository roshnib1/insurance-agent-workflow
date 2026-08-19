# Commercial Property Underwriting Workflow (Google ADK LlmAgent + tools) — backend
#
# Build:  docker build -t workflow-backend .
# Run:    docker run -p 8002:8000 --env-file .env -v workflow_output:/app/output workflow-backend
#
# output/ holds every generated decision.json, audit trail, and email draft — mount it
# as a volume or every run's artifacts vanish when the container is removed.

FROM python:3.12-slim

# pdfplumber (proposal/report parsing) needs these to render/parse PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p output/emails data/uploads logs

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]