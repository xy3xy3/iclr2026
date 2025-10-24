#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
cd "$ROOT"

# Auto-load .env if present
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

echo "[bootstrap] Ensuring DB schema..."
uv run python ./scripts/init_db.py

echo "[bootstrap] Embedding only missing rows..."
EMBED_ONLY_MISSING=${EMBED_ONLY_MISSING:-1} \
uv run python ./scripts/embed_papers.py

echo "[bootstrap] Done."

