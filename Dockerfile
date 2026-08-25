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

# Install Node.js runtime for Next.js and process supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Copy Python backend code, data, initial logs, and credentials
COPY *.py ./
COPY *.csv ./
COPY *.png ./
COPY *.jsonl ./
COPY *.json ./
COPY default_sample_header.* ./
COPY media_cache/ ./media_cache/
COPY samples/ ./samples/
COPY tests/ ./tests/
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
command=python3 -m uvicorn api:app --host 0.0.0.0 --port 8000\n\
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

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
