"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { listAdminBenchmarks, type AdminBenchmark, type RunStatus } from "@/lib/api/admin";
import type { Provider } from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

const providers: (Provider | "")[] = ["", "openai_compatible", "anthropic_compatible", "hermes"];
const statuses: (RunStatus | "")[] = ["", "queued", "running", "completed", "failed", "cancelled"];

export default function AdminBenchmarksPage() {
  const [benchmarks, setBenchmarks] = useState<AdminBenchmark[]>([]);
  const [provider, setProvider] = useState<Provider | "">("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const response = await listAdminBenchmarks({ provider, status });
    setBenchmarks(response.benchmarks);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin benchmarks"))
      .finally(() => setLoading(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin benchmarks"));
  }

  return (
    <AppShell>
      <main className="main stack">
        <AdminTabs />
        <div className="toolbar">
          <div>
            <h1>Admin Benchmarks</h1>
            <p className="muted">Benchmark runs, providers, judge context, and score summaries.</p>
          </div>
          <span className="badge info">{benchmarks.length} runs</span>
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
              &nbsp;
              <button type="submit">Apply filters</button>
            </label>
          </div>
        </form>
        {error ? <section className="panel error">{error}</section> : null}
        <section className="panel stack">
          <h2>Benchmark Runs</h2>
          {loading ? <div className="muted">Loading benchmarks...</div> : null}
          {!loading && benchmarks.length === 0 ? <div className="muted">No benchmarks match the current filters.</div> : null}
          {!loading && benchmarks.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Started by</th>
                    <th>Provider</th>
                    <th>Skill</th>
                    <th>Status</th>
                    <th>Scores</th>
                    <th>Completed</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {benchmarks.map((item) => (
                    <tr key={item.id}>
                      <td>{item.name}</td>
                      <td>{item.started_by_login}</td>
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
                        <span className="badge">Overall {item.overall_score ?? "-"}</span>{" "}
                        <span className="badge">L1 {item.layer_1_score ?? "-"}</span>{" "}
                        <span className="badge">L2 {item.layer_2_score ?? "-"}</span>
                      </td>
                      <td>{formatDate(item.completed_at)}</td>
                      <td>
                        <Link className="secondary-link" href={`/benchmarks/${item.id}`}>
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
