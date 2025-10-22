# ============================================
#   Stage 1 – Builder
#   Baut alle Python-Wheels mit Compiler-Tools
# ============================================
FROM python:3.14-slim-bookworm AS builder

# Security-/Build-Defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build-Tools (werden später nicht ins Runtime-Image übernommen)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc g++ python3-dev pkg-config cmake \
 && rm -rf /var/lib/apt/lists/*

# Requirements vorab kopieren, damit Docker-Layer besser cachen
COPY requirements.txt .

# Pip & Wheel aktualisieren und Wheels bauen
RUN python -m pip install --upgrade pip wheel \
 && python -m pip wheel --no-deps --wheel-dir /wheels -r requirements.txt


# ============================================
#   Stage 2 – Runtime
#   Enthält nur die minimal nötige Laufzeit
# ============================================
FROM python:3.14-slim-bookworm AS runtime

# Minimal benötigte Pakete (TLS-Zertifikate etc.)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Security-orientierte Python-Defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UMASK=027

# Non-root Benutzer anlegen
ARG APP_USER=appuser
ARG APP_UID=10001
RUN useradd -u ${APP_UID} -m -s /usr/sbin/nologin ${APP_USER}

# Arbeitsverzeichnis und Berechtigungen
WORKDIR /app
RUN mkdir -p /opt/venv /var/log/app /tmp/app \
 && chown -R ${APP_USER}:${APP_USER} /app /opt/venv /var/log/app /tmp/app

# Virtuelle Umgebung (Isolierung)
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Wheels aus dem Builder übernehmen und installieren (nur .whl)
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-compile /wheels/*.whl \
 && rm -rf /wheels

# Applikation kopieren und Berechtigungen setzen
COPY --chown=${APP_USER}:${APP_USER} app /app
# Optional: falls gunicorn.conf.py separat liegt
# COPY --chown=${APP_USER}:${APP_USER} gunicorn.conf.py /app/gunicorn.conf.py

# Exposed Port und Healthcheck
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=2).read()" || exit 1

# Non-root User aktivieren
USER ${APP_UID}:${APP_UID}

# Gunicorn Startbefehl (sicher & reproduzierbar)
ENV GUNICORN_CMD_ARGS="--bind=0.0.0.0:5000 --workers=2 --threads=2 --worker-tmp-dir=/tmp/app --access-logfile=- --error-logfile=- --graceful-timeout=30 --timeout=30"
CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
