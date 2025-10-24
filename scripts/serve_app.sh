#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
cd "$ROOT"

export PYTHONUNBUFFERED=1

echo "Starting FastAPI + Gradio server on :8000 ..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers

