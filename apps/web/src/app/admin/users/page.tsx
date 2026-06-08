"use client";

import { FormEvent, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { createUser, deleteUser, listUsers, patchUser, resetPassword } from "@/lib/api/admin-users";
import { me } from "@/lib/api/auth";
import type { Role, User, UserStatus } from "@/lib/api/types";

const roles: Role[] = ["user", "annotator", "admin"];
const statuses: UserStatus[] = ["active", "blocked"];

export default function AdminUsersPage() {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [deletingId, setDeletingId] = useState("");
  const [loginName, setLoginName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [status, setStatus] = useState<UserStatus>("active");

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
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load users"));
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
        <div className="toolbar">
          <div>
            <h1>Users</h1>
            <p className="muted">Admin account management</p>
          </div>
        </div>

        <form className="panel stack" onSubmit={submit}>
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
                    {item}
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

        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Login</th>
                <th>Name</th>
                <th>Role</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.login}</td>
                  <td>{user.display_name}</td>
                  <td>
                    <select
                      value={user.role}
                      onChange={(event) => updateUser(user, event.target.value as Role, user.status)}
                    >
                      {roles.map((item) => (
                        <option key={item} value={item}>
                          {item}
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
                  <td className="button-row">
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
        </section>
      </main>
    </AppShell>
  );
}
