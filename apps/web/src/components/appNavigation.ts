import type { Role } from "@/lib/api/types";

export type NavItem = {
  href: string;
  label: string;
  requiresAdmin?: boolean;
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/documents", label: "Documents" },
  { href: "/admin/feedback", label: "Feedback", requiresAdmin: true },
  { href: "/etalons", label: "Etalons", requiresAdmin: true },
  { href: "/benchmarks", label: "Benchmarks", requiresAdmin: true },
  { href: "/settings", label: "Settings", requiresAdmin: true },
  { href: "/admin/users", label: "Admin", requiresAdmin: true },
];

export function getVisibleNavItems(role: Role | null | undefined): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.requiresAdmin || role === "admin");
}
