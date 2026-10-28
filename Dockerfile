FROM python:3.13-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.3 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13-slim-bookworm
LABEL org.opencontainers.image.title="AOOSTAR OpenScreen" \
    org.opencontainers.image.version="1.0.1" \
    org.opencontainers.image.source="https://github.com/Niklas-s04/aoostar-openscreen"
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-liberation2 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 openscreen && useradd -u 10001 -g openscreen -M openscreen \
    && mkdir -p /data /run/openscreen-broker && chown openscreen:openscreen /data /run/openscreen-broker \
    && chmod 0700 /run/openscreen-broker
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY openscreen /app/openscreen
RUN find /app/openscreen -type d -exec chmod 0755 {} + \
    && find /app/openscreen -type f -exec chmod 0644 {} +
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENSCREEN_DATA=/data OPENSCREEN_SECRETS=/run/secrets
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["uvicorn", "openscreen.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
