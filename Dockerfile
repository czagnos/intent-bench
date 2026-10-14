FROM node:22-slim AS web
WORKDIR /build
COPY apps/web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/api INTENT_DATA_DIR=/app/data/private
COPY requirements.lock ./
COPY LICENSE ./
RUN pip install --no-cache-dir -r requirements.lock
COPY apps/api apps/api
COPY data/demo data/demo
COPY data/model-presets.json data/model-presets.json
COPY data/retrieval-profiles.json data/retrieval-profiles.json
COPY data/reranker-comparison-profiles.json data/reranker-comparison-profiles.json
COPY scripts scripts
COPY --from=web /build/dist apps/web/dist
RUN useradd --create-home studio && mkdir -p /app/data/private \
    && ln -s /app/data/private /app/artifacts \
    && chown -R studio:studio /app/data
USER studio
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
