"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { createUser, deleteUser, getSuperuserOwnerScope, listUsers, patchUser, putSuperuserOwnerScope, resetPassword } from "@/lib/api/admin-users";
import { me } from "@/lib/api/auth";
import { grantDocumentAccess, type DocumentAccessGrantResult } from "@/lib/api/document-access";
import type { Role, User, UserStatus } from "@/lib/api/types";

const roles: Role[] = ["user", "superuser", "annotator", "admin"];
const statuses: UserStatus[] = ["active", "blocked"];

export default function AdminUsersPage() {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [deletingId, setDeletingId] = useState("");
  const [loginName, setLoginName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [status, setStatus] = useState<UserStatus>("active");
  const [accessLines, setAccessLines] = useState("");
  const [accessPending, setAccessPending] = useState(false);
  const [accessError, setAccessError] = useState("");
  const [accessResult, setAccessResult] = useState<DocumentAccessGrantResult | null>(null);
  const [scopeUser, setScopeUser] = useState<User | null>(null);
  const [scopeOwnerIds, setScopeOwnerIds] = useState<string[]>([]);
  const [scopeFilter, setScopeFilter] = useState("");
  const [scopePending, setScopePending] = useState(false);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeLoaded, setScopeLoaded] = useState(false);
  const [scopeError, setScopeError] = useState("");
  const [scopeSaved, setScopeSaved] = useState(false);
  const scopeRequestRef = useRef(0);

  async function refresh() {
    const user = await me();
    setCurrentUser(user);
    if (user.role !== "admin") {
      return;
    }
    const response = await listUsers();
    setUsers(response.users);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load users"))
      .finally(() => setLoading(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await createUser({
        login: loginName,
        display_name: displayName,
        password,
        role,
        status,
      });
      setLoginName("");
      setDisplayName("");
      setPassword("");
      setRole("user");
      setStatus("active");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setPending(false);
    }
  }

  async function updateUser(user: User, nextRole: Role, nextStatus: UserStatus) {
    setError("");
    try {
      await patchUser(user.id, { role: nextRole, status: nextStatus });
      if (scopeUser?.id === user.id && nextRole !== "superuser") {
        scopeRequestRef.current += 1;
        setScopeUser(null);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update user");
    }
  }

  async function handleResetPassword(user: User) {
    const nextPassword = window.prompt(`New password for ${user.login}`);
    if (!nextPassword) {
      return;
    }
    setError("");
    try {
      await resetPassword(user.id, nextPassword);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password");
    }
  }

  async function handleDeleteUser(user: User) {
    if (!window.confirm(`Delete user "${user.login}"?`)) {
      return;
    }
    setDeletingId(user.id);
    setError("");
    try {
      await deleteUser(user.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete user");
    } finally {
      setDeletingId("");
    }
  }

  async function editOwnerScope(user: User) {
    const requestId = ++scopeRequestRef.current;
    setScopeUser(user);
    setScopeOwnerIds([]);
    setScopeError("");
    setScopeSaved(false);
    setScopePending(false);
    setScopeLoading(true);
    setScopeLoaded(false);
    try {
      const scope = await getSuperuserOwnerScope(user.id);
      if (scopeRequestRef.current === requestId) {
        setScopeOwnerIds(scope.owner_ids);
        setScopeLoaded(true);
      }
    } catch (err) {
      if (scopeRequestRef.current === requestId) {
        setScopeError(err instanceof Error ? err.message : "Failed to load owner scope");
      }
    } finally {
      if (scopeRequestRef.current === requestId) setScopeLoading(false);
    }
  }

  async function saveOwnerScope() {
    if (!scopeUser || !scopeLoaded) return;
    const requestId = scopeRequestRef.current;
    setScopePending(true);
    setScopeError("");
    setScopeSaved(false);
    try {
      const scope = await putSuperuserOwnerScope(scopeUser.id, scopeOwnerIds);
      if (scopeRequestRef.current === requestId) {
        setScopeOwnerIds(scope.owner_ids);
        setScopeSaved(true);
      }
    } catch (err) {
      if (scopeRequestRef.current === requestId) {
        setScopeError(err instanceof Error ? err.message : "Failed to save owner scope");
      }
    } finally {
      if (scopeRequestRef.current === requestId) setScopePending(false);
    }
  }

  async function submitAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAccessError("");
    setAccessResult(null);
    setAccessPending(true);
    try {
      const items = accessLines.trim().split("\n").map((line) => {
        const match = /^([^\s]+)\s+(.+)$/.exec(line.trim());
        if (!match) {
          throw new Error("Use one analysis ID and comma-separated logins per line");
        }
        const analysis_id = match[1];
        const logins = match[2].split(",").map((login) => login.trim()).filter(Boolean);
        if (!/^[0-9a-f-]{36}$/i.test(analysis_id) || logins.length === 0) {
          throw new Error("Use one analysis ID and comma-separated logins per line");
        }
        return { analysis_id, logins };
      });
      setAccessResult(await grantDocumentAccess(items));
    } catch (err) {
      setAccessError(err instanceof Error ? err.message : "Failed to grant document access");
    } finally {
      setAccessPending(false);
    }
  }

  if (currentUser && currentUser.role !== "admin") {
    return (
      <AppShell>
        <main className="main">
          <section className="panel error">Access denied</section>
        </main>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <main className="main stack">
        <AdminTabs />
        <div className="toolbar">
          <div>
            <h1>Users</h1>
            <p className="muted">Admin account creation, role changes, resets, and deletion.</p>
          </div>
          <span className="badge info">{users.length} users</span>
        </div>

        <form className="panel stack" onSubmit={submit}>
          <div>
            <h2>Create User</h2>
            <p className="muted">Provision an account with its initial role and status.</p>
          </div>
          <div className="form-grid">
            <label>
              Login
              <input value={loginName} onChange={(event) => setLoginName(event.target.value)} />
            </label>
            <label>
              Display name
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
            <label>
              Initial password
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
            <label>
              Role
              <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
                {roles.map((item) => (
                  <option key={item} value={item}>
                    {item === "superuser" ? "SuperUser" : item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Status
              <select value={status} onChange={(event) => setStatus(event.target.value as UserStatus)}>
                {statuses.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {error ? <div className="error">{error}</div> : null}
          <div>
            <button disabled={pending || !loginName || !displayName || password.length < 8} type="submit">
              Create user
            </button>
          </div>
        </form>

        <form className="panel stack" onSubmit={submitAccess}>
          <h2>Share analysis results</h2>
          <label>
            Analysis ID and user logins, one case per line
            <textarea
              rows={5}
              value={accessLines}
              onChange={(event) => setAccessLines(event.target.value)}
              placeholder="analysis-uuid login1,login2"
            />
          </label>
          <div><button disabled={accessPending || !accessLines.trim()} type="submit">Grant read access</button></div>
          {accessError ? <div className="error">{accessError}</div> : null}
          {accessResult ? <p className="muted">{accessResult.analyses} analyses; {accessResult.grants_created} new grants; {accessResult.grants_existing} existing.</p> : null}
        </form>

        <section className="panel stack">
          <div>
            <h2>User Directory</h2>
            <p className="muted">Identity, access role, and account state.</p>
          </div>
          {loading ? <div className="muted">Loading users...</div> : null}
          {!loading && users.length === 0 ? <div className="muted">No users found.</div> : null}
          {!loading && users.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Login</th>
                    <th>Name</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Current status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.login}</strong>
                        <div className="muted small">{user.id}</div>
                      </td>
                      <td>{user.display_name}</td>
                      <td>
                        <select
                          value={user.role}
                          onChange={(event) => updateUser(user, event.target.value as Role, user.status)}
                        >
                          {roles.map((item) => (
                            <option key={item} value={item}>
                              {item === "superuser" ? "SuperUser" : item}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          value={user.status}
                          onChange={(event) => updateUser(user, user.role, event.target.value as UserStatus)}
                        >
                          {statuses.map((item) => (
                            <option key={item} value={item}>
                              {item}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <StatusBadge status={user.status} />
                      </td>
                      <td className="button-row">
                        {user.role === "superuser" ? <button className="secondary" type="button" onClick={() => editOwnerScope(user)}>
                          Owners
                        </button> : null}
                        <button className="secondary" type="button" onClick={() => handleResetPassword(user)}>
                          Reset password
                        </button>
                        <button
                          className="danger"
                          disabled={deletingId === user.id || user.id === currentUser?.id}
                          type="button"
                          onClick={() => handleDeleteUser(user)}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>

        {scopeUser ? <section className="panel stack" aria-label={`Owner scope for ${scopeUser.login}`}>
          <div className="toolbar">
            <div>
              <h2>Owners visible to {scopeUser.login}</h2>
              <p className="muted">Existing and future cases owned by selected users, including their analyses.</p>
            </div>
            <button className="secondary" type="button" onClick={() => { scopeRequestRef.current += 1; setScopeUser(null); }}>Close</button>
          </div>
          <label>
            Find owner
            <input value={scopeFilter} onChange={(event) => setScopeFilter(event.target.value)} placeholder="Login or name" />
          </label>
          {scopeLoading ? <p className="muted">Loading owners...</p> : null}
          {!scopeLoading ? <div style={{ maxHeight: 280, overflowY: "auto" }}>
            {users.filter((candidate) => candidate.id !== scopeUser.id && (candidate.status === "active" || scopeOwnerIds.includes(candidate.id)) &&
              `${candidate.login} ${candidate.display_name}`.toLowerCase().includes(scopeFilter.toLowerCase())).map((candidate) => (
                <label key={candidate.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0" }}>
                  <input
                    type="checkbox"
                    checked={scopeOwnerIds.includes(candidate.id)}
                    disabled={scopePending}
                    onChange={(event) => {
                      setScopeSaved(false);
                      setScopeOwnerIds((current) => event.target.checked
                        ? [...current, candidate.id]
                        : current.filter((id) => id !== candidate.id));
                    }}
                  />
                  {candidate.login} <span className="muted">{candidate.display_name}{candidate.status !== "active" ? ` (${candidate.status})` : ""}</span>
                </label>
              ))}
          </div> : null}
          <div className="button-row">
            <button disabled={!scopeLoaded || scopeLoading || scopePending} type="button" onClick={saveOwnerScope}>
              {scopePending ? "Saving..." : `Save ${scopeOwnerIds.length} owners`}
            </button>
            {scopeSaved ? <span className="muted">Saved</span> : null}
          </div>
          {scopeError ? <p className="error">{scopeError}</p> : null}
        </section> : null}
      </main>
    </AppShell>
  );
}
