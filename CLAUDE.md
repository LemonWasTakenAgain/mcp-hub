# mcp-hub

## Project Context

Internal MCP gateway that aggregates 30+ upstream MCP servers through a single SSE
endpoint. Python 3.11 + FastAPI + MCP Python SDK (FastMCP). PostgreSQL backend with
Alembic migrations. Node.js runtime for npx-based upstream servers.

- GitLab: https://gitlab.steelcanvas.dev/infrastructure/mcp-hub
- GitLab Project ID: 10
- GitHub: https://github.com/LemonWasTakenAgain/mcp-hub
- Dashboard: http://mcp-hub.steelcanvas.dev (port 8500)
- MCP SSE: http://mcp-hub.steelcanvas.dev/mcp/sse

## Commands

```bash
# Dev
pip install -e .[dev]
uvicorn mcp_hub.main:app --reload --port 8500

# Test
pytest -v --cov=mcp_hub

# Lint
ruff check . && ruff format --check .

# Docker
docker compose up -d
```

## Repository Structure

```
mcp-hub/
  mcp_hub/           # Main Python package
    main.py          # FastAPI app entrypoint
    mcp_server.py    # MCP tool registration and proxy
    config.py        # Settings via pydantic-settings (MH_ prefix)
    database.py      # DB session and engine
    metrics.py       # Metrics collection
    models/          # SQLAlchemy models
    dashboard/       # Web dashboard routes and views
    proxy/           # Proxy logic
    tools/           # Tool definitions (includes _validation.py)
    migrations/      # Per-package Alembic migrations
  migrations/        # Alembic migrations (repo root)
  tests/             # pytest test suite
  static/            # Static assets
  templates/         # Jinja2 templates
  upstreams.yaml     # Upstream MCP server definitions (single source of truth)
  docker-compose.yml # Local dev environment
  pyproject.toml     # Project config and dependencies
  alembic.ini        # Alembic configuration
  entrypoint.sh      # Container entrypoint
  Dockerfile
```

## Key Patterns

- Env prefix: `MH_` (e.g. MH_DATABASE_URL, MH_PROXY_ENABLED)
- Tool access: use `get_registered_tools()`, `get_tool_names()`, `register_tool()`, `unregister_tool()` from mcp_server.py — never access `mcp._tool_manager._tools` directly
- Input validation: all user-facing inputs must go through `_validation.py` validators
- Upstream config: single source of truth is `upstreams.yaml`
- Proxy tool naming: `{prefix}__{original_tool_name}` (double underscore)

## CI Pipeline

Stages: lint -> test -> security -> build -> deploy -> mirror
- **lint**: ruff check + format, mypy
- **test**: pytest with coverage, bandit + safety
- **security**: gitleaks secret scanning
- **build**: Docker image via Kaniko (main only)
- **deploy**: kubectl rollout (main, manual)
- **mirror**: Push to GitHub backup
