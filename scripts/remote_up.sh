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
echo "[remote] Stopping any existing remote pgvector+uvapp..."
compose -f compose.remote.yml down || true
echo "[remote] Building uv image and starting pgvector+uvapp..."
compose -f compose.remote.yml up -d --build
echo "[remote] Services:"
compose -f compose.remote.yml ps

echo "[remote] Inside uv container, DB is at: postgres://iclr:iclrpass@pgvector:5432/iclr2026"
echo "[remote] To enter uv container: docker compose -f compose.remote.yml exec uvapp bash (or docker-compose ...)"
echo "[remote] Inside container, run: uv sync && uv run python ./scripts/fetch_openreview_iclr2026.py"
