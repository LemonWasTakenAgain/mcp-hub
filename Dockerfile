FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl iputils-ping dnsutils git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 lemon && useradd -u 1000 -g lemon -m lemon

COPY --from=builder /install /usr/local
COPY . /app
WORKDIR /app
RUN chown -R lemon:lemon /app

USER lemon
EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8500/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
