"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { listAdminAnalyses, type AdminAnalysis, type RunStatus } from "@/lib/api/admin";
import type { Provider } from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

const providers: (Provider | "")[] = ["", "openai_compatible", "anthropic_compatible", "hermes"];
const statuses: (RunStatus | "")[] = ["", "queued", "running", "completed", "failed", "cancelled"];

export default function AdminAnalysesPage() {
  const [analyses, setAnalyses] = useState<AdminAnalysis[]>([]);
  const [provider, setProvider] = useState<Provider | "">("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [model, setModel] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const response = await listAdminAnalyses({ provider, status, model });
    setAnalyses(response.analyses);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin analyses"))
      .finally(() => setLoading(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin analyses"));
  }

  return (
    <AppShell>
      <main className="main stack">
        <AdminTabs />
        <div className="toolbar">
          <div>
            <h1>Admin Analyses</h1>
            <p className="muted">Analysis run metadata across users, providers, models, and skills.</p>
          </div>
          <span className="badge info">{analyses.length} runs</span>
        </div>
        <form className="panel stack" onSubmit={submit}>
          <h2>Filters</h2>
          <div className="form-grid">
            <label>
              Provider
              <select value={provider} onChange={(event) => setProvider(event.target.value as Provider | "")}>
                {providers.map((item) => (
                  <option key={item || "all"} value={item}>
                    {item ? formatLabel(item) : "All"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Status
              <select value={status} onChange={(event) => setStatus(event.target.value as RunStatus | "")}>
                {statuses.map((item) => (
                  <option key={item || "all"} value={item}>
                    {item ? formatLabel(item) : "All"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <input value={model} onChange={(event) => setModel(event.target.value)} />
            </label>
            <label>
              &nbsp;
              <button type="submit">Apply filters</button>
            </label>
          </div>
        </form>
        {error ? <section className="panel error">{error}</section> : null}
        <section className="panel stack">
          <h2>Analysis Runs</h2>
          {loading ? <div className="muted">Loading analyses...</div> : null}
          {!loading && analyses.length === 0 ? <div className="muted">No analyses match the current filters.</div> : null}
          {!loading && analyses.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>User</th>
                    <th>Provider</th>
                    <th>Skill</th>
                    <th>Status</th>
                    <th>Verdict</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {analyses.map((item) => (
                    <tr key={item.id}>
                      <td>{item.document_title}</td>
                      <td>{item.user_login}</td>
                      <td>
                        {formatLabel(item.provider)}
                        <div className="muted small">{item.model}</div>
                      </td>
                      <td>
                        {item.skill_name}
                        <div className="muted small">{item.skill_version}</div>
                      </td>
                      <td>
                        <StatusBadge status={item.status} />
                      </td>
                      <td>
                        <VerdictBadge verdict={item.verdict} />
                      </td>
                      <td>{formatDate(item.created_at)}</td>
                      <td>
                        <Link className="secondary-link" href={`/analyses/${item.id}`}>
                          Open
                        </Link>
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

function VerdictBadge({ verdict }: { verdict: string | null }) {
  const tone = verdict === "approve" ? "ok" : verdict === "reject" ? "danger" : "info";
  return <span className={`badge ${tone}`}>{formatLabel(verdict)}</span>;
}
