FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY mcp_hub/ mcp_hub/
COPY README.md .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim

# Install system tools + Node.js (for npx-based MCP servers) + uv/uvx (for Python MCP servers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl iputils-ping dnsutils git ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

RUN groupadd -g 1000 lemon && useradd -u 1000 -g lemon -m lemon

COPY --from=builder /install /usr/local
COPY . /app
WORKDIR /app
RUN chown -R lemon:lemon /app

USER lemon

# Pre-warm npx cache for enabled servers (runs once at build time)
RUN npx -y @modelcontextprotocol/server-github --help 2>/dev/null || true \
    && npx -y @modelcontextprotocol/server-filesystem --help 2>/dev/null || true \
    && npx -y @modelcontextprotocol/server-memory --help 2>/dev/null || true \
    && npx -y @modelcontextprotocol/server-time --help 2>/dev/null || true \
    && npx -y @modelcontextprotocol/server-sequential-thinking --help 2>/dev/null || true \
    && npx -y mcp-server-wikipedia --help 2>/dev/null || true \
    && npx -y mcp-docker --help 2>/dev/null || true \
    && npx -y @hashicorp/terraform-mcp-server --help 2>/dev/null || true \
    && npx -y @grafana/mcp-grafana --help 2>/dev/null || true \
    && npx -y @grafana/loki-mcp --help 2>/dev/null || true \
    && npx -y @argoproj-labs/mcp-for-argocd --help 2>/dev/null || true \
    && npx -y mcp-server-kubernetes --help 2>/dev/null || true \
    && npx -y @sonarsource/sonarqube-mcp-server --help 2>/dev/null || true \
    && npx -y @netboxlabs/netbox-mcp-server --help 2>/dev/null || true \
    && npx -y n8n-mcp-server --help 2>/dev/null || true

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -f http://localhost:8500/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
