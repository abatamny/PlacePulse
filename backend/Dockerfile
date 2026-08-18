FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS builder

ARG UV_VERSION=0.12.5
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir "uv==${UV_VERSION}"
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --group dev
COPY backend/ ./
RUN uv sync --frozen --group dev

FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8

ENV PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 placepulse \
    && useradd --uid 10001 --gid placepulse --create-home --home-dir /home/placepulse placepulse

WORKDIR /app/backend
COPY --from=builder --chown=placepulse:placepulse /app/backend /app/backend
COPY --chown=placepulse:placepulse data/osm /app/data/osm
COPY --chown=placepulse:placepulse contracts /app/contracts

USER 10001:10001
