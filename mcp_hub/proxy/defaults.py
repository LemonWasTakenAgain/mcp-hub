"""Default upstream MCP server configurations.

These are the most useful public MCP servers available.
Each requires its own API key or setup — disabled by default until configured.
"""

from mcp_hub.proxy.registry import TransportType, UpstreamRegistry, UpstreamServer


def get_default_registry() -> UpstreamRegistry:
    """Build the default registry with all known useful upstream MCP servers."""
    registry = UpstreamRegistry()

    # =========================================================================
    # SEARCH & WEB
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="brave-search",
            transport=TransportType.STDIO,
            enabled=False,
            description="Brave Search API — web search and local search",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-brave-search"],
            env={"BRAVE_API_KEY": "${MH_BRAVE_API_KEY}"},
            prefix="brave",
        )
    )

    registry.add(
        UpstreamServer(
            name="tavily",
            transport=TransportType.STDIO,
            enabled=False,
            description="Tavily AI search — optimized for AI agents",
            command="npx",
            args=["-y", "tavily-mcp@latest"],
            env={"TAVILY_API_KEY": "${MH_TAVILY_API_KEY}"},
            prefix="tavily",
        )
    )

    registry.add(
        UpstreamServer(
            name="exa",
            transport=TransportType.STDIO,
            enabled=False,
            description="Exa AI — neural search engine for semantic queries",
            command="npx",
            args=["-y", "exa-mcp-server"],
            env={"EXA_API_KEY": "${MH_EXA_API_KEY}"},
            prefix="exa",
        )
    )

    registry.add(
        UpstreamServer(
            name="fetch",
            transport=TransportType.STDIO,
            enabled=True,
            description="Fetch web pages and convert to markdown — no API key needed",
            command="uvx",
            args=["mcp-server-fetch"],
            prefix="web",
        )
    )

    registry.add(
        UpstreamServer(
            name="puppeteer",
            transport=TransportType.STDIO,
            enabled=False,
            description="Browser automation — navigate, screenshot, interact with pages",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-puppeteer"],
            prefix="browser",
        )
    )

    # =========================================================================
    # CODE & DEVELOPMENT
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="github",
            transport=TransportType.STDIO,
            enabled=True,
            description="GitHub API — repos, issues, PRs, actions, code search",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "${MH_GITHUB_TOKEN}"},
            prefix="github",
        )
    )

    registry.add(
        UpstreamServer(
            name="gitlab",
            transport=TransportType.STDIO,
            enabled=False,
            description="GitLab API — projects, pipelines, MRs (use built-in tools for local)",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-gitlab"],
            env={
                "GITLAB_PERSONAL_ACCESS_TOKEN": "${MH_GITLAB_TOKEN}",
                "GITLAB_API_URL": "${MH_GITLAB_URL}/api/v4",
            },
            prefix="ext_gitlab",
        )
    )

    registry.add(
        UpstreamServer(
            name="docker",
            transport=TransportType.STDIO,
            enabled=True,
            description="Docker management — containers, images, volumes, networks",
            command="npx",
            args=["-y", "mcp-docker"],
            prefix="docker",
        )
    )

    registry.add(
        UpstreamServer(
            name="kubernetes",
            transport=TransportType.STDIO,
            enabled=False,
            description="Kubernetes management (use built-in tools for local cluster)",
            command="npx",
            args=["-y", "mcp-k8s"],
            prefix="ext_k8s",
        )
    )

    # =========================================================================
    # DATABASES
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="postgres",
            transport=TransportType.STDIO,
            enabled=False,
            description="PostgreSQL — query any Postgres database directly",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-postgres", "${MH_PROXY_POSTGRES_URL}"],
            prefix="pg",
        )
    )

    registry.add(
        UpstreamServer(
            name="sqlite",
            transport=TransportType.STDIO,
            enabled=False,
            description="SQLite — read and query SQLite databases",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-sqlite", "${MH_SQLITE_PATH}"],
            prefix="sqlite",
        )
    )

    registry.add(
        UpstreamServer(
            name="redis",
            transport=TransportType.STDIO,
            enabled=False,
            description="Redis — key-value operations, pub/sub, data structures",
            command="npx",
            args=["-y", "redis-mcp", "${MH_REDIS_URL}"],
            prefix="redis",
        )
    )

    registry.add(
        UpstreamServer(
            name="qdrant",
            transport=TransportType.STDIO,
            enabled=False,
            description="Qdrant vector database — semantic search and embeddings",
            command="uvx",
            args=["mcp-server-qdrant"],
            env={
                "QDRANT_URL": "${MH_QDRANT_URL}",
                "QDRANT_API_KEY": "${MH_QDRANT_API_KEY}",
            },
            prefix="qdrant",
        )
    )

    # =========================================================================
    # KNOWLEDGE & RESEARCH
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="arxiv",
            transport=TransportType.STDIO,
            enabled=True,
            description="Arxiv — search and read academic papers (no API key needed)",
            command="uvx",
            args=["mcp-server-arxiv"],
            prefix="arxiv",
        )
    )

    registry.add(
        UpstreamServer(
            name="wikipedia",
            transport=TransportType.STDIO,
            enabled=True,
            description="Wikipedia — search and read encyclopedia articles (no API key)",
            command="npx",
            args=["-y", "mcp-server-wikipedia"],
            prefix="wiki",
        )
    )

    registry.add(
        UpstreamServer(
            name="wolfram-alpha",
            transport=TransportType.STDIO,
            enabled=False,
            description="Wolfram Alpha — computational knowledge, math, data analysis",
            command="npx",
            args=["-y", "mcp-wolfram-alpha"],
            env={"WOLFRAM_APP_ID": "${MH_WOLFRAM_APP_ID}"},
            prefix="wolfram",
        )
    )

    # =========================================================================
    # FILES & STORAGE
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="filesystem",
            transport=TransportType.STDIO,
            enabled=True,
            description="Filesystem — read, write, search files in allowed directories",
            command="npx",
            args=[
                "-y",
                "@modelcontextprotocol/server-filesystem",
                "${MH_FS_ALLOWED_DIRS}",
            ],
            prefix="fs",
        )
    )

    registry.add(
        UpstreamServer(
            name="s3",
            transport=TransportType.STDIO,
            enabled=False,
            description="S3/MinIO — bucket operations and object storage",
            command="npx",
            args=["-y", "mcp-s3"],
            env={
                "AWS_ACCESS_KEY_ID": "${MH_S3_ACCESS_KEY}",
                "AWS_SECRET_ACCESS_KEY": "${MH_S3_SECRET_KEY}",
                "AWS_ENDPOINT_URL": "${MH_S3_ENDPOINT}",
                "AWS_REGION": "us-east-1",
            },
            prefix="s3",
        )
    )

    registry.add(
        UpstreamServer(
            name="gdrive",
            transport=TransportType.STDIO,
            enabled=False,
            description="Google Drive — search, read, and manage Drive files",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-gdrive"],
            prefix="gdrive",
        )
    )

    # =========================================================================
    # COMMUNICATION & PRODUCTIVITY
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="slack",
            transport=TransportType.STDIO,
            enabled=False,
            description="Slack — read channels, post messages, search conversations",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-slack"],
            env={"SLACK_BOT_TOKEN": "${MH_SLACK_BOT_TOKEN}"},
            prefix="slack",
        )
    )

    registry.add(
        UpstreamServer(
            name="discord",
            transport=TransportType.STDIO,
            enabled=False,
            description="Discord — read channels, post messages, manage server",
            command="npx",
            args=["-y", "mcp-discord"],
            env={"DISCORD_TOKEN": "${MH_DISCORD_TOKEN}"},
            prefix="discord",
        )
    )

    registry.add(
        UpstreamServer(
            name="linear",
            transport=TransportType.STDIO,
            enabled=False,
            description="Linear — project management, issues, sprints, teams",
            command="npx",
            args=["-y", "mcp-linear"],
            env={"LINEAR_API_KEY": "${MH_LINEAR_API_KEY}"},
            prefix="linear",
        )
    )

    registry.add(
        UpstreamServer(
            name="notion",
            transport=TransportType.STDIO,
            enabled=False,
            description="Notion — read and manage Notion pages and databases",
            command="npx",
            args=["-y", "mcp-notion"],
            env={"NOTION_API_KEY": "${MH_NOTION_API_KEY}"},
            prefix="notion",
        )
    )

    # =========================================================================
    # AI & ML
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="huggingface",
            transport=TransportType.STDIO,
            enabled=False,
            description="HuggingFace — model search, dataset info, spaces, inference",
            command="npx",
            args=["-y", "mcp-huggingface"],
            env={"HF_TOKEN": "${MH_HF_TOKEN}"},
            prefix="hf",
        )
    )

    registry.add(
        UpstreamServer(
            name="openai",
            transport=TransportType.STDIO,
            enabled=False,
            description="OpenAI API — GPT completions, embeddings, DALL-E, Whisper",
            command="npx",
            args=["-y", "mcp-openai"],
            env={"OPENAI_API_KEY": "${MH_OPENAI_API_KEY}"},
            prefix="openai",
        )
    )

    # =========================================================================
    # MONITORING & OBSERVABILITY
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="prometheus",
            transport=TransportType.STDIO,
            enabled=False,
            description="Prometheus — query metrics, alerts, targets",
            command="uvx",
            args=["mcp-server-prometheus", "--url", "${MH_PROMETHEUS_URL}"],
            prefix="prom",
        )
    )

    registry.add(
        UpstreamServer(
            name="grafana",
            transport=TransportType.STDIO,
            enabled=False,
            description="Grafana — dashboards, datasources, annotations",
            command="npx",
            args=["-y", "mcp-grafana"],
            env={
                "GRAFANA_URL": "${MH_GRAFANA_URL}",
                "GRAFANA_API_KEY": "${MH_GRAFANA_API_KEY}",
            },
            prefix="grafana",
        )
    )

    registry.add(
        UpstreamServer(
            name="sentry",
            transport=TransportType.STDIO,
            enabled=False,
            description="Sentry — error tracking, issues, performance monitoring",
            command="npx",
            args=["-y", "mcp-server-sentry"],
            env={"SENTRY_AUTH_TOKEN": "${MH_SENTRY_TOKEN}"},
            prefix="sentry",
        )
    )

    # =========================================================================
    # CLOUD & INFRA
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="terraform",
            transport=TransportType.STDIO,
            enabled=False,
            description="Terraform — state, plan, resources, modules",
            command="npx",
            args=["-y", "mcp-terraform"],
            prefix="tf",
        )
    )

    registry.add(
        UpstreamServer(
            name="cloudflare",
            transport=TransportType.STDIO,
            enabled=False,
            description="Cloudflare — DNS, Workers, Pages, WAF, analytics",
            command="npx",
            args=["-y", "@cloudflare/mcp-server-cloudflare"],
            env={"CLOUDFLARE_API_TOKEN": "${MH_CLOUDFLARE_TOKEN}"},
            prefix="cf",
        )
    )

    # =========================================================================
    # UTILITIES
    # =========================================================================

    registry.add(
        UpstreamServer(
            name="memory",
            transport=TransportType.STDIO,
            enabled=True,
            description="Persistent memory — knowledge graph for long-term storage (no API key)",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
            prefix="memory",
        )
    )

    registry.add(
        UpstreamServer(
            name="time",
            transport=TransportType.STDIO,
            enabled=True,
            description="Time — current time, timezone conversions (no API key)",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-time"],
            prefix="time",
        )
    )

    registry.add(
        UpstreamServer(
            name="sequential-thinking",
            transport=TransportType.STDIO,
            enabled=True,
            description="Sequential thinking — structured step-by-step reasoning (no API key)",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-sequential-thinking"],
            prefix="think",
        )
    )

    registry.add(
        UpstreamServer(
            name="everything",
            transport=TransportType.STDIO,
            enabled=False,
            description="MCP test server — all MCP features for testing/debugging",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-everything"],
            prefix="test",
        )
    )

    return registry
