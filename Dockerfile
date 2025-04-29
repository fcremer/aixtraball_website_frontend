FROM python:3.12-slim
WORKDIR /app

COPY app /app
COPY requirements.txt .

# hier einfach den Pfad RELATIV lassen
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000
CMD ["python", "/app/app.py"]