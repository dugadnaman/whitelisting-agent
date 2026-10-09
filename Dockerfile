# Multi-stage Dockerfile for Karix Template Whitelisting Web Platform
# Runs FastAPI Backend on port 8000 and Next.js Frontend on port 3000

# ==========================================
# Stage 1: Build Next.js Frontend
# ==========================================
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

# ==========================================
# Stage 2: Final Production Runner
# ==========================================
FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONPATH=/app/backend:/app \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    NODE_ENV=production \
    BACKEND_INTERNAL_URL=http://127.0.0.1:8000 \
    KARIX_DB_PATH=/app/data/karix_store.db \
    MOENGAGE_DRAFT_TATA_CATALOG_FILE=/app/tata_catalog.json
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libstdc++6 \
    libatomic1 \
    supervisor \
    && rm -rf /var/lib/apt/lists/*
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node

# Install Python backend dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    mkdir -p /ms-playwright && \
    playwright install --with-deps chromium && \
    chmod -R 777 /ms-playwright && \
    rm -rf /var/lib/apt/lists/*
# Copy Python backend code and static assets. Runtime secrets, SQLite, and JSONL
# logs are supplied through environment variables/volumes at deployment time.
COPY backend/ ./backend/
COPY media_cache/ ./media_cache/
COPY samples/ ./samples/
COPY tests/ ./tests/
COPY tata_catalog.json* ./
COPY --from=frontend-builder /app/frontend /app/frontend
COPY docker-entrypoint.py /app/docker-entrypoint.py

# Setup supervisord configuration to run both FastAPI (8000) and Next.js (3000)
RUN mkdir -p /var/log/supervisor /etc/supervisor/conf.d
RUN echo '[supervisord]\n\
nodaemon=true\n\
logfile=/var/log/supervisor/supervisord.log\n\
pidfile=/var/run/supervisord.pid\n\
\n\
[program:fastapi]\n\
directory=/app\n\
command=python3 -m uvicorn api:app --app-dir /app/backend --host 0.0.0.0 --port 8000\n\
autostart=true\n\
autorestart=true\n\
stderr_logfile=/var/log/supervisor/fastapi.err.log\n\
stdout_logfile=/var/log/supervisor/fastapi.out.log\n\
\n\
[program:nextjs]\n\
directory=/app/frontend\n\
command=/usr/local/bin/node node_modules/next/dist/bin/next start -p 3000 -H 0.0.0.0\n\
autostart=true\n\
autorestart=true\n\
stderr_logfile=/var/log/supervisor/nextjs.err.log\n\
stdout_logfile=/var/log/supervisor/nextjs.out.log\n\
' > /etc/supervisor/conf.d/supervisord.conf

EXPOSE 3000 8000

# The frontend proxy must reach the backend before this image is ready.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:3000/api/health || exit 1

VOLUME ["/app/data"]

# Create and switch to non-privileged system user for container security
RUN useradd -m -u 1000 -s /bin/bash appuser && \
    mkdir -p /app/data /app/media_cache /var/log/supervisor /var/run && \
    chown -R appuser:appuser /app /var/log/supervisor /var/run

USER appuser

ENTRYPOINT ["python3", "/app/docker-entrypoint.py"]

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
