"use client";

import { FormEvent, useEffect, useState } from "react";

import { login, me } from "@/lib/api/auth";
import { appPath } from "@/lib/routing";

export default function LoginPage() {
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    me()
      .then((user) => {
        if (process.env.NEXT_PUBLIC_EXTERNAL_ACCESS_DISABLED !== "true" || user.role === "admin") {
          window.location.replace(appPath("/documents"));
        }
      })
      .catch(() => {});
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const result = await login(loginName, password);
      window.location.replace(appPath(
        process.env.NEXT_PUBLIC_EXTERNAL_ACCESS_DISABLED === "true" && result.user.role !== "admin"
          ? "/transition"
          : "/documents",
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="login-shell">
      <form className="panel login-panel stack" onSubmit={submit}>
        <div>
          <h1>Gate Challenger</h1>
          <p className="muted">Sign in</p>
        </div>
        <label>
          Login
          <input autoComplete="username" value={loginName} onChange={(event) => setLoginName(event.target.value)} />
        </label>
        <label>
          Password
          <input
            autoComplete="current-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error ? <div className="error">{error}</div> : null}
        <button disabled={pending || !loginName || !password} type="submit">
          Sign in
        </button>
      </form>
    </main>
  );
}
