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
docker compose --env-file .env -f infra/docker-compose.yml up --build
```

The Compose defaults use the public `mirror.gcr.io` mirror for official
PostgreSQL, Redis, Python, and Node images because Docker Hub DNS can be flaky
in local Codex environments. Override `POSTGRES_IMAGE`, `REDIS_IMAGE`,
`PYTHON_BASE_IMAGE`, or `NODE_BASE_IMAGE` in `.env` if your environment should
pull directly from Docker Hub or an internal registry.

For temporary local provider egress through a SOCKS5 proxy, set
`OUTBOUND_PROXY_URL=socks5h://user:password@host:port` in the untracked `.env`.
The API and worker containers keep `postgres`, `redis`, and other local Compose
hosts in `NO_PROXY` so internal service traffic stays direct.
Docker image builds use separate optional `BUILD_HTTP_PROXY`,
`BUILD_HTTPS_PROXY`, and `BUILD_ALL_PROXY` values. Do not reuse a SOCKS
`OUTBOUND_PROXY_URL` as a build proxy because `pip` cannot bootstrap SOCKS
support before dependencies are installed.

Run migrations from the API container or a local API environment:

```bash
cd apps/api
alembic upgrade head
```

Create the first admin account:

```bash
python -m app.seeds.admin --login admin --password 'change-me-now'
```

Seed baseline skills:

```bash
python -m app.seeds.skills
```

Useful checks:

```bash
pytest apps/api/tests -q
pytest apps/worker/tests -q
npm --prefix apps/web run test
docker compose -f infra/docker-compose.yml config
```

Full MVP acceptance:

```bash
E2E_ADMIN_LOGIN=admin \
E2E_ADMIN_PASSWORD='change-me-now' \
make test
```

The e2e runner starts the built web app with `next start` on port `3000` when
`E2E_BASE_URL` is omitted. Set `E2E_BASE_URL` only when intentionally testing an
already running web server.
