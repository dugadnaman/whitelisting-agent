#!/bin/bash
set -euo pipefail

echo "========================================================"
echo " Karix Apparel Attribution - 100% Free 24/7 Deployment "
echo "========================================================"

# 1. Install Docker & Compose if missing
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER" || true
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# 2. Ensure directories exist
mkdir -p agents/apparel-attribution/data
mkdir -p agents/apparel-attribution/browser-profile
mkdir -p data
mkdir -p media_cache
chmod 700 agents/apparel-attribution/data agents/apparel-attribution/browser-profile || true

# 3. Build & start all 3 containers
echo "Building and launching all containers..."
docker compose up -d --build

# 4. Display URLs and instructions
SERVER_IP=$(curl -s https://ifconfig.me || echo "YOUR_SERVER_IP")

echo ""
echo "========================================================"
echo " DEPLOYMENT SUCCESSFUL!"
echo "========================================================"
echo ""
echo "1. Web App (Share this with your 20 users):"
echo "   http://${SERVER_IP}:3000/apparel/attribution"
echo ""
echo "2. Protected Browser Desktop (One-time Admin MoEngage Login):"
echo "   http://${SERVER_IP}:3001"
echo "   Username: operator-admin"
echo "   Password: KarixApparelSecureAuth2026!7xV4mQ8zA1"
echo ""
echo "   -> Open this URL, log in to MoEngage via Google SSO & MFA."
echo "   -> Once logged in, close the tab. The session stays active 24/7!"
echo ""
echo "3. Free HTTPS (Optional - Instant Cloudflare Tunnel):"
echo "   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared"
echo "   chmod +x /usr/local/bin/cloudflared"
echo "   cloudflared tunnel --url http://localhost:3000"
echo "========================================================"
