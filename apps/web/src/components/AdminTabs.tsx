"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const adminLinks = [
  ["/admin/users", "Users"],
  ["/admin/documents", "Documents"],
  ["/admin/analyses", "Analyses"],
  ["/admin/skills", "Skills"],
  ["/admin/etalons", "Etalons"],
  ["/admin/benchmarks", "Benchmarks"],
];

export function AdminTabs() {
  const pathname = usePathname();

  return (
    <nav className="admin-tabs" aria-label="Admin sections">
      {adminLinks.map(([href, label]) => (
        <Link className={pathname === href ? "button-link" : "secondary-link"} href={href} key={href}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
