ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY contracts ./contracts

RUN pip install --no-cache-dir -e ./apps/api \
    && pip install --no-cache-dir -e ./apps/worker

WORKDIR /app/apps/worker

CMD ["python", "worker.py"]
