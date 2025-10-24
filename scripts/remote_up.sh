#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
cd "$ROOT"

echo "[remote] Building uv image and starting pgvector+uvapp..."
docker compose -f compose.remote.yml up -d --build
echo "[remote] Services:"
docker compose -f compose.remote.yml ps

echo "[remote] DB connection string: postgres://iclr:iclrpass@127.0.0.1:5432/iclr2026"
echo "[remote] To enter uv container: docker compose -f compose.remote.yml exec uvapp bash"
echo "[remote] Inside container, run: uv sync && uv run python ./scripts/fetch_openreview_iclr2026.py"
