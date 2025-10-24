#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
cd "$ROOT"

# Auto-load .env to get DB and OpenAI settings
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export PYTHONUNBUFFERED=1

# Wait for DB if configured to use docker compose pgvector service
DB_HOST=${POSTGRES_HOST:-127.0.0.1}
DB_PORT=${POSTGRES_PORT:-5433}
if [ "$DB_HOST" = "pgvector" ]; then
  DB_HOST=127.0.0.1
  DB_PORT=5433
fi

echo "[mcp] Waiting for DB at $DB_HOST:$DB_PORT ..."
for i in $(seq 1 60); do
  if (echo > /dev/tcp/$DB_HOST/$DB_PORT) >/dev/null 2>&1; then
    echo "[mcp] DB is reachable."
    break
  fi
  echo "[mcp] Still waiting ($i/60)..."
  sleep 2
done

echo "Starting FastMCP server (HTTP transport) on :8765/mcp ..."
exec uv run fastmcp run app/mcp_server.py --transport http --host 0.0.0.0 --port 8765 --path /mcp

