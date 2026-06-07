"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { logout, me } from "@/lib/api/auth";
import type { User } from "@/lib/api/types";

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    me()
      .then(setUser)
      .catch(() => {
        window.location.href = "/login";
      });
  }, []);

  async function handleLogout() {
    setError("");
    try {
      await logout();
      window.location.href = "/login";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Logout failed");
    }
  }

  if (!user) {
    return <main className="main muted">Loading...</main>;
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">Gate Challenger</div>
        <nav className="nav">
          <Link href="/documents">Documents</Link>
          <Link href="/documents/upload">Upload</Link>
          <Link href="/etalons">Etalons</Link>
          <Link href="/benchmarks">Benchmarks</Link>
          <Link href="/settings">Settings</Link>
          {user.role === "admin" ? <Link href="/admin/users">Users</Link> : null}
        </nav>
        <button className="secondary" type="button" onClick={handleLogout}>
          Log out
        </button>
      </header>
      {error ? <main className="main error">{error}</main> : null}
      {children}
    </div>
  );
}
