"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { deleteAdminEtalon, listAdminEtalons, type AdminEtalon, type EtalonStatus } from "@/lib/api/admin";
import { formatDate, formatLabel } from "@/lib/format";

const statuses: (EtalonStatus | "")[] = ["", "draft", "active", "archived", "deleted"];

export default function AdminEtalonsPage() {
  const [etalons, setEtalons] = useState<AdminEtalon[]>([]);
  const [status, setStatus] = useState<EtalonStatus | "">("");
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState("");

  async function refresh() {
    const response = await listAdminEtalons({ status });
    setEtalons(response.etalons);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin etalons"));
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

  return (
    <AppShell>
      <main className="main stack">
        <AdminTabs />
        <h1>Admin Etalons</h1>
        <form className="panel form-grid" onSubmit={submit}>
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
        </form>
        {error ? <div className="error">{error}</div> : null}
        <section className="panel table-wrap">
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
                  <td>{item.document_title}</td>
                  <td>{item.author_login}</td>
                  <td>{formatLabel(item.document_type)}</td>
                  <td>{formatLabel(item.expected_verdict)}</td>
                  <td>{item.layer_1_count} / {item.layer_2_count}</td>
                  <td>{formatLabel(item.status)}</td>
                  <td>{formatDate(item.updated_at)}</td>
                  <td className="button-row">
                    <Link className="secondary-link" href={`/etalons/${item.id}`}>
                      Open
                    </Link>
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
        </section>
      </main>
    </AppShell>
  );
}
