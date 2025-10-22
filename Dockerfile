# ============================================
#   Stage 1 – Builder
#   Builds ALL wheels incl. dependencies
# ============================================
FROM python:3.14-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Toolchain needed to build native wheels (removed in runtime)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc g++ python3-dev pkg-config cmake \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Upgrade pip/wheel and build wheels for the ENTIRE dependency tree
# (IMPORTANT: no --no-deps here, so transitive deps like 'brotli' get built, too)
RUN python -m pip install --upgrade pip wheel \
 && python -m pip wheel --wheel-dir /wheels -r requirements.txt


# ============================================
#   Stage 2 – Runtime
#   Minimal image, offline install from wheels
# ============================================
FROM python:3.14-slim-bookworm AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UMASK=027

ARG APP_USER=appuser
ARG APP_UID=10001
RUN useradd -u ${APP_UID} -m -s /usr/sbin/nologin ${APP_USER}

WORKDIR /app
RUN mkdir -p /opt/venv /var/log/app /tmp/app \
 && chown -R ${APP_USER}:${APP_USER} /app /opt/venv /var/log/app /tmp/app

# Isolated venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Copy requirements and prebuilt wheels
COPY requirements.txt .
COPY --from=builder /wheels /wheels

# OFFLINE install strictly from /wheels (no network, no source builds)
RUN python -m pip install \
      --no-index --find-links=/wheels \
      --only-binary=:all: \
      -r requirements.txt \
 && rm -rf /wheels

# App code
COPY --chown=${APP_USER}:${APP_USER} app /app
# COPY --chown=${APP_USER}:${APP_USER} gunicorn.conf.py /app/gunicorn.conf.py  # if needed

EXPOSE 5000

USER ${APP_UID}:${APP_UID}

ENV GUNICORN_CMD_ARGS="--bind=0.0.0.0:5000 --workers=2 --threads=2 --worker-tmp-dir=/tmp/app --access-logfile=- --error-logfile=- --graceful-timeout=30 --timeout=30"
CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
