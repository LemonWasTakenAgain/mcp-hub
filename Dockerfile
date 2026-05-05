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
ENV PATH="/home/lemon/.local/bin:${PATH}"

# Pre-warm cache happens at runtime now — the build-time pre-warm (npx -y of
# every MCP server) added a ~1 GB layer that breaks registry pushes when the
# registry storage backend is degraded. Servers will be downloaded lazily on
# first invocation by the proxy. Re-evaluate if startup latency becomes a
# problem and a faster-than-network-pull path is needed (e.g., bake a slim
# subset, or use a sidecar warm-up Job).

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD curl -f http://localhost:8500/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
