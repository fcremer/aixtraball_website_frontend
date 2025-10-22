FROM python:3.14-bookworm
WORKDIR /app

COPY app /app
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000
# Production server
ENV PYTHONUNBUFFERED=1
CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
