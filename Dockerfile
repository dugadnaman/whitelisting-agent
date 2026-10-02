# Multi-stage Dockerfile for Karix Template Whitelisting Web Platform
# Runs FastAPI Backend on port 8000 and Next.js Frontend on port 3000

# ==========================================
# Stage 1: Build Next.js Frontend
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps
COPY frontend/ ./
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

# ==========================================
# Stage 2: Final Production Runner
# ==========================================
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app/backend:/app \
    MOENGAGE_DRAFT_TATA_CATALOG_FILE=/app/tata_catalog.json \
    MOENGAGE_DRAFT_TATA_WORKSPACE_ID=0KYUNUW5WODKX5ZFVAGPVL0U \
    MOENGAGE_DRAFT_TATA_DATA_CENTER=03 \
    MOENGAGE_DRAFT_TATA_LIVE_ENABLED=true \
    MOENGAGE_DRAFT_TATA_ZERO_CHARGE_CONFIRMED=true \
    MOENGAGE_DRAFT_TATA_NO_PUBLISH_SCOPE_CONFIRMED=true \
    MOENGAGE_DRAFT_TATA_LIVE_TEST_OPERATOR_EMAIL=dugadnaman@gmail.com,naman.dugad@attributics.com \
    MOENGAGE_DRAFT_ALLOW_SQLITE=true
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium && \
    rm -rf /var/lib/apt/lists/*
# Copy Python backend code and static assets. Runtime secrets, SQLite, and JSONL
# logs are supplied through environment variables/volumes at deployment time.
COPY backend/ ./backend/
COPY media_cache/ ./media_cache/
COPY samples/ ./samples/
COPY tests/ ./tests/
COPY tata_catalog.json* ./
COPY --from=frontend-builder /app/frontend /app/frontend

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
command=npm run start -- -p 3000 -H 0.0.0.0\n\
autostart=true\n\
autorestart=true\n\
stderr_logfile=/var/log/supervisor/nextjs.err.log\n\
stdout_logfile=/var/log/supervisor/nextjs.out.log\n\
' > /etc/supervisor/conf.d/supervisord.conf

EXPOSE 3000 8000

VOLUME ["/app/data"]

# Create and switch to non-privileged system user for container security
RUN useradd -m -u 1000 -s /bin/bash appuser && \
    mkdir -p /app/data /app/media_cache /var/log/supervisor /var/run && \
    chown -R appuser:appuser /app /var/log/supervisor /var/run

USER appuser

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
