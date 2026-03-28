ARG PYTHON_BASE=python:3.11-slim
FROM ${PYTHON_BASE} AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --prefix=/install .
COPY mcp_hub/ mcp_hub/
COPY README.md .

FROM ${PYTHON_BASE}

# Install system tools + Node.js (for npx-based MCP servers) + uv/uvx (for Python MCP servers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl iputils-ping dnsutils git ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && curl -fsSL "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/$(dpkg --print-architecture)/kubectl" \
        -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

RUN groupadd -g 1000 lemon && useradd -u 1000 -g lemon -m lemon

COPY --from=builder /install /usr/local
COPY . /app
WORKDIR /app
RUN chown -R lemon:lemon /app

USER lemon

# Pre-warm npx/uvx cache for enabled servers (runs once at build time)
RUN npx -y @modelcontextprotocol/server-github --help 2>/dev/null || true \
    && npx -y @modelcontextprotocol/server-filesystem --help 2>/dev/null || true \
    && npx -y @modelcontextprotocol/server-memory --help 2>/dev/null || true \
    && npx -y @modelcontextprotocol/server-sequential-thinking --help 2>/dev/null || true \
    && npx -y wikipedia-mcp --help 2>/dev/null || true \
    && npx -y mcp-server-docker --help 2>/dev/null || true \
    && npx -y terraform-mcp-server --help 2>/dev/null || true \
    && npx -y argocd-mcp@latest --help 2>/dev/null || true \
    && npx -y mcp-server-kubernetes --help 2>/dev/null || true \
    && uvx mcp-server-time --help 2>/dev/null || true \
    && uvx arxiv-mcp-server --help 2>/dev/null || true \
    && uvx mcp-grafana --help 2>/dev/null || true \
    && uvx prometheus-mcp-server --help 2>/dev/null || true \
    && uvx mcp-server-qdrant --help 2>/dev/null || true \
    && npx -y ollama-mcp --help 2>/dev/null || true \
    && npx -y n8n-mcp-server --help 2>/dev/null || true \
    && uvx mcp-proxmox --help 2>/dev/null || true

# Install sandbox-mcp-server from private GitLab repo
# CI_JOB_TOKEN is short-lived and safe to use as a build arg
ARG GITLAB_TOKEN=""
RUN pip install --no-cache-dir \
        "sandbox-mcp-server @ git+https://gitlab-ci-token:${GITLAB_TOKEN}@gitlab.steelcanvas.studio/user-projects/sandbox-mcp-server.git@main" \
    || echo "WARN: sandbox-mcp-server install failed (no token or repo unreachable)"

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -f http://localhost:8500/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
