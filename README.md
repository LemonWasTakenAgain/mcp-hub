# MCP Hub

Internal MCP (Model Context Protocol) server and AI tools platform for the homelab. Acts as a **single gateway** that aggregates dozens of upstream MCP servers — your AIs connect once and get access to everything.

## How It Works

```
Claude Code / Claude Desktop / Any MCP Client
            │
            ▼
    ┌───────────────┐
    │   MCP Hub     │  ← single SSE connection
    │  (FastAPI)    │
    └──────┬────────┘
           │
    ┌──────┴────────────────────────────────┐
    │                                       │
    ▼              ▼              ▼         ▼
 Local Tools    GitHub MCP    Brave MCP   Wikipedia MCP
 (GitLab,K8s,   (stdio)       (stdio)     (stdio)
  Homelab)        ...           ...         ...
```

Your AI connects to **one endpoint** and gets access to:
- 15 built-in local tools (GitLab, Kubernetes, Homelab)
- 30+ upstream MCP servers (search, databases, code, AI, monitoring, communication)

## Quick Start

```bash
cd ~/projects/homelab/mcp-hub
export MH_GITLAB_TOKEN=<your-gitlab-pat>
export MH_GITHUB_TOKEN=<your-github-token>
docker compose up -d

# Dashboard: http://localhost:8500
# MCP SSE:   http://localhost:8500/mcp/sse
```

## Connect Your AI

Add to Claude Code `settings.json`:

```json
{
  "mcpServers": {
    "mcp-hub": {
      "type": "sse",
      "url": "http://mcp-hub.steelcanvas.dev/mcp/sse"
    }
  }
}
```

That's it. One connection, all tools.

## Available Upstream Servers

Configured in `upstreams.yaml`. Enabled by default (no API key needed):

| Server | Prefix | Description |
|--------|--------|-------------|
| fetch | `web__` | Fetch web pages, convert to markdown |
| github | `github__` | Repos, issues, PRs, actions, code search |
| docker | `docker__` | Container, image, volume management |
| arxiv | `arxiv__` | Search and read academic papers |
| wikipedia | `wiki__` | Search and read encyclopedia articles |
| filesystem | `fs__` | Read, write, search files |
| memory | `memory__` | Persistent knowledge graph |
| time | `time__` | Time, timezone conversions |
| sequential-thinking | `think__` | Structured reasoning |

Set an API key to enable:

| Server | Prefix | Env Var |
|--------|--------|---------|
| Brave Search | `brave__` | `MH_BRAVE_API_KEY` |
| Tavily | `tavily__` | `MH_TAVILY_API_KEY` |
| Exa | `exa__` | `MH_EXA_API_KEY` |
| Puppeteer | `browser__` | (just enable) |
| PostgreSQL | `pg__` | `MH_PROXY_POSTGRES_URL` |
| SQLite | `sqlite__` | `MH_SQLITE_PATH` |
| Redis | `redis__` | `MH_REDIS_URL` |
| Qdrant | `qdrant__` | `MH_QDRANT_URL` |
| Wolfram Alpha | `wolfram__` | `MH_WOLFRAM_APP_ID` |
| Slack | `slack__` | `MH_SLACK_BOT_TOKEN` |
| Discord | `discord__` | `MH_DISCORD_TOKEN` |
| Linear | `linear__` | `MH_LINEAR_API_KEY` |
| Notion | `notion__` | `MH_NOTION_API_KEY` |
| HuggingFace | `hf__` | `MH_HF_TOKEN` |
| OpenAI | `openai__` | `MH_OPENAI_API_KEY` |
| Prometheus | `prom__` | `MH_PROMETHEUS_URL` |
| Grafana | `grafana__` | `MH_GRAFANA_URL` + `MH_GRAFANA_API_KEY` |
| Sentry | `sentry__` | `MH_SENTRY_TOKEN` |
| S3/MinIO | `s3__` | `MH_S3_ACCESS_KEY` + `MH_S3_SECRET_KEY` |
| Cloudflare | `cf__` | `MH_CLOUDFLARE_TOKEN` |
| Terraform | `tf__` | (just enable) |
| Google Drive | `gdrive__` | (OAuth setup) |

## Adding Custom Upstream Servers

Edit `upstreams.yaml`:

```yaml
upstreams:
  # stdio-based (spawns a local process)
  my-server:
    transport: stdio
    enabled: true
    description: "My custom MCP server"
    command: npx
    args: ["-y", "my-mcp-package"]
    env:
      API_KEY: "${MH_MY_API_KEY}"
    prefix: my

  # SSE-based (connects to a remote HTTP endpoint)
  remote-server:
    transport: sse
    enabled: true
    description: "Remote MCP server"
    url: "http://192.168.1.50:9000/mcp/sse"
    headers:
      Authorization: "Bearer ${MH_REMOTE_TOKEN}"
    prefix: remote
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web dashboard |
| `GET /health` | Health check (DB + proxy status) |
| `GET /api/tools` | All tools (local + proxied) with source |
| `GET /api/logs` | Tool invocation logs |
| `GET /api/proxy/status` | Upstream connection status |
| `GET /api/proxy/tools` | Proxied tool name -> source mapping |
| `POST /api/proxy/reconnect/{name}` | Reconnect a specific upstream |
| `GET /mcp/sse` | MCP SSE endpoint |
| `GET /docs` | OpenAPI docs |

## Architecture

```
mcp-hub/
├── mcp_hub/
│   ├── main.py            # FastAPI app + dashboard + proxy lifecycle
│   ├── mcp_server.py      # MCP server (FastMCP) with local tools
│   ├── config.py          # Pydantic settings (MH_* env vars)
│   ├── database.py        # SQLAlchemy async engine
│   ├── models/            # ORM models (ToolLog)
│   ├── tools/             # Built-in local tools
│   │   ├── gitlab_tools.py
│   │   ├── k8s_tools.py
│   │   └── homelab_tools.py
│   └── proxy/             # Upstream MCP proxy engine
│       ├── manager.py     # Orchestrates connections, registers proxied tools
│       ├── connector.py   # MCP client for a single upstream (stdio/SSE)
│       ├── registry.py    # Server config dataclass + YAML loader
│       ├── defaults.py    # Built-in default upstream configs
│       └── env_resolver.py # ${VAR} placeholder resolution
├── upstreams.yaml         # User-editable upstream config
├── templates/             # Jinja2 dashboard
├── static/css/            # Dark-themed dashboard styles
├── Dockerfile             # Multi-stage (Python + Node.js for npx)
├── docker-compose.yml     # Local dev stack
└── .gitlab-ci.yml         # CI/CD pipeline
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# Run locally
export MH_DATABASE_URL=postgresql+asyncpg://mcphub:mcphub@localhost:5432/mcphub
uvicorn mcp_hub.main:app --reload --port 8500

# Lint & test
ruff check .
pytest -v
```
