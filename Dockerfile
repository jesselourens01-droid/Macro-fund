FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps needed to build psycopg / scientific stack wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

# Install the package (core deps only for Phase 1 image; ml/opt extras added in later phases)
RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY config ./config
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY scripts ./scripts
COPY dashboards ./dashboards
COPY tests ./tests

EXPOSE 8000 8501

CMD ["uvicorn", "jlmacro.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
