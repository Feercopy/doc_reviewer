"use client";

import { useEffect, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { listAdminSkills } from "@/lib/api/admin";
import type { SkillRecord } from "@/lib/api/skills";
import { formatLabel } from "@/lib/format";

export default function AdminSkillsPage() {
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listAdminSkills()
      .then((response) => setSkills(response.skills))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin skills"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <AppShell>
      <main className="main stack">
        <AdminTabs />
        <div className="toolbar">
          <div>
            <h1>Admin Skills</h1>
            <p className="muted">Versioned skill sources and result schema metadata.</p>
          </div>
          <span className="badge info">{skills.length} skills</span>
        </div>
        {error ? <section className="panel error">{error}</section> : null}
        <section className="panel stack">
          <h2>Skill Registry</h2>
          {loading ? <div className="muted">Loading skills...</div> : null}
          {!loading && skills.length === 0 ? <div className="muted">No skills found.</div> : null}
          {!loading && skills.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Schema</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {skills.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.name}</strong>
                        <div className="muted small">{item.id}</div>
                      </td>
                      <td>{formatLabel(item.skill_type)}</td>
                      <td>{item.version}</td>
                      <td>
                        <StatusBadge status={item.status} />
                      </td>
                      <td className="small">{item.result_schema_path}</td>
                      <td className="small">{item.source_snapshot.source_fingerprint ?? item.source_snapshot.source_type}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      </main>
    </AppShell>
  );
}
