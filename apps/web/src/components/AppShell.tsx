"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { logout, me } from "@/lib/api/auth";
import type { User } from "@/lib/api/types";

type NavIconName = "documents" | "upload" | "etalons" | "benchmarks" | "settings" | "admin";

type NavItem = {
  href: string;
  icon: NavIconName;
  label: string;
  requiresAdmin?: boolean;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/documents", icon: "documents", label: "Documents" },
  { href: "/documents/upload", icon: "upload", label: "Upload" },
  { href: "/etalons", icon: "etalons", label: "Etalons" },
  { href: "/benchmarks", icon: "benchmarks", label: "Benchmarks" },
  { href: "/settings", icon: "settings", label: "Settings" },
  { href: "/admin/users", icon: "admin", label: "Admin", requiresAdmin: true },
];

const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV?.trim() || "MVP";

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
  const activeItem = visibleNav.find((item) => isActivePath(pathname, item.href)) ?? visibleNav[0];

  if (!user) {
    return (
      <main className="app-loading muted">
        <div className="panel pulse">Loading workspace...</div>
      </main>
    );
  }

  return (
    <div className="shell app-shell">
      <aside className="sidebar" aria-label="Gate Challenger navigation">
        <Link className="brand" href="/documents" aria-label="Gate Challenger documents">
          <span className="brand-mark" aria-hidden="true">
            GC
          </span>
          <span>
            <span className="brand-title">Gate Challenger</span>
            <span className="brand-subtitle">Defense review</span>
          </span>
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
                <span className="nav-icon" aria-hidden="true">
                  <NavIcon name={item.icon} />
                </span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="env-card" aria-label={`${APP_ENV} environment`}>
            <div className="env-label">{APP_ENV} environment</div>
            <p className="env-copy">Traceable analysis workspace</p>
          </div>
        </div>
      </aside>

      <div className="content-shell">
        <header className="topbar">
          <div className="topbar-title">
            <span className="topbar-eyebrow">Workspace</span>
            <span className="topbar-heading">{activeItem?.label ?? "Gate Challenger"}</span>
          </div>

          <div className="topbar-actions">
            <span className="mvp-chip">{APP_ENV}</span>
            <span className="role-chip">{user.role}</span>
            <span className="user-chip" title={user.login}>
              {user.display_name || user.login}
            </span>
            <button className="secondary" type="button" onClick={handleLogout}>
              Log out
            </button>
          </div>
        </header>

        {error ? <div className="shell-alert panel error">{error}</div> : null}
        <div className="content-scroll">{children}</div>
      </div>
    </div>
  );
}

function isActivePath(pathname: string, href: string) {
  if (href === "/documents") {
    return pathname === href || (pathname.startsWith("/documents/") && !pathname.startsWith("/documents/upload"));
  }

  if (href === "/admin/users") {
    return pathname.startsWith("/admin");
  }

  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavIcon({ name }: { name: NavIconName }) {
  switch (name) {
    case "documents":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M7 3h7l4 4v14H7z" />
          <path d="M14 3v5h5" />
          <path d="M9 13h6" />
          <path d="M9 17h5" />
        </svg>
      );
    case "upload":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 16V4" />
          <path d="m7 9 5-5 5 5" />
          <path d="M5 17v3h14v-3" />
        </svg>
      );
    case "etalons":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 4h12v16H6z" />
          <path d="M9 8h6" />
          <path d="M9 12h6" />
          <path d="M9 16h3" />
        </svg>
      );
    case "benchmarks":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 20V8" />
          <path d="M12 20V4" />
          <path d="M19 20v-9" />
          <path d="M3 20h18" />
        </svg>
      );
    case "settings":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z" />
          <path d="M4 12h2" />
          <path d="M18 12h2" />
          <path d="M12 4v2" />
          <path d="M12 18v2" />
        </svg>
      );
    case "admin":
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z" />
          <path d="M9 12l2 2 4-5" />
        </svg>
      );
  }
}
