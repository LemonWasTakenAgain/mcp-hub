"""Application configuration via environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "MH_"}

    # Server
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8500
    mcp_port: int = 8501

    # Database
    database_url: str = "postgresql+asyncpg://mcphub:mcphub@localhost:5432/mcphub"

    # GitLab
    gitlab_url: str = "http://gitlab.steelcanvas.studio"
    gitlab_token: str = ""

    # Kubernetes
    kube_config: str = ""

    # Proxy
    proxy_enabled: bool = True
    upstreams_config: str = "upstreams.yaml"

    # Upstream API keys (resolved in upstreams.yaml via ${MH_*} placeholders)
    github_token: str = ""
    brave_api_key: str = ""
    tavily_api_key: str = ""
    exa_api_key: str = ""
    wolfram_app_id: str = ""
    openai_api_key: str = ""
    hf_token: str = ""
    slack_bot_token: str = ""
    discord_token: str = ""
    linear_api_key: str = ""
    notion_api_key: str = ""
    sentry_token: str = ""
    cloudflare_token: str = ""
    grafana_url: str = ""
    grafana_api_key: str = ""
    prometheus_url: str = ""
    proxy_postgres_url: str = ""
    sqlite_path: str = ""
    redis_url: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_endpoint: str = ""

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2").replace(
            "postgresql+psycopg2", "postgresql"
        )


settings = Settings()
