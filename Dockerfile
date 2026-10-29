FROM python:3.13-alpine3.24@sha256:8bcfa47b04b853a17aaf909362b847b2112fd6ec4105ea553ef9a43bafbb5916 AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.3@sha256:bee0a2a458fd956c5df7b8b4c5fed2257b0af34866e3da7b51db0be3acb375d1 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS fonts
RUN rm /etc/apt/sources.list.d/debian.sources \
    && printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261020T000000Z/ bookworm main\n' > /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-dejavu-extra fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/* /var/log/apt /var/log/dpkg.log

FROM python:3.13-alpine3.24@sha256:8bcfa47b04b853a17aaf909362b847b2112fd6ec4105ea553ef9a43bafbb5916
ARG SOURCE_DATE_EPOCH=1793232000
LABEL org.opencontainers.image.title="AOOSTAR OpenScreen" \
    org.opencontainers.image.version="1.0.2" \
    org.opencontainers.image.source="https://github.com/Niklas-s04/aoostar-openscreen"
RUN addgroup -g 10001 openscreen && adduser -D -H -u 10001 -G openscreen openscreen \
    && mkdir -p /data /run/openscreen-broker && chown openscreen:openscreen /data /run/openscreen-broker \
    && chmod 0700 /run/openscreen-broker
COPY --from=fonts /usr/share/fonts/truetype/dejavu /usr/share/fonts/truetype/dejavu
COPY --from=fonts /usr/share/fonts/truetype/liberation2 /usr/share/fonts/truetype/liberation2
COPY --from=fonts /usr/share/doc/fonts-dejavu-core /usr/share/doc/fonts-dejavu-core
COPY --from=fonts /usr/share/doc/fonts-dejavu-extra /usr/share/doc/fonts-dejavu-extra
COPY --from=fonts /usr/share/doc/fonts-liberation2 /usr/share/doc/fonts-liberation2
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY openscreen /app/openscreen
COPY LICENSE /app/LICENSE
RUN rm -rf /usr/local/lib/python3.13/site-packages/* /usr/local/lib/python3.13/ensurepip /usr/local/bin/pip* \
    && chmod 0644 /app/LICENSE \
    && find /app/openscreen -type d -name __pycache__ -prune -exec rm -r {} + \
    && find /app/openscreen -type d -exec chmod 0755 {} + \
    && find /app/openscreen -type f -exec chmod 0644 {} +
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENSCREEN_DATA=/data OPENSCREEN_SECRETS=/run/secrets
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["uvicorn", "openscreen.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
