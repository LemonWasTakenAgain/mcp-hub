# MCP Hub

Internal MCP (Model Context Protocol) server and AI tools platform for the homelab.

## Features

- **MCP Server** — Exposes tools over SSE transport for Claude Code, Claude Desktop, and other MCP clients
- **GitLab Tools** — List projects, pipelines, jobs, merge requests; create projects
- **Kubernetes Tools** — Cluster status, namespaces, pods, services, deployments
- **Homelab Tools** — System info, ping, TCP checks, DNS lookups, HTTP health checks
- **Web Dashboard** — Monitor tool usage, view invocation logs, check health
- **REST API** — `/api/tools`, `/api/logs`, `/health`, plus OpenAPI docs at `/docs`

## Quick Start

```bash
# Clone
git clone http://gitlab.steelcanvas.studio/applications/mcp-hub.git
cd mcp-hub

# Start with Docker Compose
export MH_GITLAB_TOKEN=<your-gitlab-pat>
docker compose up -d

# Dashboard: http://localhost:8500
# MCP SSE:   http://localhost:8500/mcp/sse
# API Docs:  http://localhost:8500/docs
```

## Connect MCP Client

Add to your Claude Code `settings.json`:

```json
{
  "mcpServers": {
    "mcp-hub": {
      "type": "sse",
      "url": "http://mcp-hub.steelcanvas.studio/mcp/sse"
    }
  }
}
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# Run locally (requires PostgreSQL)
export MH_DATABASE_URL=postgresql+asyncpg://mcphub:mcphub@localhost:5432/mcphub
uvicorn mcp_hub.main:app --reload --port 8500

# Lint & test
ruff check .
pytest -v
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MH_DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `MH_DEBUG` | `false` | Enable debug logging |
| `MH_HOST` | `0.0.0.0` | Server bind host |
| `MH_PORT` | `8500` | Server bind port |
| `MH_GITLAB_URL` | `http://gitlab.steelcanvas.studio` | GitLab instance URL |
| `MH_GITLAB_TOKEN` | | GitLab Personal Access Token |
| `MH_KUBE_CONFIG` | | Path to kubeconfig (empty = in-cluster) |

## Architecture

```
mcp-hub/
├── mcp_hub/
│   ├── main.py          # FastAPI app + dashboard routes
│   ├── mcp_server.py    # MCP server (FastMCP) with tool registration
│   ├── config.py        # Pydantic settings
│   ├── database.py      # SQLAlchemy async engine
│   ├── models/          # ORM models (ToolLog)
│   └── tools/
│       ├── gitlab_tools.py   # GitLab API integration
│       ├── k8s_tools.py      # Kubernetes client tools
│       └── homelab_tools.py  # System/network utilities
├── templates/           # Jinja2 dashboard templates
├── static/css/          # Dashboard styles
├── migrations/          # Alembic migrations
├── Dockerfile           # Multi-stage build
├── docker-compose.yml   # Local dev stack
└── .gitlab-ci.yml       # CI/CD pipeline
```
