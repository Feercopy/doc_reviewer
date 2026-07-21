"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  listAdminFeedback,
  markAdminFeedbackProcessed,
  type AdminFeedback,
  type AdminFeedbackSummary,
} from "@/lib/api/admin";
import type { Provider } from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

const emptySummary: AdminFeedbackSummary = {
  total_count: 0,
  scored_count: 0,
  average_rating: null,
  usefulness_counts: { useful: 0, partially_useful: 0, useless: 0 },
  incorrect_verdict_count: 0,
  false_findings_count: 0,
  missed_findings_count: 0,
  benchmark_candidate_count: 0,
  unprocessed_count: 0,
  low_rating_count: 0,
  legacy_count: 0,
};

type ProcessedState = "all" | "processed" | "unprocessed" | "";

export default function AdminFeedbackPage() {
  const [feedback, setFeedback] = useState<AdminFeedback[]>([]);
  const [summary, setSummary] = useState<AdminFeedbackSummary>(emptySummary);
  const [provider, setProvider] = useState<Provider | "">("");
  const [model, setModel] = useState("");
  const [verdict, setVerdict] = useState("");
  const [skillId, setSkillId] = useState("");
  const [userId, setUserId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [processedState, setProcessedState] = useState<ProcessedState>("all");
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const response = await listAdminFeedback({
      provider,
      model,
      verdict,
      skill_id: skillId,
      user_id: userId,
      date_from: dateFrom,
      date_to: dateTo,
      processed_state: processedState,
    });
    setFeedback(response.feedback);
    setSummary(response.summary);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin feedback"))
      .finally(() => setLoading(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin feedback"))
      .finally(() => setLoading(false));
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

  const improvementSignals = useMemo(() => buildImprovementSignals(summary, feedback), [summary, feedback]);

  return (
    <AppShell>
      <main className="main stack feedback-dashboard">
        <AdminTabs />
        <div className="toolbar">
          <div>
            <h1>Feedback Dashboard</h1>
            <p className="muted">All-time user feedback tied to documents, model choices, and analysis runs.</p>
          </div>
          <span className="badge info">{summary.total_count} items</span>
        </div>

        <section className="metric-grid" aria-label="Feedback summary">
          <Metric label="Average rating" value={formatAverage(summary.average_rating)} note={`${summary.scored_count} scored feedback`} />
          <Metric
            label="Scored feedback"
            value={String(summary.scored_count)}
            note={`${summary.usefulness_counts.useful ?? 0} useful, ${summary.usefulness_counts.partially_useful ?? 0} partial, ${
              summary.usefulness_counts.useless ?? 0
            } useless`}
          />
          <Metric label="Incorrect verdicts" value={String(summary.incorrect_verdict_count)} note="users marked verdict wrong" />
          <Metric label="False findings" value={String(summary.false_findings_count)} note="invented or unsupported findings" />
          <Metric label="Missed findings" value={String(summary.missed_findings_count)} note="important issues users expected" />
          <Metric label="Unprocessed" value={String(summary.unprocessed_count)} note={`${summary.benchmark_candidate_count} benchmark candidates`} />
        </section>

        <form className="panel stack" onSubmit={submit}>
          <div className="table-toolbar">
            <div>
              <h2>Filters</h2>
              <p className="muted small">Default scope is all-time. Filters update both summary cards and row details.</p>
            </div>
            <button type="submit">Apply filters</button>
          </div>
          <div className="form-grid feedback-dashboard__filters">
            <label>
              Provider
              <select value={provider} onChange={(event) => setProvider(event.target.value as Provider | "")}>
                <option value="">Any provider</option>
                <option value="openai_compatible">OpenAI compatible</option>
                <option value="anthropic_compatible">Anthropic compatible</option>
                <option value="hermes">Hermes</option>
              </select>
            </label>
            <label>
              Model
              <input value={model} onChange={(event) => setModel(event.target.value)} />
            </label>
            <label>
              Verdict
              <input value={verdict} placeholder="need_evidence" onChange={(event) => setVerdict(event.target.value)} />
            </label>
            <label>
              Processed state
              <select value={processedState} onChange={(event) => setProcessedState(event.target.value as ProcessedState)}>
                <option value="all">All</option>
                <option value="unprocessed">Unprocessed</option>
                <option value="processed">Processed</option>
              </select>
            </label>
            <label>
              Date from
              <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
            </label>
            <label>
              Date to
              <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </label>
            <label>
              skill_id
              <input value={skillId} onChange={(event) => setSkillId(event.target.value)} />
            </label>
            <label>
              user_id
              <input value={userId} onChange={(event) => setUserId(event.target.value)} />
            </label>
          </div>
        </form>

        {error ? <section className="panel error">{error}</section> : null}

        <section className="panel stack">
          <div className="table-toolbar">
            <div>
              <h2>What to improve</h2>
              <p className="muted small">Signals are derived from low ratings, verdict corrections, and finding quality flags.</p>
            </div>
            <span className="badge warning">{summary.low_rating_count} low ratings</span>
          </div>
          <div className="feedback-dashboard__signals">
            {improvementSignals.map((signal) => (
              <article className="feedback-dashboard__signal" key={signal.label}>
                <span className="metric-label">{signal.label}</span>
                <strong>{signal.value}</strong>
                <p>{signal.note}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="panel stack">
          <div className="table-toolbar">
            <div>
              <h2>Feedback details</h2>
              <p className="muted small">Each row links back to the exact analysis run that produced the feedback.</p>
            </div>
            {loading ? <StatusBadge status="running" /> : <span className="badge neutral">{feedback.length} rows</span>}
          </div>
          {loading ? <div className="muted">Loading feedback...</div> : null}
          {!loading && feedback.length === 0 ? <div className="muted">No feedback matches the current filters.</div> : null}
          {!loading && feedback.length > 0 ? (
            <div className="table-wrap feedback-dashboard__table">
              <table>
                <thead>
                  <tr>
                    <th>Rating</th>
                    <th>Feedback</th>
                    <th>Flags</th>
                    <th>Document</th>
                    <th>Provider</th>
                    <th>Verdict</th>
                    <th>Processed</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {feedback.map((item) => (
                    <tr key={item.id}>
                      <td>
                        {item.rating === null ? (
                          <span className="badge neutral">Legacy / no score</span>
                        ) : (
                          <span className={item.rating <= 2 ? "badge danger" : item.rating === 3 ? "badge warning" : "badge ok"}>
                            {item.rating}/5
                          </span>
                        )}
                        <div className="muted small">{formatLabel(item.usefulness)}</div>
                      </td>
                      <td>
                        <strong>{item.user_login}</strong>
                        <p className="feedback-dashboard__comment">{item.comment ?? "No comment text."}</p>
                        <div className="muted small">{formatDate(item.created_at)}</div>
                      </td>
                      <td>
                        <div className="chip-row">
                          <FlagBadge active={item.verdict_correct === false} label="Incorrect verdict" />
                          <FlagBadge active={item.has_false_findings === true} label="False findings" />
                          <FlagBadge active={item.has_missed_findings === true} label="Missed findings" />
                          <FlagBadge active={item.can_use_for_benchmark} label="Benchmark" />
                        </div>
                      </td>
                      <td>
                        {item.document_title}
                        <div className="muted small">{item.analysis_id}</div>
                      </td>
                      <td>
                        {formatLabel(item.provider)}
                        <div className="muted small">{item.model}</div>
                        <div className="muted small">Skill {item.skill_version}</div>
                      </td>
                      <td>
                        <VerdictBadge verdict={item.analysis_verdict} />
                      </td>
                      <td>
                        {item.processed_at ? <StatusBadge status="completed" /> : <StatusBadge status="queued" />}
                        <div className="muted small">{formatDate(item.processed_at)}</div>
                      </td>
                      <td className="button-row">
                        <Link className="secondary-link" href={`/analyses/${item.analysis_id}`}>
                          Open run
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

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <article className="metric-card">
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      <span className="metric-note">{note}</span>
    </article>
  );
}

function FlagBadge({ active, label }: { active: boolean; label: string }) {
  return <span className={active ? "badge danger" : "badge neutral"}>{label}</span>;
}

function VerdictBadge({ verdict }: { verdict: string | null }) {
  const tone = verdict === "approve" ? "ok" : verdict === "reject" ? "danger" : "info";
  return <span className={`badge ${tone}`}>{formatLabel(verdict)}</span>;
}

function formatAverage(value: number | null) {
  return value === null ? "-" : value.toFixed(2);
}

function buildImprovementSignals(summary: AdminFeedbackSummary, feedback: AdminFeedback[]) {
  const problemFeedback = feedback.filter(
    (item) =>
      (item.rating !== null && item.rating <= 2) ||
      item.verdict_correct === false ||
      item.has_false_findings === true ||
      item.has_missed_findings === true,
  );
  const topModels = topBreakdown(problemFeedback, (item) => item.model);
  const topProviders = topBreakdown(problemFeedback, (item) => formatLabel(item.provider));
  const topSkillVersions = topBreakdown(problemFeedback, (item) => item.skill_version);

  return [
    {
      label: "Low ratings",
      value: String(summary.low_rating_count),
      note: "Prioritize comments with 1-2 scores and inspect their linked runs.",
    },
    {
      label: "Incorrect verdicts",
      value: String(summary.incorrect_verdict_count),
      note: "Review verdict thresholds and prompt examples for these documents.",
    },
    {
      label: "False findings",
      value: String(summary.false_findings_count),
      note: "Check evidence grounding and hallucinated risks in the linked runs.",
    },
    {
      label: "Missed findings",
      value: String(summary.missed_findings_count),
      note: "Use comments to identify rubric gaps and missing document evidence.",
    },
    {
      label: "Model breakdown",
      value: topModels || "-",
      note: "Problem feedback grouped by model.",
    },
    {
      label: "Provider breakdown",
      value: topProviders || "-",
      note: "Problem feedback grouped by provider.",
    },
    {
      label: "Skill version breakdown",
      value: topSkillVersions || "-",
      note: "Problem feedback grouped by skill version.",
    },
    {
      label: "Legacy / no score",
      value: String(summary.legacy_count),
      note: "Older feedback remains visible but is excluded from average rating.",
    },
  ];
}

function topBreakdown(items: AdminFeedback[], keyFor: (item: AdminFeedback) => string) {
  const counts = new Map<string, number>();
  items.forEach((item) => {
    const key = keyFor(item);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  });
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 3)
    .map(([key, count]) => `${key}: ${count}`)
    .join(", ");
}
