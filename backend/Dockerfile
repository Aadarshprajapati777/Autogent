FROM python:3.13-slim AS backend

WORKDIR /app

# System deps for psycopg, cryptography, weasyprint
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Run migrations on startup, then start uvicorn with multiple workers
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --no-access-log"]
