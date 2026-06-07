# Gate Challenger Service

MVP platform for reproducible analysis of investment and product defense documents.

## Repository Layout

- `apps/api` - FastAPI backend, SQLAlchemy models, Alembic migrations, auth, RBAC.
- `apps/worker` - background jobs for parsing, analysis, and benchmarks.
- `apps/web` - Next.js frontend.
- `contracts/schemas` - shared JSON schemas for analysis and benchmark contracts.
- `infra` - local Docker Compose stack.

## Local Stack

Copy the environment template and set a real secret:

```bash
cp .env.example .env
```

Start the MVP stack:

```bash
docker compose -f infra/docker-compose.yml up --build
```

The Compose defaults use the public `mirror.gcr.io` mirror for official
PostgreSQL, Redis, Python, and Node images because Docker Hub DNS can be flaky
in local Codex environments. Override `POSTGRES_IMAGE`, `REDIS_IMAGE`,
`PYTHON_BASE_IMAGE`, or `NODE_BASE_IMAGE` in `.env` if your environment should
pull directly from Docker Hub or an internal registry.

Run migrations from the API container or a local API environment:

```bash
cd apps/api
alembic upgrade head
```

Create the first admin account:

```bash
python -m app.seeds.admin --login admin --password 'change-me-now'
```

Useful checks:

```bash
pytest apps/api/tests -q
pytest apps/worker/tests -q
npm --prefix apps/web run test
docker compose -f infra/docker-compose.yml config
```
