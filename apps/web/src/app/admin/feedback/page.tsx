"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { listAdminFeedback, markAdminFeedbackProcessed, type AdminFeedback } from "@/lib/api/admin";
import { formatDate, formatLabel } from "@/lib/format";

export default function AdminFeedbackPage() {
  const [feedback, setFeedback] = useState<AdminFeedback[]>([]);
  const [model, setModel] = useState("");
  const [verdict, setVerdict] = useState("");
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const response = await listAdminFeedback({ model, verdict });
    setFeedback(response.feedback);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin feedback"))
      .finally(() => setLoading(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin feedback"));
  }

  async function markProcessed(feedbackId: string) {
    setPending(feedbackId);
    setError("");
    try {
      await markAdminFeedbackProcessed(feedbackId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to mark feedback processed");
    } finally {
      setPending("");
    }
  }

  return (
    <AppShell>
      <main className="main stack">
        <AdminTabs />
        <div className="toolbar">
          <div>
            <h1>Admin Feedback</h1>
            <p className="muted">User feedback tied to analyses, model choices, and verdict outcomes.</p>
          </div>
          <span className="badge info">{feedback.length} items</span>
        </div>
        <form className="panel stack" onSubmit={submit}>
          <h2>Filters</h2>
          <div className="form-grid">
            <label>
              Model
              <input value={model} onChange={(event) => setModel(event.target.value)} />
            </label>
            <label>
              Verdict
              <input value={verdict} onChange={(event) => setVerdict(event.target.value)} />
            </label>
            <label>
              &nbsp;
              <button type="submit">Apply filters</button>
            </label>
          </div>
        </form>
        {error ? <section className="panel error">{error}</section> : null}
        <section className="panel stack">
          <h2>Feedback</h2>
          {loading ? <div className="muted">Loading feedback...</div> : null}
          {!loading && feedback.length === 0 ? <div className="muted">No feedback matches the current filters.</div> : null}
          {!loading && feedback.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Document</th>
                    <th>Provider</th>
                    <th>Usefulness</th>
                    <th>Verdict</th>
                    <th>Comment</th>
                    <th>Processed</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {feedback.map((item) => (
                    <tr key={item.id}>
                      <td>{item.user_login}</td>
                      <td>{item.document_title}</td>
                      <td>
                        {formatLabel(item.provider)}
                        <div className="muted small">{item.model}</div>
                      </td>
                      <td>
                        <span className="badge">{formatLabel(item.usefulness)}</span>
                      </td>
                      <td>
                        <VerdictBadge verdict={item.analysis_verdict} />
                      </td>
                      <td>{item.comment ?? "-"}</td>
                      <td>
                        {item.processed_at ? <StatusBadge status="completed" /> : <StatusBadge status="queued" />}
                        <div className="muted small">{formatDate(item.processed_at)}</div>
                      </td>
                      <td className="button-row">
                        <Link className="secondary-link" href={`/analyses/${item.analysis_id}`}>
                          Open
                        </Link>
                        <button
                          className="secondary"
                          disabled={Boolean(item.processed_at) || pending === item.id}
                          type="button"
                          onClick={() => markProcessed(item.id)}
                        >
                          Mark processed
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

function VerdictBadge({ verdict }: { verdict: string | null }) {
  const tone = verdict === "approve" ? "ok" : verdict === "reject" ? "danger" : "info";
  return <span className={`badge ${tone}`}>{formatLabel(verdict)}</span>;
}
