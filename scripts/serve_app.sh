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

echo "Starting FastAPI + Gradio server on :8000 ..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
