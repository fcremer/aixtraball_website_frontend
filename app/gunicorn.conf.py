import os

bind = "0.0.0.0:5000"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("THREADS", "8"))
worker_class = "gthread"
keepalive = int(os.environ.get("KEEPALIVE", "5"))
timeout = int(os.environ.get("TIMEOUT", "60"))
graceful_timeout = int(os.environ.get("GRACEFUL_TIMEOUT", "30"))
worker_tmp_dir = "/dev/shm"

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOGLEVEL", "info")
