FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# deps first for layer caching
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

# Cloud Run injects $PORT (8080); default 8090 for local docker-compose.
# Set RUN_MIGRATIONS=1 (prod) to apply Alembic migrations before serving.
EXPOSE 8090
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = \"1\" ]; then alembic upgrade head; fi; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8090}"]
