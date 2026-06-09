"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { deleteAdminEtalon, listAdminEtalons, type AdminEtalon, type EtalonStatus } from "@/lib/api/admin";
import { archiveEtalon } from "@/lib/api/etalons";
import { formatDate, formatLabel } from "@/lib/format";

const statuses: (EtalonStatus | "")[] = ["", "draft", "active", "archived", "deleted"];

export default function AdminEtalonsPage() {
  const [etalons, setEtalons] = useState<AdminEtalon[]>([]);
  const [status, setStatus] = useState<EtalonStatus | "">("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [archivingId, setArchivingId] = useState("");
  const [deletingId, setDeletingId] = useState("");

  async function refresh() {
    const response = await listAdminEtalons({ status });
    setEtalons(response.etalons);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin etalons"))
      .finally(() => setLoading(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin etalons"));
  }

  async function handleDelete(etalon: AdminEtalon) {
    if (!window.confirm(`Delete etalon for "${etalon.document_title}"?`)) {
      return;
    }
    setDeletingId(etalon.id);
    setError("");
    try {
      await deleteAdminEtalon(etalon.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete etalon");
    } finally {
      setDeletingId("");
    }
  }

  async function handleArchive(etalon: AdminEtalon) {
    setArchivingId(etalon.id);
    setError("");
    try {
      await archiveEtalon(etalon.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive etalon");
    } finally {
      setArchivingId("");
    }
  }

  return (
    <AppShell>
      <main className="main stack">
        <AdminTabs />
        <div className="toolbar">
          <div>
            <h1>Admin Etalons</h1>
            <p className="muted">Reference records, verdicts, layer counts, and lifecycle controls.</p>
          </div>
          <span className="badge info">{etalons.length} etalons</span>
        </div>
        <form className="panel stack" onSubmit={submit}>
          <h2>Filters</h2>
          <div className="form-grid">
            <label>
              Status
              <select value={status} onChange={(event) => setStatus(event.target.value as EtalonStatus | "")}>
                {statuses.map((item) => (
                  <option key={item || "all"} value={item}>
                    {item ? formatLabel(item) : "All"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              &nbsp;
              <button type="submit">Apply filters</button>
            </label>
          </div>
        </form>
        {error ? <section className="panel error">{error}</section> : null}
        <section className="panel stack">
          <h2>Etalons</h2>
          {loading ? <div className="muted">Loading etalons...</div> : null}
          {!loading && etalons.length === 0 ? <div className="muted">No etalons match the current filters.</div> : null}
          {!loading && etalons.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Author</th>
                    <th>Type</th>
                    <th>Verdict</th>
                    <th>Layers</th>
                    <th>Status</th>
                    <th>Updated</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {etalons.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.document_title}</strong>
                        <div className="muted small">{item.id}</div>
                      </td>
                      <td>{item.author_login}</td>
                      <td>{formatLabel(item.document_type)}</td>
                      <td>
                        <VerdictBadge verdict={item.expected_verdict} />
                      </td>
                      <td>
                        <span className="badge">L1 {item.layer_1_count}</span>{" "}
                        <span className="badge">L2 {item.layer_2_count}</span>
                      </td>
                      <td>
                        <StatusBadge status={item.status} />
                      </td>
                      <td>{formatDate(item.updated_at)}</td>
                      <td className="button-row">
                        <Link className="secondary-link" href={`/etalons/${item.id}`}>
                          Open
                        </Link>
                        <button
                          className="danger"
                          disabled={archivingId === item.id || item.status === "archived" || item.status === "deleted"}
                          type="button"
                          onClick={() => handleArchive(item)}
                        >
                          Archive
                        </button>
                        <button
                          className="danger"
                          disabled={deletingId === item.id || item.status === "deleted"}
                          type="button"
                          onClick={() => handleDelete(item)}
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
      </main>
    </AppShell>
  );
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const tone = verdict === "approve" ? "ok" : verdict === "reject" ? "danger" : "info";
  return <span className={`badge ${tone}`}>{formatLabel(verdict)}</span>;
}
