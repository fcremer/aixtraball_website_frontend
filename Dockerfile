# ---- builder: baut Wheels isoliert ----
FROM python:3.14-slim-bookworm AS builder

# Sicherheits/Build-Basics
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Nur, falls native Wheels nötig sind (z. B. psycopg2, lxml, numpy …)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Nur die Requirements, damit Layer-Caching greift
COPY requirements.txt .

# Optional: strenge Pinning/Verifikation (setzt Hashes in requirements.txt voraus)
# RUN python -m pip install --upgrade pip pip-tools \
#  && python -m pip install --require-hashes -r requirements.txt -t /wheels
# Alternativ (ohne Hash-Zwang), erzeugt Wheels:
RUN python -m pip install --upgrade pip wheel \
 && python -m pip wheel --no-deps --wheel-dir /wheels -r requirements.txt


# ---- runtime: schlank, Non-Root, nur das Nötigste ----
FROM python:3.14-slim-bookworm AS runtime

# Minimale OS-Basis aktuell halten und Root-FS klein halten
# (ca-certificates ist oft nötig für TLS-Zugriffe)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Sicherheitsrelevante Python/Runtime-Defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UMASK=027

# App-Verzeichnisse und Non-Root-User
ARG APP_USER=appuser
ARG APP_UID=10001
WORKDIR /app
RUN useradd -u ${APP_UID} -m -s /usr/sbin/nologin ${APP_USER} \
 && mkdir -p /app /opt/venv /var/log/app /tmp/app \
 && chown -R ${APP_USER}:${APP_USER} /app /opt/venv /var/log/app /tmp/app

# Isoliertes venv statt System-Python
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Wheels aus dem Builder übernehmen und installieren
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-compile /wheels/* \
 && rm -rf /wheels

# App-Code zuletzt (bessere Cache-Nutzung) und gleich ownership setzen
COPY --chown=${APP_USER}:${APP_USER} app /app
# Falls du gunicorn.conf.py außerhalb von /app hältst, separat kopieren:
# COPY --chown=${APP_USER}:${APP_USER} gunicorn.conf.py /app/gunicorn.conf.py

# Netzwerkoberfläche und Healthcheck
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=2).read()" || exit 1

# Non-Root ausführen
USER ${APP_UID}:${APP_UID}

# Gunicorn: tmp-Dir setzen (wichtig bei read-only rootfs), Logs auf stdout/stderr
ENV GUNICORN_CMD_ARGS="--bind=0.0.0.0:5000 --workers=2 --threads=2 --worker-tmp-dir=/tmp/app --access-logfile=- --error-logfile=- --graceful-timeout=30 --timeout=30"
CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
