"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { cancelBenchmark, getBenchmark, getBenchmarkReport, type BenchmarkRecord } from "@/lib/api/benchmarks";
import { formatDate, formatLabel } from "@/lib/format";

type BenchmarkTab = "documents" | "missed" | "falsePositives" | "partial" | "report";

const benchmarkTabs: Array<{ id: BenchmarkTab; label: string }> = [
  { id: "documents", label: "Documents" },
  { id: "missed", label: "Missed" },
  { id: "falsePositives", label: "False Positives" },
  { id: "partial", label: "Partial Matches" },
  { id: "report", label: "Report" },
];

export default function BenchmarkDetailPage() {
  const params = useParams<{ benchmarkId: string }>();
  const [benchmark, setBenchmark] = useState<BenchmarkRecord | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [activeTab, setActiveTab] = useState<BenchmarkTab>("documents");

  async function refresh() {
    const [nextBenchmark, nextReport] = await Promise.all([
      getBenchmark(params.benchmarkId),
      getBenchmarkReport(params.benchmarkId),
    ]);
    setBenchmark(nextBenchmark);
    setReport(nextReport);
  }

  useEffect(() => {
    setLoading(true);
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load benchmark"))
      .finally(() => setLoading(false));
  }, [params.benchmarkId]);

  async function cancel() {
    setPending(true);
    setError("");
    try {
      setBenchmark(await cancelBenchmark(params.benchmarkId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel benchmark");
    } finally {
      setPending(false);
    }
  }

  const currentReport = report ?? benchmark?.report ?? null;
  const inspector = useMemo(() => (benchmark ? buildInspector(benchmark, currentReport) : null), [benchmark, currentReport]);

  return (
    <AppShell>
      <main className="benchmark-dashboard">
        <style>{benchmarkDetailStyles}</style>
        {error ? <section className="benchmark-alert">{error}</section> : null}
        {loading && !benchmark ? (
          <section className="benchmark-state">Loading benchmark...</section>
        ) : benchmark ? (
          <>
            <section className="benchmark-hero">
              <div>
                <div className="benchmark-eyebrow">QA dashboard</div>
                <h1>{benchmark.name}</h1>
                <p>{benchmark.description || "Benchmark run over selected active etalons."}</p>
                <div className="benchmark-chip-row">
                  <StatusBadge status={benchmark.status} />
                  <Chip label="Provider" value={formatLabel(benchmark.provider)} />
                  <Chip label="Model" value={benchmark.model} />
                  <Chip label="Skill version" value={benchmark.skill_version} />
                  <Chip label="Started" value={formatDate(benchmark.started_at)} />
                </div>
              </div>
              <div className="benchmark-score-grid">
                <MetricCard label="Overall F1" value={benchmark.f1 ?? benchmark.overall_score} />
                <MetricCard label="Layer 1" value={benchmark.layer_1_score} />
                <MetricCard label="Layer 2" value={benchmark.layer_2_score} />
                <MetricCard label="Precision" value={benchmark.precision} />
                <MetricCard label="Recall" value={benchmark.recall} />
              </div>
            </section>

            {benchmark.error_message ? <section className="benchmark-alert">{benchmark.error_message}</section> : null}

            <div className="benchmark-layout">
              <section className="benchmark-main">
                <nav className="benchmark-tabs" aria-label="Benchmark result sections">
                  {benchmarkTabs.map((tab) => (
                    <button
                      aria-pressed={activeTab === tab.id}
                      className={activeTab === tab.id ? "benchmark-tab benchmark-tab--active" : "benchmark-tab"}
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                    >
                      {tab.label}
                    </button>
                  ))}
                </nav>

                {activeTab === "documents" ? <DocumentsPanel report={currentReport} /> : null}
                {activeTab === "missed" ? (
                  <IssuePanel
                    emptyMessage="No missed findings were reported."
                    items={benchmark.missed_findings}
                    title="Missed Findings"
                  />
                ) : null}
                {activeTab === "falsePositives" ? (
                  <IssuePanel
                    emptyMessage="No false positives were reported."
                    items={benchmark.false_positives}
                    title="False Positives"
                  />
                ) : null}
                {activeTab === "partial" ? (
                  <IssuePanel
                    emptyMessage="No partial matches were reported."
                    items={benchmark.partial_matches}
                    title="Partial Matches"
                  />
                ) : null}
                {activeTab === "report" ? <ReportPanel benchmark={benchmark} report={currentReport} /> : null}
              </section>

              <aside className="benchmark-inspector">
                <section className="benchmark-card">
                  <div className="benchmark-card__header">
                    <div>
                      <h2>Run control</h2>
                      <p>Queued and running benchmarks can be cancelled.</p>
                    </div>
                  </div>
                  <button
                    className="benchmark-secondary"
                    disabled={pending || !["queued", "running"].includes(benchmark.status)}
                    type="button"
                    onClick={cancel}
                  >
                    {pending ? "Cancelling..." : "Cancel"}
                  </button>
                  <InspectorRow label="Started by" value={benchmark.started_by_id} />
                  <InspectorRow label="Completed" value={formatDate(benchmark.completed_at)} />
                  <InspectorRow label="Etalons" value={String(benchmark.etalon_ids.length)} />
                </section>

                <section className="benchmark-card">
                  <div className="benchmark-card__header">
                    <div>
                      <h2>Gaps</h2>
                      <p>Counts from persisted judge output.</p>
                    </div>
                  </div>
                  <div className="benchmark-count-grid">
                    <Count label="Missed" value={benchmark.missed_findings?.length ?? 0} tone="bad" />
                    <Count label="False" value={benchmark.false_positives?.length ?? 0} tone="warn" />
                    <Count label="Partial" value={benchmark.partial_matches?.length ?? 0} tone="neutral" />
                  </div>
                </section>

                <section className="benchmark-card">
                  <div className="benchmark-card__header">
                    <div>
                      <h2>Recommendations</h2>
                      <p>Derived from report recommendations and issue fields.</p>
                    </div>
                  </div>
                  {inspector?.recommendations.length ? (
                    <ul className="benchmark-list">
                      {inspector.recommendations.slice(0, 6).map((recommendation) => (
                        <li key={recommendation}>{recommendation}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="benchmark-muted">No recommendations reported.</p>
                  )}
                </section>

                <section className="benchmark-card">
                  <div className="benchmark-card__header">
                    <div>
                      <h2>Trace</h2>
                      <p>Parameters kept for reproducibility.</p>
                    </div>
                  </div>
                  <InspectorRow label="Judge skill" value={benchmark.judge_skill_id} />
                  <InspectorRow label="Run params" value={`${Object.keys(benchmark.run_parameters).length} keys`} />
                  <details className="benchmark-details">
                    <summary>Run parameters JSON</summary>
                    <JsonBlock value={benchmark.run_parameters} />
                  </details>
                </section>
              </aside>
            </div>
          </>
        ) : (
          <section className="benchmark-state">Benchmark was not found.</section>
        )}
      </main>
    </AppShell>
  );
}

function DocumentsPanel({ report }: { report: Record<string, unknown> | null }) {
  const documents = asRecordArray(report?.documents);
  return (
    <section className="benchmark-card">
      <div className="benchmark-card__header">
        <div>
          <h2>Per-document results</h2>
          <p>Document-level status, scores, and judge output when available.</p>
        </div>
      </div>
      {documents.length ? (
        <div className="benchmark-doc-grid">
          {documents.map((document, index) => (
            <article className="benchmark-doc" key={`${asString(document.etalon_id) || index}`}>
              <div className="benchmark-doc__top">
                <span>{asString(document.document_title) || asString(document.etalon_id) || `Document ${index + 1}`}</span>
                <span className={`benchmark-pill benchmark-pill--${toneForValue(asString(document.status))}`}>
                  {formatLabel(asString(document.status))}
                </span>
              </div>
              <DocumentScores scores={asRecord(document.scores)} />
              {asString(document.error_message) ? <p className="benchmark-error-text">{asString(document.error_message)}</p> : null}
              {asRecord(document.judge_output) ? (
                <details className="benchmark-details">
                  <summary>Judge output JSON</summary>
                  <JsonBlock value={document.judge_output} />
                </details>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <p className="benchmark-muted">No per-document report is available yet.</p>
      )}
    </section>
  );
}

function IssuePanel({
  emptyMessage,
  items,
  title,
}: {
  emptyMessage: string;
  items: unknown[] | null;
  title: string;
}) {
  const records = Array.isArray(items) ? items : [];
  return (
    <section className="benchmark-card">
      <div className="benchmark-card__header">
        <div>
          <h2>{title}</h2>
          <p>{records.length ? `${records.length} persisted item(s)` : emptyMessage}</p>
        </div>
      </div>
      {records.length ? (
        <div className="benchmark-issue-grid">
          {records.map((item, index) => (
            <IssueCard index={index} item={item} key={`${title}-${index}`} />
          ))}
        </div>
      ) : (
        <p className="benchmark-muted">{emptyMessage}</p>
      )}
      <details className="benchmark-details">
        <summary>Raw {title.toLowerCase()} JSON</summary>
        <JsonBlock value={records} />
      </details>
    </section>
  );
}

function ReportPanel({ benchmark, report }: { benchmark: BenchmarkRecord; report: Record<string, unknown> | null }) {
  const currentReport = report ?? benchmark.report ?? {};
  const recommendations = collectRecommendations(currentReport, benchmark);
  const failures = asRecordArray(currentReport.model_failures);
  return (
    <section className="benchmark-card">
      <div className="benchmark-card__header">
        <div>
          <h2>Report</h2>
          <p>Report-oriented view with model failures and improvement recommendations.</p>
        </div>
      </div>
      {recommendations.length ? <StringList title="Recommendations" values={recommendations} /> : null}
      {failures.length ? <RecordGrid records={failures} title="Model failures" /> : null}
      <details className="benchmark-details" open>
        <summary>Raw report JSON</summary>
        <JsonBlock value={currentReport} />
      </details>
      {benchmark.judge_output ? (
        <details className="benchmark-details">
          <summary>Judge output JSON</summary>
          <JsonBlock value={benchmark.judge_output} />
        </details>
      ) : null}
    </section>
  );
}

function MetricCard({ label, value }: { label: string; value: string | null }) {
  return (
    <div className={`benchmark-metric benchmark-metric--${scoreTone(value)}`}>
      <span>{label}</span>
      <strong>{value ?? "-"}</strong>
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="benchmark-chip">
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="benchmark-inspector-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Count({ label, tone, value }: { label: string; tone: string; value: number }) {
  return (
    <div className={`benchmark-count benchmark-count--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DocumentScores({ scores }: { scores: Record<string, unknown> | null }) {
  if (!scores) {
    return <p className="benchmark-muted">No scores reported.</p>;
  }
  const layer1 = asRecord(scores.layer_1);
  const layer2 = asRecord(scores.layer_2);
  return (
    <div className="benchmark-mini-scores">
      <MiniScore label="F1" value={asNumberOrString(scores.f1)} />
      <MiniScore label="Precision" value={asNumberOrString(scores.precision)} />
      <MiniScore label="Recall" value={asNumberOrString(scores.recall)} />
      <MiniScore label="Layer 1" value={asNumberOrString(layer1?.f1)} />
      <MiniScore label="Layer 2" value={asNumberOrString(layer2?.f1)} />
    </div>
  );
}

function MiniScore({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function IssueCard({ index, item }: { index: number; item: unknown }) {
  const record = asRecord(item);
  if (!record) {
    return (
      <article className="benchmark-issue">
        <div className="benchmark-doc__top">
          <span>Item {index + 1}</span>
        </div>
        <p>{String(item)}</p>
      </article>
    );
  }

  return (
    <article className="benchmark-issue">
      <div className="benchmark-doc__top">
        <span>{asString(record.id) || asString(record.expected_id) || asString(record.actual_id) || `Item ${index + 1}`}</span>
        <span className={`benchmark-pill benchmark-pill--${toneForValue(asString(record.severity) || asString(record.status))}`}>
          {formatLabel(asString(record.severity) || asString(record.status))}
        </span>
      </div>
      <h3>{recordTitle(record)}</h3>
      {recordBody(record) ? <p>{recordBody(record)}</p> : null}
      {asString(record.evidence) ? (
        <blockquote>
          <strong>Evidence</strong>
          {asString(record.evidence)}
        </blockquote>
      ) : null}
      {asString(record.recommendation) ? (
        <p>
          <strong>Recommendation:</strong> {asString(record.recommendation)}
        </p>
      ) : null}
      <details className="benchmark-details">
        <summary>Item JSON</summary>
        <JsonBlock value={record} />
      </details>
    </article>
  );
}

function RecordGrid({ records, title }: { records: Record<string, unknown>[]; title: string }) {
  return (
    <div>
      <h3>{title}</h3>
      <div className="benchmark-issue-grid">
        {records.map((record, index) => (
          <IssueCard index={index} item={record} key={`${title}-${index}`} />
        ))}
      </div>
    </div>
  );
}

function StringList({ title, values }: { title: string; values: string[] }) {
  return (
    <div>
      <h3>{title}</h3>
      <ul className="benchmark-list">
        {values.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="benchmark-pre">{JSON.stringify(value, null, 2)}</pre>;
}

function buildInspector(benchmark: BenchmarkRecord, report: Record<string, unknown> | null) {
  return {
    recommendations: collectRecommendations(report, benchmark),
  };
}

function collectRecommendations(report: Record<string, unknown> | null, benchmark: BenchmarkRecord): string[] {
  const values = [
    ...stringifyList(report?.recommendations),
    ...stringifyRecommendations(benchmark.missed_findings),
    ...stringifyRecommendations(benchmark.false_positives),
    ...stringifyRecommendations(benchmark.partial_matches),
  ];
  return Array.from(new Set(values)).slice(0, 12);
}

function stringifyRecommendations(items: unknown[] | null): string[] {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.flatMap((item) => {
    const record = asRecord(item);
    if (!record) {
      return [];
    }
    return [asString(record.recommendation), asString(record.explanation), asString(record.reason)].filter(
      (value): value is string => Boolean(value),
    );
  });
}

function stringifyList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }
      const record = asRecord(item);
      return record ? recordTitle(record) : null;
    })
    .filter((item): item is string => Boolean(item));
}

function recordTitle(record: Record<string, unknown>): string {
  return (
    asString(record.title) ||
    asString(record.name) ||
    asString(record.expected_title) ||
    asString(record.actual_title) ||
    asString(record.expected_id) ||
    asString(record.actual_id) ||
    "Structured issue"
  );
}

function recordBody(record: Record<string, unknown>): string | null {
  return (
    asString(record.summary) ||
    asString(record.explanation) ||
    asString(record.reason) ||
    asString(record.issue) ||
    asString(record.risk) ||
    asString(record.comment)
  );
}

function scoreTone(value: string | null): string {
  const numeric = value === null ? NaN : Number(value);
  if (Number.isNaN(numeric)) {
    return "neutral";
  }
  if (numeric >= 0.8) {
    return "good";
  }
  if (numeric >= 0.5) {
    return "warn";
  }
  return "bad";
}

function toneForValue(value: string | null | undefined): string {
  if (!value) {
    return "neutral";
  }
  if (["completed", "pass", "approve", "low"].includes(value)) {
    return "good";
  }
  if (["running", "queued", "partial", "medium", "important"].includes(value)) {
    return "warn";
  }
  if (["failed", "cancelled", "high", "critical", "reject"].includes(value)) {
    return "bad";
  }
  return "neutral";
}

function asNumberOrString(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toFixed(3);
  }
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return "-";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(asRecord(item))) : [];
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

const benchmarkDetailStyles = `
.benchmark-dashboard {
  width: min(100%, 1480px);
  margin: 0 auto;
  padding: 28px 24px 48px;
  color: #e6edf3;
}

.benchmark-dashboard h1,
.benchmark-dashboard h2,
.benchmark-dashboard h3,
.benchmark-dashboard p {
  margin: 0;
}

.benchmark-dashboard h1 {
  font-size: clamp(30px, 4vw, 52px);
  line-height: 1;
}

.benchmark-dashboard h2 {
  font-size: 18px;
  line-height: 1.25;
}

.benchmark-dashboard h3 {
  margin-bottom: 10px;
  font-size: 15px;
}

.benchmark-dashboard button {
  border: 1px solid rgba(94, 234, 212, 0.28);
  background: linear-gradient(180deg, #14b8a6 0%, #0f766e 100%);
  color: #f8fafc;
  box-shadow: 0 12px 28px rgba(20, 184, 166, 0.18);
}

.benchmark-dashboard button:focus-visible {
  outline: 3px solid rgba(56, 189, 248, 0.42);
  outline-offset: 2px;
}

.benchmark-dashboard .badge {
  border-color: rgba(148, 163, 184, 0.28);
  background: rgba(15, 23, 42, 0.78);
  color: #cbd5e1;
}

.benchmark-dashboard .badge.ok {
  border-color: rgba(52, 211, 153, 0.35);
  background: rgba(6, 78, 59, 0.58);
  color: #bbf7d0;
}

.benchmark-dashboard .badge.info {
  border-color: rgba(56, 189, 248, 0.38);
  background: rgba(12, 74, 110, 0.55);
  color: #bae6fd;
}

.benchmark-dashboard .badge.danger {
  border-color: rgba(248, 113, 113, 0.44);
  background: rgba(127, 29, 29, 0.55);
  color: #fecaca;
}

.benchmark-hero,
.benchmark-card,
.benchmark-alert,
.benchmark-state {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.96)),
    #020617;
  box-shadow: 0 22px 70px rgba(2, 6, 23, 0.28);
}

.benchmark-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(420px, 0.72fr);
  gap: 18px;
  margin-bottom: 18px;
  padding: 22px;
}

.benchmark-hero p,
.benchmark-card__header p,
.benchmark-muted,
.benchmark-doc p,
.benchmark-issue p,
.benchmark-state,
.benchmark-list {
  color: #9fb0c4;
  font-size: 13px;
  line-height: 1.6;
}

.benchmark-hero p {
  max-width: 78ch;
  margin-top: 12px;
  font-size: 15px;
}

.benchmark-eyebrow {
  margin-bottom: 10px;
  color: #5eead4;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.benchmark-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 14px;
}

.benchmark-chip {
  display: inline-grid;
  gap: 2px;
  min-height: 40px;
  align-content: center;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.72);
  padding: 6px 10px;
  color: #cbd5e1;
  font-size: 12px;
}

.benchmark-chip span,
.benchmark-inspector-row span,
.benchmark-count span,
.benchmark-metric span,
.benchmark-mini-scores span {
  color: #7f8ea3;
  font-size: 11px;
  text-transform: uppercase;
}

.benchmark-chip strong,
.benchmark-inspector-row strong,
.benchmark-count strong,
.benchmark-metric strong,
.benchmark-mini-scores strong {
  color: #f8fafc;
}

.benchmark-score-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.benchmark-metric,
.benchmark-count,
.benchmark-inspector-row,
.benchmark-doc,
.benchmark-issue {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.62);
  padding: 14px;
}

.benchmark-metric {
  display: grid;
  gap: 8px;
}

.benchmark-metric strong {
  font-size: 26px;
}

.benchmark-metric--good {
  border-color: rgba(52, 211, 153, 0.34);
}

.benchmark-metric--warn {
  border-color: rgba(251, 191, 36, 0.36);
}

.benchmark-metric--bad {
  border-color: rgba(248, 113, 113, 0.38);
}

.benchmark-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 18px;
  align-items: start;
}

.benchmark-main,
.benchmark-inspector,
.benchmark-card,
.benchmark-doc,
.benchmark-issue {
  display: grid;
  gap: 14px;
}

.benchmark-inspector {
  position: sticky;
  top: 18px;
}

.benchmark-card,
.benchmark-alert,
.benchmark-state {
  padding: 18px;
}

.benchmark-alert {
  margin-bottom: 14px;
  border-color: rgba(248, 113, 113, 0.42);
  color: #fecaca;
}

.benchmark-state {
  color: #94a3b8;
}

.benchmark-card__header,
.benchmark-doc__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.benchmark-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.72);
  padding: 6px;
}

.benchmark-tab {
  min-height: 38px;
  border-color: transparent !important;
  background: transparent !important;
  box-shadow: none !important;
  color: #94a3b8 !important;
}

.benchmark-tab--active {
  border-color: rgba(94, 234, 212, 0.32) !important;
  background: rgba(20, 184, 166, 0.16) !important;
  color: #f8fafc !important;
}

.benchmark-secondary {
  border-color: rgba(148, 163, 184, 0.24) !important;
  background: rgba(15, 23, 42, 0.72) !important;
  box-shadow: none !important;
}

.benchmark-count-grid,
.benchmark-mini-scores {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.benchmark-count,
.benchmark-mini-scores div {
  display: grid;
  gap: 6px;
}

.benchmark-count--bad {
  border-color: rgba(248, 113, 113, 0.38);
}

.benchmark-count--warn {
  border-color: rgba(251, 191, 36, 0.36);
}

.benchmark-doc-grid,
.benchmark-issue-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}

.benchmark-pill {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.benchmark-pill--good {
  border: 1px solid rgba(52, 211, 153, 0.4);
  background: rgba(6, 95, 70, 0.72);
  color: #bbf7d0;
}

.benchmark-pill--warn {
  border: 1px solid rgba(251, 191, 36, 0.42);
  background: rgba(120, 53, 15, 0.7);
  color: #fde68a;
}

.benchmark-pill--bad {
  border: 1px solid rgba(248, 113, 113, 0.46);
  background: rgba(127, 29, 29, 0.7);
  color: #fecaca;
}

.benchmark-pill--neutral {
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(30, 41, 59, 0.78);
  color: #cbd5e1;
}

.benchmark-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 20px;
}

.benchmark-details {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.38);
  padding: 10px;
}

.benchmark-details summary {
  cursor: pointer;
  color: #bae6fd;
  font-weight: 700;
}

.benchmark-pre {
  max-height: 520px;
  overflow: auto;
  margin-top: 10px;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.7);
  color: #dbeafe;
  padding: 14px;
  font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.benchmark-issue blockquote {
  display: grid;
  gap: 4px;
  margin: 0;
  border-left: 3px solid rgba(94, 234, 212, 0.6);
  padding-left: 10px;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.55;
}

.benchmark-error-text {
  color: #fecaca !important;
}

@media (max-width: 1080px) {
  .benchmark-hero,
  .benchmark-layout {
    grid-template-columns: 1fr;
  }

  .benchmark-inspector {
    position: static;
  }
}

@media (max-width: 680px) {
  .benchmark-dashboard {
    width: 100%;
    padding: 18px 10px 32px;
  }

  .benchmark-hero,
  .benchmark-card {
    padding: 14px;
  }

  .benchmark-score-grid,
  .benchmark-count-grid,
  .benchmark-mini-scores {
    grid-template-columns: 1fr;
  }
}
`;
