#!/usr/bin/env bash
# Build and launch the tattoo-feed HTTP server + ngrok TLS tunnel.
#
# Prerequisites:
#   1. Docker and docker compose installed.
#   2. Copy .env.example to .env and fill in every value.
#
# Usage:
#   cp .env.example .env          # edit with real credentials
#   ./scripts/run-server.sh       # builds image, starts stack
#
# After startup:
#   - ngrok inspector at http://localhost:4040 shows the public URL.
#   - Use that URL as the ChatGPT connector URL (Auth = OAuth).
#   - The public URL must also be set as MCP_AUTH_AUDIENCE in .env and
#     configured as the audience/resource in your IdP before starting.
#
# To use a stable ngrok domain (recommended — prevents connector URL churn):
#   1. Reserve a domain at https://dashboard.ngrok.com/domains
#   2. Set NGROK_DOMAIN in .env
#   3. Add --domain=${NGROK_DOMAIN} to the ngrok command in docker-compose.yml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ ! -f "$REPO_ROOT/.env" ]]; then
    echo "Error: .env not found."
    echo "Run:  cp .env.example .env   # then fill in your credentials"
    exit 1
fi

cd "$REPO_ROOT"

echo "Building the server image and starting the stack (server + ngrok)..."
docker compose up --build "$@"
