# Finboard application image (ROADMAP M7, ADR-0040). Build from the repository root:
#
#   docker build -f deploy/Dockerfile -t finboard .
#   docker build -f deploy/Dockerfile --build-arg WITH_AI=1 -t finboard:ai .
#   docker build -f deploy/Dockerfile --build-arg WITH_S3=1 -t finboard:s3 .
#
# Three stages: the SPA (node), the Python environment (uv), and a slim runtime that holds
# neither node nor build tools and runs as a non-root user. One image serves the api, worker
# and beat services (deploy/compose.yaml); only the command differs.

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=24
ARG UV_VERSION=0.13.1

# ---------------------------------------------------------------- SPA
FROM node:${NODE_VERSION}-trixie-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite.config.ts writes the build into the backend package: ../backend/src/finboard/web/static
RUN npm run build

# ---------------------------------------------------------------- Python environment
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-trixie AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/finboard/venv
# WITH_AI=1 adds the optional `ai` extra and bakes the embedding model in, so category
# suggestions work with no download at run time (ARCHITECTURE §18).
ARG WITH_AI=0
# WITH_S3=1 adds the optional `s3` extra (boto3) for FINBOARD_BLOB_BACKEND=s3 (ADR-0026).
ARG WITH_S3=0
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project $([ "$WITH_AI" = 1 ] && echo "--extra ai") $([ "$WITH_S3" = 1 ] && echo "--extra s3")
COPY backend/src ./src
COPY --from=web /src/backend/src/finboard/web/static ./src/finboard/web/static
# Not editable: the package (with the built SPA inside it) is copied into the environment, so
# the runtime stage needs the environment only.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable $([ "$WITH_AI" = 1 ] && echo "--extra ai") $([ "$WITH_S3" = 1 ] && echo "--extra s3")
RUN mkdir -p /opt/finboard/models \
    && if [ "$WITH_AI" = 1 ]; then \
         FINBOARD_MODEL_DIR=/opt/finboard/models /opt/finboard/venv/bin/finboard ai fetch-model \
         && chmod -R a+rX /opt/finboard/models; \
       fi

# ---------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
# pg_dump for the backup before a migration (ADR-0037). It must not be older than the server,
# and Debian's own client is, so Postgres 18's comes from the PostgreSQL apt repository.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates postgresql-common \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 finboard \
    && useradd --uid 10001 --gid 10001 --home-dir /data --no-create-home --shell /usr/sbin/nologin finboard \
    && mkdir -p /data/blobs /data/backups \
    && chown -R finboard:finboard /data
COPY --from=build /opt/finboard /opt/finboard
ENV PATH=/opt/finboard/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FINBOARD_ENV=prod \
    FINBOARD_HOST=0.0.0.0 \
    FINBOARD_PORT=8000 \
    FINBOARD_BLOB_DIR=/data/blobs \
    FINBOARD_BACKUP_DIR=/data/backups \
    FINBOARD_MODEL_DIR=/opt/finboard/models
ARG VERSION=dev
LABEL org.opencontainers.image.title="Finboard" \
      org.opencontainers.image.description="Private personal finance: statement import, rules, dashboard" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
USER 10001:10001
WORKDIR /data
VOLUME /data
EXPOSE 8000
CMD ["finboard", "serve"]
