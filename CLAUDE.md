# Claude Code Configuration

## Project Context
MCP Hub — internal MCP gateway that aggregates 30+ upstream MCP servers through a single SSE endpoint.
- GitLab Project ID: 10
- Repo: ~/projects/homelab/mcp-hub
- GitLab: https://gitlab.steelcanvas.studio/infrastructure/mcp-hub
- GitHub: https://github.com/LemonWasTakenAgain/mcp-hub
- Dashboard: http://mcp-hub.steelcanvas.studio (port 8500)
- MCP SSE: http://mcp-hub.steelcanvas.studio/mcp/sse

## Stack
- Python 3.11, FastAPI, MCP Python SDK (FastMCP)
- PostgreSQL + SQLAlchemy async + Alembic migrations
- Node.js (for npx-based upstream MCP servers)
- Docker + docker-compose for local dev

## Repository Structure

```
mcp-hub/
├── mcp_hub/           # Main Python package
│   ├── main.py        # FastAPI app entrypoint
│   ├── mcp_server.py  # MCP tool registration and proxy
│   ├── _validation.py # Input validation
│   └── models/        # SQLAlchemy models
├── upstreams.yaml     # Upstream MCP server definitions (single source of truth)
├── alembic/           # Database migrations
├── tests/             # pytest test suite
├── docker-compose.yml # Local dev environment
└── pyproject.toml     # Project config and dependencies
```

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

## Key Patterns
- Env prefix: `MH_` (e.g. MH_DATABASE_URL, MH_PROXY_ENABLED)
- Tool access: use `get_registered_tools()`, `get_tool_names()`, `register_tool()`, `unregister_tool()` from mcp_server.py — never access `mcp._tool_manager._tools` directly
- Input validation: all user-facing inputs must go through `_validation.py` validators
- Upstream config: single source of truth is `upstreams.yaml`
- Proxy tool naming: `{prefix}__{original_tool_name}` (double underscore)

## CI Pipeline

Stages: lint → test → security → build → deploy → mirror
- **lint**: ruff check + format, mypy
- **test**: pytest with coverage, bandit + safety
- **security**: gitleaks secret scanning
- **build**: Docker image via Kaniko (main only)
- **deploy**: kubectl rollout (main, manual)
- **mirror**: Push to GitHub backup
