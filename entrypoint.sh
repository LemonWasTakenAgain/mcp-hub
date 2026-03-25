#!/bin/bash
set -e

# Copy git credentials if mounted read-only
if [ -f /run/secrets/git-credentials ]; then
    cp /run/secrets/git-credentials /home/lemon/.git-credentials
    chmod 600 /home/lemon/.git-credentials
fi

# Run database migrations
echo "Running database migrations..."
python -m alembic upgrade head 2>/dev/null || echo "Migration skipped (DB may not be ready yet, tables will be auto-created)"

exec uvicorn mcp_hub.main:app --host "${MH_HOST:-0.0.0.0}" --port "${MH_PORT:-8500}"
