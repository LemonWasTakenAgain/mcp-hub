#!/bin/bash
set -e

# Copy git credentials if mounted read-only
if [ -f /run/secrets/git-credentials ]; then
    cp /run/secrets/git-credentials /home/lemon/.git-credentials
    chmod 600 /home/lemon/.git-credentials
fi

exec uvicorn mcp_hub.main:app --host "${MH_HOST:-0.0.0.0}" --port "${MH_PORT:-8500}"
