#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
cd "$ROOT"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "Docker Compose not found. Install compose-plugin or docker-compose."
    echo "- Ubuntu/Debian: sudo apt-get install docker-compose-plugin"
    echo "- Or: https://docs.docker.com/compose/install/"
    exit 1
  fi
}

echo "[dev] Stopping any existing local pgvector..."
compose -f compose.local.yml down || true
echo "[dev] Starting local pgvector (port 5432)..."
compose -f compose.local.yml up -d
echo "[dev] Services:"
compose -f compose.local.yml ps

echo "[dev] Connection string: postgres://iclr:iclrpass@127.0.0.1:5432/iclr2026"
