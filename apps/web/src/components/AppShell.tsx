"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { logout, me } from "@/lib/api/auth";
import type { User } from "@/lib/api/types";

type NavItem = {
  href: string;
  label: string;
  requiresAdmin?: boolean;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/documents", label: "Documents" },
  { href: "/etalons", label: "Etalons" },
  { href: "/benchmarks", label: "Benchmarks" },
  { href: "/settings", label: "Settings" },
  { href: "/admin/users", label: "Admin", requiresAdmin: true },
];

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
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

  const visibleNav = useMemo(
    () => NAV_ITEMS.filter((item) => !item.requiresAdmin || user?.role === "admin"),
    [user?.role],
  );

  if (!user) {
    return (
      <main className="app-loading muted">
        <div className="panel pulse">Loading workspace...</div>
      </main>
    );
  }

  return (
    <div className="shell app-shell">
      <header className="app-header" aria-label="Gate Challenger navigation">
        <Link className="brand" href="/documents" aria-label="Gate Challenger documents">
          <span className="brand-mark" aria-hidden="true">
            G
          </span>
          <span className="brand-title">Gate Challenger</span>
        </Link>

        <nav className="nav sidebar-nav" aria-label="Primary">
          {visibleNav.map((item) => {
            const active = isActivePath(pathname, item.href);
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={`nav-link${active ? " active" : ""}`}
                href={item.href}
                key={item.href}
              >
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="topbar-actions">
          <span className="user-chip" title={user.login}>
            {user.display_name || user.login}
          </span>
          <button className="secondary" type="button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>

      <div className="content-shell">
        {error ? <div className="shell-alert panel error">{error}</div> : null}
        <div className="content-scroll">{children}</div>
      </div>
    </div>
  );
}

function isActivePath(pathname: string, href: string) {
  if (href === "/documents") {
    return pathname === href || pathname.startsWith("/documents/");
  }

  if (href === "/admin/users") {
    return pathname.startsWith("/admin");
  }

  return pathname === href || pathname.startsWith(`${href}/`);
}
