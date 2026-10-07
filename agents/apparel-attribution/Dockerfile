FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORAGE_DIR=/data \
    PORT=8000
WORKDIR /app
# Playwright's bundled Node transport connects to remote CDP; no local browser install.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*


# Build from the repository root; never copy the frontend, keys, or customer data.
COPY agents/apparel-attribution/Backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY agents/apparel-attribution/Backend/app /app/app
COPY agents/apparel-attribution/start-worker /usr/local/bin/start-worker
RUN chmod 0755 /usr/local/bin/start-worker && mkdir -p /data && chmod 0700 /data

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz', timeout=4).close()"

# One process and one deployment replica share a persistent browser/job lock.
CMD ["/usr/local/bin/start-worker"]
