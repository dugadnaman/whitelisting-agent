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

# The main image runs as UID/GID 1000. Preserve files and make its bind mounts
# writable; the browser uses the same persisted host ownership.
mkdir -p data media_cache agents/apparel-attribution/data agents/apparel-attribution/browser-profile
sudo chown -R 1000:1000 data media_cache agents/apparel-attribution/browser-profile
chmod 700 agents/apparel-attribution/data
sudo chmod 700 data agents/apparel-attribution/browser-profile

# --wait requires the real frontend/backend and browser CDP health probes.
docker compose up -d --build --wait --wait-timeout 300
curl --fail --silent --show-error http://127.0.0.1:3000/api/health

echo ""
echo "Container health checks passed. Attribution is NOT ready until Google and MoEngage are connected."
echo "Frontend: http://127.0.0.1:3000/apparel/attribution"
echo "Admin desktop: https://localhost:3001 (self-signed certificate)"
echo "Fresh database admin provisioning options: docker compose exec karix-app python -m auth --help"
echo "From your laptop, forward these loopback-only ports:"
echo "  ssh -L 3000:127.0.0.1:3000 -L 3001:127.0.0.1:3001 USER@VM_HOST"
echo "Sign in to the desktop with APPAREL_BROWSER_USER / APPAREL_BROWSER_PASSWORD from your private .env."
echo "Finish MoEngage sign-in/MFA there, upload the Google key through Admin setup, then refresh status."
echo "Use an isolated verification worksheet for a real job before sharing the portal."
echo "For team access, put an authenticated HTTPS ingress in front of frontend port 3000; keep the admin desktop SSH/VPN-only."
echo "Do not expose ports 8000, 9222, or 9223. Login sessions may expire; human reauthentication remains required."
echo "Oracle eligibility, capacity, quotas, and billing must be checked in your own account."
