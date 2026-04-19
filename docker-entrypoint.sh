#!/bin/sh
set -e

echo "[entrypoint] Initializing auth database..."
PYTHONPATH=/app/src python /app/src/scripts/init_auth_db.py

echo "[entrypoint] Starting ContextGraph API..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
