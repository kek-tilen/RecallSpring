# syntax=docker/dockerfile:1.7
# RecallSpring in one image (docs/install-docker.md): the API with the built web app, the worker, the MCP connector
# and the PostgreSQL 16 client tools for backups. The same image runs as api, worker, mcp and the one-shot database
# step; compose.yml says which. Build from the repository root:
#   docker build -f infra/docker/Dockerfile -t recallspring:local .
#   docker build -f infra/docker/Dockerfile --build-arg FULL=1 -t recallspring:local-full .   (with LibreOffice)
# Base images are pinned by digest; Python packages are installed from the hashed lock files only.

ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64
ARG NODE_IMAGE=node:22.23.5-bookworm-slim@sha256:be979e5523c76fa4d5ca4ebd3099078f220aa47ec39c48ad5b5df9314debd6eb

# ---------------------------------------------------------------- the web app
# The web app and RecallSpring's two wheels are the same on every CPU, so they are built once on the builder's own
# platform (fast) and only the image stage below is built per platform.
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

# ---------------------------------------------------------------- RecallSpring's own two packages, as wheels
FROM --platform=$BUILDPLATFORM ${PYTHON_IMAGE} AS wheels
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /src
# The dev lock pins setuptools and wheel (with hashes), which building the two packages needs.
COPY services/api/requirements-dev.lock services/api/
RUN python -m venv /build && /build/bin/pip install --require-hashes -r services/api/requirements-dev.lock
COPY services/api/ services/api/
COPY services/mcp/ services/mcp/
COPY infra/docker/linux_lock.py infra/docker/
RUN /build/bin/pip wheel --no-deps --no-build-isolation -w /wheels services/api services/mcp \
 && /build/bin/python infra/docker/linux_lock.py services/mcp/requirements.lock /wheels/mcp-requirements.lock

# ---------------------------------------------------------------- the image
FROM ${PYTHON_IMAGE} AS app
ARG FULL=0
ARG VERSION=dev
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive

# pg_dump/pg_restore 16 for backups, from the PostgreSQL project's apt repository (Debian bookworm only has 15, which
# cannot dump a 16 server). The repository key is checked by its published fingerprint before it is trusted.
# FULL=1 adds LibreOffice (headless) so whole Word, PowerPoint and OpenDocument pages can be shown.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /tmp/pgdg.asc; \
    gpg --show-keys --with-colons /tmp/pgdg.asc | grep -q '^fpr:::::::::B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8:'; \
    gpg --dearmor -o /usr/share/keyrings/pgdg.gpg /tmp/pgdg.asc; \
    echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16; \
    if [ "$FULL" = "1" ]; then apt-get install -y --no-install-recommends libreoffice-nogui fonts-dejavu-core; fi; \
    apt-get purge -y curl gnupg; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/* /tmp/pgdg.asc

COPY services/api/requirements.lock /tmp/api.lock
COPY --from=wheels /wheels /tmp/wheels
RUN set -eux; \
    python -m venv /opt/api; \
    /opt/api/bin/pip install --only-binary=:all: --require-hashes -r /tmp/api.lock; \
    /opt/api/bin/pip install --no-deps /tmp/wheels/recallspring_api-*.whl; \
    python -m venv /opt/mcp; \
    /opt/mcp/bin/pip install --only-binary=:all: --require-hashes -r /tmp/wheels/mcp-requirements.lock; \
    /opt/mcp/bin/pip install --no-deps /tmp/wheels/recallspring_mcp-*.whl; \
    ln -s /opt/mcp/bin/recallspring-mcp /usr/local/bin/recallspring-mcp; \
    rm -rf /tmp/wheels /tmp/api.lock

COPY services/api/alembic.ini /app/api/alembic.ini
COPY services/api/migrations /app/api/migrations
COPY packages/contracts/schemas /app/schemas
COPY --from=web /src/apps/web/dist /app/web
COPY LICENSE /app/LICENSE

# Everything RecallSpring writes goes to /data (material, notes' files, sign-ins, run files) and /backups; the rest of
# the image is read-only. The backup folders come from here and the install's --backups / --sync-folder, not from
# Settings (it would only see paths inside the container); schedule, encryption and cloud copies stay in Settings.
ENV PATH=/opt/api/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/data/home \
    RS_ENVIRONMENT=production \
    RS_COOKIE_SECURE=false \
    RS_STORAGE_DIR=/data/storage \
    RS_RUN_DIR=/data/run \
    RS_SECRETS_DIR=/data/secrets \
    RS_BACKUP_SETTINGS_FILE=/data/backup-settings.json \
    RS_BACKUP_FOLDERS_FROM_WEB=false \
    RS_BACKUP_DIR=/backups \
    RS_BACKUP_DOCKER_CONTAINER= \
    RS_WEB_DIST=/app/web \
    RS_SCHEMAS_DIR=/app/schemas \
    RS_IMAGE_VERSION=${VERSION}

LABEL org.opencontainers.image.title="RecallSpring" \
      org.opencontainers.image.description="Self-hosted study companion: your material, notes, grades and reviews on your own computer" \
      org.opencontainers.image.source="https://github.com/kek-tilen/RecallSpring" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version="${VERSION}"

WORKDIR /app/api
USER 10001:10001
EXPOSE 4318 4319
CMD ["recallspring", "serve", "--host", "0.0.0.0", "--port", "4318"]
