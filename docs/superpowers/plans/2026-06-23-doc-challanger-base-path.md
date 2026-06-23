# Doc Challanger Base Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve Gate Challenger at `http://iseremenko.ru/doc-challanger/...` while preserving room for other projects under the same domain.

**Architecture:** Build the Next.js web app with a configurable `basePath`, set production to `/doc-challanger`, and route `/doc-challanger/api/*` through nginx to FastAPI with the prefix stripped. Keep local development root-based by default.

**Tech Stack:** Next.js, TypeScript, FastAPI, Docker Compose, nginx.

---

## Files

- Modify `apps/web/next.config.ts` to read `NEXT_PUBLIC_BASE_PATH`.
- Create `apps/web/src/lib/routing.ts` and `apps/web/src/lib/routing.test.ts` for imperative navigation paths.
- Modify client redirects in `apps/web/src/app/**` and `apps/web/src/components/AppShell.tsx`.
- Modify `apps/web/Dockerfile.prod` and `infra/docker-compose.prod.yml` to pass `NEXT_PUBLIC_BASE_PATH` at build time.
- Modify `infra/nginx.prod.conf` to route `/doc-challanger` and `/doc-challanger/api`.
- Update `.env.example` and `TASKS.md` with the deployment note.

## Tasks

### Task 1: Add Routing Helper

- [ ] Write tests for normalizing an empty base path, `/doc-challanger`, and stripping the base path from active nav paths.
- [ ] Implement `routing.ts`.
- [ ] Run the focused routing tests.

### Task 2: Wire Web Base Path

- [ ] Configure `next.config.ts` from `NEXT_PUBLIC_BASE_PATH`.
- [ ] Use `appPath()` for `window.location.href` and server `redirect()` calls.
- [ ] Keep `Link href` values unprefixed so Next.js can apply `basePath`.
- [ ] Run focused frontend tests.

### Task 3: Wire Production Proxy

- [ ] Add `/doc-challanger/api` proxy rules to FastAPI.
- [ ] Add `/doc-challanger` web proxy rules to Next.js.
- [ ] Redirect `/` to `/doc-challanger/login`.
- [ ] Validate Docker Compose config.

### Task 4: Verify And Deploy

- [ ] Run frontend tests and production build locally.
- [ ] Sync the release tree to `178.250.159.250`.
- [ ] Set production public URLs to `http://iseremenko.ru/doc-challanger/api` and `NEXT_PUBLIC_BASE_PATH=/doc-challanger`.
- [ ] Rebuild web and recreate edge.
- [ ] Verify server-local `/doc-challanger/login` and `/doc-challanger/api/health`.
