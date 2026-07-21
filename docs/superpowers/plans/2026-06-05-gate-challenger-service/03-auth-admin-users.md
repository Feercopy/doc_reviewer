# Auth and Admin Users Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement login, session handling, password hashing, and admin-managed user accounts.

**Architecture:** Use cookie-based sessions for the browser client. Passwords are hashed with Argon2, current passwords are never exposed, and blocked users cannot log in or call authenticated APIs.

**Tech Stack:** FastAPI, passlib Argon2, signed HTTP-only cookies, SQLAlchemy, pytest, Next.js.

---

## Files

- Create: `apps/api/app/security/passwords.py`
- Create: `apps/api/app/security/sessions.py`
- Create: `apps/api/app/dependencies/auth.py`
- Create: `apps/api/app/routers/auth.py`
- Create: `apps/api/app/routers/admin_users.py`
- Create: `apps/api/app/schemas/auth.py`
- Create: `apps/api/app/schemas/users.py`
- Create: `apps/api/tests/test_auth.py`
- Create: `apps/api/tests/test_admin_users.py`
- Create: `apps/web/src/app/login/page.tsx`
- Create: `apps/web/src/app/admin/users/page.tsx`
- Create: `apps/web/src/lib/api/auth.ts`
- Create: `apps/web/src/lib/api/admin-users.ts`

## API Endpoints

```text
POST /auth/login
POST /auth/logout
GET /auth/me
GET /admin/users
POST /admin/users
PATCH /admin/users/{user_id}
POST /admin/users/{user_id}/reset-password
```

## Request and Response Contracts

### POST /auth/login

Request:

```json
{
  "login": "admin",
  "password": "secret"
}
```

Response:

```json
{
  "user": {
    "id": "uuid",
    "login": "admin",
    "display_name": "Administrator",
    "role": "admin",
    "status": "active"
  }
}
```

Failure cases:

- invalid login or password: `401`;
- blocked user: `403`;
- missing fields: `422`.

### POST /admin/users

Request:

```json
{
  "login": "analyst1",
  "display_name": "Analyst 1",
  "password": "initial-password",
  "role": "user",
  "status": "active"
}
```

Response omits password and password hash.

## Tasks

### Task 1: Password Hashing

- [ ] Implement `hash_password(password: str) -> str`.
- [ ] Implement `verify_password(password: str, password_hash: str) -> bool`.
- [ ] Add tests:
  - same plaintext verifies against hash;
  - wrong plaintext fails;
  - raw password is not present in hash string.

Acceptance:

- password tests pass;
- no route stores plaintext password.

### Task 2: Sessions and Current User Dependency

- [ ] Implement signed session cookie creation in `sessions.py`.
- [ ] Implement cookie parsing and validation in `dependencies/auth.py`.
- [ ] Add `require_current_user`.
- [ ] Add `require_admin`.
- [ ] Add tests for missing cookie, invalid cookie, valid user, blocked user, and non-admin access to admin route.

Acceptance:

- blocked users receive `403`;
- non-admin users cannot access admin user endpoints.

### Task 3: Auth Routes

- [ ] Implement `POST /auth/login`.
- [ ] Implement `POST /auth/logout`.
- [ ] Implement `GET /auth/me`.
- [ ] Add API tests for success and failure cases.

Acceptance:

- login sets HTTP-only cookie;
- logout clears cookie;
- `/auth/me` returns current user with no password fields.

### Task 4: Admin User Management

- [ ] Implement list users.
- [ ] Implement create user.
- [ ] Implement patch user role/status/display name.
- [ ] Implement reset password.
- [ ] Write audit log entries for create, update, block, unblock, role change, and password reset.

Acceptance:

- admin can create a user;
- admin cannot see current user password;
- reset password replaces hash and invalidates old password.

### Task 5: Frontend Login and Admin Users Page

- [ ] Build `/login` page with login and password fields.
- [ ] Redirect authenticated users from `/login` to `/documents`.
- [ ] Build `/admin/users` table with create user form, role selector, status selector, and password reset action.
- [ ] Hide admin navigation from non-admin users based on `/auth/me`.

Acceptance:

- user can log in from browser;
- admin can create user from browser;
- non-admin cannot open admin users page and receives an access-denied view.

## Verification

Run:

```bash
pytest apps/api/tests/test_auth.py apps/api/tests/test_admin_users.py -q
npm --prefix apps/web run test
```

Expected:

- auth and admin API tests pass;
- frontend form validation tests pass.

