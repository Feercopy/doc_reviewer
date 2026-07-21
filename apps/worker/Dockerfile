ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}
ARG INSTALL_DEV=false

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY contracts ./contracts

RUN if [ "$INSTALL_DEV" = "true" ]; then \
      pip install --no-cache-dir -e "./apps/api[dev]" \
      && pip install --no-cache-dir -e "./apps/worker[dev]"; \
    else \
      pip install --no-cache-dir -e ./apps/api \
      && pip install --no-cache-dir -e ./apps/worker; \
    fi

WORKDIR /app/apps/worker

CMD ["python", "worker.py"]
