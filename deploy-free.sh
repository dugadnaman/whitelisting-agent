#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
echo "Karix Apparel deployment — runtime verification, not a cost guarantee"

if [ "$(uname -s)" != Linux ]; then
    echo "Run this host setup on the Linux VM. For local Docker testing, use docker compose." >&2
    exit 1
fi

# Secrets belong in the host environment/.env, never in tracked defaults.
# Compose checks all required variables without printing their values.
if ! command -v docker >/dev/null 2>&1; then
    echo "Docker Engine is missing. Install it using https://docs.docker.com/engine/install/ubuntu/ and rerun." >&2
    exit 1
fi
docker compose version >/dev/null
docker info >/dev/null
if [ -f .env ]; then
    chmod 600 .env
fi
docker compose config --quiet

# The main image owns its durable attribution and credential state.
mkdir -p data media_cache
sudo chown -R 1000:1000 data media_cache
sudo chmod 700 data

# Readiness traverses the frontend and main backend; no browser host is deployed.
docker compose up -d --build --wait --wait-timeout 300
curl --fail --silent --show-error http://127.0.0.1:3000/api/health

echo ""
echo "Container health checks passed. Attribution is NOT ready until Google and MoEngage are connected."
echo "Frontend: http://127.0.0.1:3000/apparel/attribution"
echo "Fresh database admin provisioning options: docker compose exec karix-app python -m auth --help"
echo "For private VM access: ssh -L 3000:127.0.0.1:3000 USER@VM_HOST"
echo "Connect Apparel Auth Sync in Settings > MoEngage and install the Google key in attribution Admin setup."
echo "Use an isolated verification worksheet for a real job before sharing the portal."
echo "For team access, use HTTPS ingress to frontend port 3000. Keep backend port 8000 private."
echo "Session credentials can expire; refresh Apparel Auth Sync when required."
echo "Oracle eligibility, capacity, quotas, and billing must be checked in your own account."
