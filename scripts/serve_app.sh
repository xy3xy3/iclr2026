#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
cd "$ROOT"

# Auto-load .env if present (for OPENAI_API_KEY/BASE_URL/etc.)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export PYTHONUNBUFFERED=1

# Wait for DB to be reachable to avoid startup race
DB_HOST=${POSTGRES_HOST:-127.0.0.1}
DB_PORT=${POSTGRES_PORT:-5433}
if [ "$DB_HOST" = "pgvector" ]; then
  # local fallback when not in compose network
  DB_HOST=127.0.0.1
  DB_PORT=5433
fi

echo "[serve] Waiting for DB at $DB_HOST:$DB_PORT ..."
for i in $(seq 1 60); do
  if (echo > /dev/tcp/$DB_HOST/$DB_PORT) >/dev/null 2>&1; then
    echo "[serve] DB is reachable."
    break
  fi
  echo "[serve] Still waiting ($i/60)..."
  sleep 2
done

echo "Starting FastAPI + Gradio server on :8000 ..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
