ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}
ARG INSTALL_DEV=false

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
COPY apps/api/tests ./apps/api/tests
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/alembic ./alembic
COPY contracts ./contracts

RUN if [ "$INSTALL_DEV" = "true" ]; then \
      pip install --no-cache-dir -e ".[dev]"; \
    else \
      pip install --no-cache-dir -e .; \
    fi

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
