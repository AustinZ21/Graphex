#!/bin/sh
set -e

echo "[entrypoint] Initializing auth database..."
python -m scripts.init_auth_db

echo "[entrypoint] Starting ContextGraph API..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
