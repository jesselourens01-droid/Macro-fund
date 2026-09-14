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

# Install the package (all dependencies - the platform spec's stack, including
# cvxpy/xgboost/lightgbm for portfolio construction and the ML research layer)
RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY config ./config
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY scripts ./scripts
COPY dashboards ./dashboards
COPY tests ./tests

# Run as a non-root user - defense in depth, not a substitute for the app-level
# safeguards (live trading disabled by default, optional API-key auth) that
# actually gate what this container can do.
RUN useradd --create-home --uid 1000 jlmacro && chown -R jlmacro:jlmacro /app
USER jlmacro

EXPOSE 8000 8501

CMD ["uvicorn", "jlmacro.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
