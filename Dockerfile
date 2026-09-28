# ---- web UI -------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx tsc -b && npx vite build --outDir /web/dist --emptyOutDir

# ---- API + agent ----------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ .
COPY --from=web /web/dist ./app/static
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN useradd -m maverick && mkdir -p /data && chown maverick /data && chmod +x /usr/local/bin/entrypoint.sh
# Starts as root only to fix volume ownership; the entrypoint then drops to `maverick`.
EXPOSE 8000
HEALTHCHECK CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/api/health')" || exit 1
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# $PORT is injected by Railway/Render/Fly; the proxy headers make URLs/https correct behind their edge.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75"]
