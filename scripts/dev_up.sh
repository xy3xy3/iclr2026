#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/.."
cd "$ROOT"

echo "[dev] Starting local pgvector (port 5433)..."
docker compose -f compose.local.yml up -d
echo "[dev] Services:"
docker compose -f compose.local.yml ps

echo "[dev] Connection string: postgres://iclr:iclrpass@127.0.0.1:5433/iclr2026"
