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

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2").replace(
            "postgresql+psycopg2", "postgresql"
        )


settings = Settings()
