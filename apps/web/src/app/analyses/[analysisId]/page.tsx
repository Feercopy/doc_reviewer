"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  getAnalysis,
  type AnalysisRecord,
  type PredictedCommentRunRecord,
  type RetrievalTrace,
  type SourceTrace,
} from "@/lib/api/documents";
import { createEtalonDraft } from "@/lib/api/etalons";
import { submitFeedback } from "@/lib/api/feedback";
import { formatDate, formatLabel } from "@/lib/format";

type AnalysisTab = "summary" | "layer1" | "layer2" | "devilsAdvocate" | "fullOutput";

type EvidenceItem = {
  id: string;
  title: string;
  severity: string | null;
  evidence: string | null;
  detail: string | null;
  recommendation: string | null;
};

const analysisTabs: Array<{ id: AnalysisTab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "layer1", label: "Layer 1" },
  { id: "layer2", label: "Layer 2" },
  { id: "devilsAdvocate", label: "Devil's Advocate" },
  { id: "fullOutput", label: "Full Output" },
];

export default function AnalysisDetailPage() {
  const params = useParams<{ analysisId: string }>();
  const [analysis, setAnalysis] = useState<AnalysisRecord | null>(null);
  const [error, setError] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [usefulness, setUsefulness] = useState<"useful" | "partially_useful" | "useless">("useful");
  const [canUseForBenchmark, setCanUseForBenchmark] = useState(false);
  const [etalonPending, setEtalonPending] = useState(false);
  const [activeTab, setActiveTab] = useState<AnalysisTab>("summary");

  useEffect(() => {
    getAnalysis(params.analysisId)
      .then(setAnalysis)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load analysis"));
  }, [params.analysisId]);

  async function sendFeedback() {
    if (!analysis) {
      return;
    }
    setFeedbackStatus("");
    setError("");
    try {
      await submitFeedback(analysis.id, {
        usefulness,
        verdict_correct: null,
        has_false_findings: null,
        has_missed_findings: null,
        comment: feedbackComment || null,
        can_use_for_benchmark: canUseForBenchmark,
      });
      setFeedbackStatus("Feedback saved");
      setFeedbackComment("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit feedback");
    }
  }

  async function createDraft() {
    if (!analysis) {
      return;
    }
    setEtalonPending(true);
    setError("");
    try {
      const etalon = await createEtalonDraft(analysis.id);
      window.location.href = `/annotation/${etalon.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create etalon draft");
    } finally {
      setEtalonPending(false);
    }
  }

  const inspector = useMemo(() => (analysis ? buildInspector(analysis) : null), [analysis]);
  const inspectorQuestions = analysis
    ? asStringArray(analysis.predicted_comment_run?.structured_output?.predicted_questions).slice(0, 3)
    : [];

  return (
    <AppShell>
      <main className="analysis-workbench">
        <style>{analysisStyles}</style>
        {error ? <section className="analysis-alert">{error}</section> : null}
        {analysis ? (
          <>
            <section className="analysis-hero">
              <div className="analysis-hero__main">
                <div className="analysis-eyebrow">Evidence workbench</div>
                <h1>Analysis</h1>
                <p className="analysis-hero__summary">
                  {analysis.summary || summaryFromOutput(analysis.structured_output) || "Analysis output is loading."}
                </p>
                <div className="analysis-chip-row">
                  <span className={`analysis-verdict analysis-verdict--${toneForValue(analysis.verdict)}`}>
                    {formatLabel(analysis.verdict)}
                  </span>
                  <StatusBadge status={analysis.status} />
                  <TraceChip label="Provider" value={formatLabel(analysis.provider)} />
                  <TraceChip label="Model" value={analysis.model} />
                  <TraceChip label="Skill" value={`${analysis.skill_name} · ${analysis.skill_version}`} />
                  <TraceChip label="Created" value={formatDate(analysis.created_at)} />
                </div>
              </div>
              <TracePanel
                title="Run Trace"
                sourceTrace={analysis.source_trace}
                runParameters={analysis.run_parameters}
                startedAt={analysis.started_at}
                completedAt={analysis.completed_at}
              />
            </section>

            {analysis.error_message ? <section className="analysis-alert">{analysis.error_message}</section> : null}

            <div className="analysis-layout">
              <section className="analysis-main stack">
                <nav className="analysis-tabs" aria-label="Analysis output sections">
                  {analysisTabs.map((tab) => (
                    <button
                      aria-pressed={activeTab === tab.id}
                      className={activeTab === tab.id ? "analysis-tab analysis-tab--active" : "analysis-tab"}
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                    >
                      {tab.label}
                    </button>
                  ))}
                </nav>

                {activeTab === "summary" ? <SummaryPanel analysis={analysis} /> : null}
                {activeTab === "layer1" ? (
                  <LayerPanel
                    emptyMessage="No Layer 1 output yet."
                    items={extractEvidenceItems(analysis.structured_output, "layer_1")}
                    markdown={asString(analysis.structured_output?.layer_1_markdown)}
                    raw={analysis.structured_output?.layer_1}
                    title="Layer 1"
                  />
                ) : null}
                {activeTab === "layer2" ? (
                  <LayerPanel
                    emptyMessage="No Layer 2 output yet."
                    items={extractEvidenceItems(analysis.structured_output, "layer_2")}
                    markdown={asString(analysis.structured_output?.layer_2_markdown)}
                    raw={analysis.structured_output?.layer_2}
                    title="Layer 2"
                  />
                ) : null}
                {activeTab === "devilsAdvocate" ? (
                  <DevilsAdvocatePanel run={analysis.predicted_comment_run} />
                ) : null}
                {activeTab === "fullOutput" ? <FullOutputPanel analysis={analysis} /> : null}
              </section>

              <aside className="analysis-inspector">
                <section className="analysis-card stack">
                  <div>
                    <div className="analysis-card__label">Verdict</div>
                    <div className={`analysis-inspector__verdict analysis-verdict--${toneForValue(analysis.verdict)}`}>
                      {formatLabel(analysis.verdict)}
                    </div>
                  </div>
                  <div className="analysis-score-grid">
                    <Metric label="Input" value={formatNumber(analysis.input_tokens)} />
                    <Metric label="Output" value={formatNumber(analysis.output_tokens)} />
                    <Metric label="Latency" value={analysis.latency_ms ? `${analysis.latency_ms} ms` : "-"} />
                    <Metric label="Cost" value={analysis.estimated_cost ?? "-"} />
                  </div>
                  <button disabled={etalonPending || analysis.status !== "completed"} type="button" onClick={createDraft}>
                    Create etalon draft
                  </button>
                </section>

                <section className="analysis-card stack">
                  <h2>Top risks</h2>
                  {inspector?.topRisks.length ? (
                    <div className="analysis-risk-list">
                      {inspector.topRisks.map((risk) => (
                        <article className="analysis-risk" key={`${risk.id}-${risk.title}`}>
                          <div>
                            <span className={`analysis-severity analysis-severity--${toneForValue(risk.severity)}`}>
                              {formatLabel(risk.severity)}
                            </span>
                          </div>
                          <strong>{risk.title}</strong>
                          {risk.evidence ? <p>{risk.evidence}</p> : null}
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="analysis-muted">No structured risk items found yet.</p>
                  )}
                </section>

                <section className="analysis-card stack">
                  <h2>Evidence trace</h2>
                  <InspectorTrace label="Source" value={analysis.source_trace?.source_slug} />
                  <InspectorTrace label="Snapshot" value={shortHash(analysis.source_trace?.source_snapshot_id)} />
                  <InspectorTrace label="Prompt" value={shortHash(analysis.source_trace?.prompt_fingerprint)} />
                  <InspectorTrace label="DA source" value={analysis.predicted_comment_run?.source_trace?.source_slug} />
                  <InspectorTrace
                    label="DA corpus"
                    value={shortHash(analysis.predicted_comment_run?.retrieval_trace?.corpus_fingerprint)}
                  />
                </section>

                <section className="analysis-card stack">
                  <h2>Devil&apos;s Advocate</h2>
                  <InspectorTrace label="Decision" value={inspector?.daDecision} />
                  <InspectorTrace label="Retrieval" value={analysis.predicted_comment_run?.retrieval_trace?.retrieval_mode} />
                  {inspectorQuestions.length ? (
                    <div className="analysis-question-list">
                      {inspectorQuestions.map((question) => (
                        <p key={question}>{question}</p>
                      ))}
                    </div>
                  ) : null}
                  {inspector?.consultedPages.length ? (
                    <div className="analysis-token-list">
                      {inspector.consultedPages.slice(0, 6).map((page) => (
                        <span className="analysis-token" key={page}>
                          {page}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="analysis-muted">No consulted pages reported.</p>
                  )}
                </section>

                <section className="analysis-card stack" id="feedback">
                  <h2>Feedback</h2>
                  <label>
                    Usefulness
                    <select value={usefulness} onChange={(event) => setUsefulness(event.target.value as typeof usefulness)}>
                      <option value="useful">Useful</option>
                      <option value="partially_useful">Partially useful</option>
                      <option value="useless">Useless</option>
                    </select>
                  </label>
                  <label className="analysis-checkbox">
                    <input
                      checked={canUseForBenchmark}
                      type="checkbox"
                      onChange={(event) => setCanUseForBenchmark(event.target.checked)}
                    />
                    Use for benchmark review
                  </label>
                  <label>
                    Comment
                    <textarea value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)} />
                  </label>
                  <div className="analysis-action-row">
                    <button type="button" onClick={sendFeedback}>
                      Submit feedback
                    </button>
                    {feedbackStatus ? <span className="analysis-success">{feedbackStatus}</span> : null}
                  </div>
                </section>
              </aside>
            </div>
          </>
        ) : (
          <section className="analysis-loading">Loading...</section>
        )}
      </main>
    </AppShell>
  );
}

function SummaryPanel({ analysis }: { analysis: AnalysisRecord }) {
  const output = analysis.structured_output;
  const assessment = asString(output?.assessment_markdown);
  const summary = analysis.summary || summaryFromOutput(output);
  const keyFindings = asStringArray(output?.key_findings);
  const findings = extractEvidenceItems(output, "findings");
  const checks = extractChecks(output);

  return (
    <section className="analysis-card stack">
      <div className="analysis-section-heading">
        <div>
          <h2>Summary</h2>
          <p>Gate Challenger assessment with supporting structured findings.</p>
        </div>
      </div>
      {summary ? <p className="analysis-lead">{summary}</p> : null}
      {assessment ? <MarkdownBlock title="Native assessment" value={assessment} /> : null}
      {keyFindings.length ? (
        <div className="analysis-callout-grid">
          {keyFindings.slice(0, 7).map((finding) => (
            <div className="analysis-callout" key={finding}>
              {finding}
            </div>
          ))}
        </div>
      ) : null}
      {findings.length ? <EvidenceGrid items={findings} /> : null}
      {checks.length ? (
        <div className="analysis-check-grid">
          {checks.map((check) => (
            <article className="analysis-check" key={`${check.name}-${check.status}`}>
              <span className={`analysis-severity analysis-severity--${toneForValue(check.status)}`}>
                {formatLabel(check.status)}
              </span>
              <strong>{check.name}</strong>
              {check.explanation ? <p>{check.explanation}</p> : null}
            </article>
          ))}
        </div>
      ) : null}
      {output ? (
        <details className="analysis-details">
          <summary>Structured summary JSON</summary>
          <JsonBlock value={pickSummaryOutput(output)} />
        </details>
      ) : null}
    </section>
  );
}

function LayerPanel({
  emptyMessage,
  items,
  markdown,
  raw,
  title,
}: {
  emptyMessage: string;
  items: EvidenceItem[];
  markdown: string | null;
  raw: unknown;
  title: string;
}) {
  return (
    <section className="analysis-card stack">
      <div className="analysis-section-heading">
        <div>
          <h2>{title}</h2>
          <p>{items.length ? `${items.length} structured items` : "Native text is shown when available."}</p>
        </div>
      </div>
      {markdown ? <MarkdownBlock title={`${title} native output`} value={markdown} /> : null}
      {items.length ? <EvidenceGrid items={items} /> : markdown ? null : <p className="analysis-muted">{emptyMessage}</p>}
      {raw ? (
        <details className="analysis-details">
          <summary>{title} structured JSON</summary>
          <JsonBlock value={raw} />
        </details>
      ) : null}
    </section>
  );
}

function DevilsAdvocatePanel({ run }: { run: PredictedCommentRunRecord | null }) {
  if (!run) {
    return (
      <section className="analysis-card stack">
        <h2>Devil&apos;s Advocate</h2>
        <p className="analysis-muted">No Devil&apos;s Advocate run is attached yet.</p>
      </section>
    );
  }

  const output = run.structured_output;
  const nativeMarkdown = asString(output?.native_markdown);
  const roleComments = asRecordArray(output?.role_comments);
  const anchoredComments = asRecordArray(output?.anchored_comments);
  const contradictions = asRecordArray(output?.detected_contradictions);
  const toughQuestions = asRecordArray(output?.tough_questions);
  const jtbds = asStringArray(output?.actionable_jtbds);
  const predictedQuestions = asStringArray(output?.predicted_questions);
  const consultedPages = asStringArray(output?.consulted_wiki_pages);
  const icDecision = asRecord(output?.ic_decision);
  const trailer = asRecord(output?.trailer);

  return (
    <section className="analysis-card stack">
      <div className="analysis-section-heading">
        <div>
          <h2>Devil&apos;s Advocate</h2>
          <p>
            {run.skill_name} · {run.provider} · {run.model}
          </p>
        </div>
        <StatusBadge status={run.status} />
      </div>
      {run.error_message ? <div className="analysis-alert">{run.error_message}</div> : null}
      <TracePanel
        retrievalTrace={run.retrieval_trace}
        runParameters={run.run_parameters}
        sourceTrace={run.source_trace}
        title="Devil's Advocate Trace"
        startedAt={run.started_at}
        completedAt={run.completed_at}
      />
      {nativeMarkdown ? <MarkdownBlock title="Native IC voting output" value={nativeMarkdown} /> : null}
      {icDecision ? (
        <div className="analysis-split">
          <div>
            <div className="analysis-card__label">IC decision</div>
            <strong>{formatLabel(asString(icDecision.verdict))}</strong>
          </div>
          <div>
            <div className="analysis-card__label">Rationale</div>
            <p>{asString(icDecision.rationale) || "-"}</p>
          </div>
        </div>
      ) : null}
      {trailer?.executive_summary ? <p className="analysis-lead">{asString(trailer.executive_summary)}</p> : null}
      {roleComments.length ? <RecordList title="Role comments" records={roleComments} /> : null}
      {anchoredComments.length ? <RecordList title="Anchored comments" records={anchoredComments} /> : null}
      {contradictions.length ? <RecordList title="Contradictions and missing proofs" records={contradictions} /> : null}
      {toughQuestions.length ? <RecordList title="Tough questions" records={toughQuestions} /> : null}
      {predictedQuestions.length ? <StringList title="Predicted Questions" values={predictedQuestions} /> : null}
      {jtbds.length ? <StringList title="Actionable JTBDs" values={jtbds} /> : null}
      {consultedPages.length ? (
        <p className="analysis-muted analysis-wrap">Consulted pages: {consultedPages.join(", ")}</p>
      ) : null}
      {output ? (
        <details className="analysis-details">
          <summary>Structured Devil&apos;s Advocate JSON</summary>
          <JsonBlock value={output} />
        </details>
      ) : null}
      {run.raw_output ? (
        <details className="analysis-details">
          <summary>Raw Devil&apos;s Advocate Output</summary>
          <pre className="analysis-pre">{run.raw_output}</pre>
        </details>
      ) : null}
    </section>
  );
}

function FullOutputPanel({ analysis }: { analysis: AnalysisRecord }) {
  return (
    <section className="analysis-card stack">
      <div className="analysis-section-heading">
        <div>
          <h2>Full Output</h2>
          <p>Structured result, raw model text when authorized, and run parameters.</p>
        </div>
      </div>
      <details className="analysis-details" open>
        <summary>Gate Challenger structured JSON</summary>
        <JsonBlock value={analysis.structured_output ?? {}} />
      </details>
      {analysis.raw_output ? (
        <details className="analysis-details">
          <summary>Raw Gate Challenger Output</summary>
          <pre className="analysis-pre">{analysis.raw_output}</pre>
        </details>
      ) : null}
      {analysis.predicted_comment_run?.structured_output ? (
        <details className="analysis-details">
          <summary>Devil&apos;s Advocate structured JSON</summary>
          <JsonBlock value={analysis.predicted_comment_run.structured_output} />
        </details>
      ) : null}
      {analysis.predicted_comment_run?.raw_output ? (
        <details className="analysis-details">
          <summary>Raw Devil&apos;s Advocate Output</summary>
          <pre className="analysis-pre">{analysis.predicted_comment_run.raw_output}</pre>
        </details>
      ) : null}
      <details className="analysis-details">
        <summary>Run parameters</summary>
        <JsonBlock value={analysis.run_parameters} />
      </details>
    </section>
  );
}

function TracePanel({
  completedAt,
  retrievalTrace,
  runParameters,
  sourceTrace,
  startedAt,
  title,
}: {
  completedAt: string | null;
  retrievalTrace?: RetrievalTrace | null;
  runParameters: Record<string, unknown>;
  sourceTrace?: SourceTrace | null;
  startedAt: string | null;
  title: string;
}) {
  const snapshotMode = sourceTrace?.snapshot_mode;
  return (
    <div className="analysis-trace">
      <div className="analysis-trace__title">{title}</div>
      <div className="analysis-trace__grid">
        <TraceChip label="Source" value={sourceTrace?.source_slug || "n/a"} />
        <TraceChip label="Snapshot" value={shortHash(sourceTrace?.source_snapshot_id) || snapshotMode || "n/a"} />
        <TraceChip label="Revision" value={shortHash(sourceTrace?.source_revision) || "n/a"} />
        <TraceChip label="Fingerprint" value={shortHash(sourceTrace?.source_fingerprint) || "n/a"} />
        <TraceChip label="Prompt" value={shortHash(sourceTrace?.prompt_fingerprint) || "n/a"} />
        {retrievalTrace ? <TraceChip label="Retrieval" value={retrievalTrace.retrieval_mode || "n/a"} /> : null}
        {retrievalTrace ? <TraceChip label="Corpus" value={shortHash(retrievalTrace.corpus_fingerprint) || "n/a"} /> : null}
        <TraceChip label="Started" value={formatDate(startedAt)} />
        <TraceChip label="Completed" value={formatDate(completedAt)} />
        <TraceChip label="Params" value={`${Object.keys(runParameters).length} keys`} />
      </div>
    </div>
  );
}

function TraceChip({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <span className="analysis-chip">
      <span>{label}</span>
      <strong>{value || "n/a"}</strong>
    </span>
  );
}

function InspectorTrace({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="analysis-inspector-row">
      <span>{label}</span>
      <strong>{value || "n/a"}</strong>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="analysis-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MarkdownBlock({ title, value }: { title: string; value: string }) {
  return (
    <div className="analysis-markdown">
      <div className="analysis-card__label">{title}</div>
      <pre className="analysis-pre analysis-pre--narrative">{value}</pre>
    </div>
  );
}

function EvidenceGrid({ items }: { items: EvidenceItem[] }) {
  return (
    <div className="analysis-evidence-grid">
      {items.map((item) => (
        <article className="analysis-evidence" key={`${item.id}-${item.title}`}>
          <div className="analysis-evidence__top">
            <span>{item.id}</span>
            <span className={`analysis-severity analysis-severity--${toneForValue(item.severity)}`}>
              {formatLabel(item.severity)}
            </span>
          </div>
          <h3>{item.title}</h3>
          {item.detail ? <p>{item.detail}</p> : null}
          {item.evidence ? (
            <blockquote>
              <strong>Evidence</strong>
              {item.evidence}
            </blockquote>
          ) : null}
          {item.recommendation ? (
            <p>
              <strong>Recommendation:</strong> {item.recommendation}
            </p>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function RecordList({ records, title }: { records: Record<string, unknown>[]; title: string }) {
  return (
    <div className="stack">
      <h3>{title}</h3>
      <div className="analysis-evidence-grid">
        {records.map((record, index) => (
          <article className="analysis-evidence" key={`${title}-${index}`}>
            <div className="analysis-evidence__top">
              <span>{asString(record.id) || asString(record.voter) || asString(record.persona) || `#${index + 1}`}</span>
              <span className={`analysis-severity analysis-severity--${toneForValue(asString(record.severity) || asString(record.vote))}`}>
                {formatLabel(asString(record.severity) || asString(record.vote))}
              </span>
            </div>
            <h3>{bestRecordTitle(record)}</h3>
            {bestRecordBody(record) ? <p>{bestRecordBody(record)}</p> : null}
            {asRecordArray(record.comments).length ? <RecordList records={asRecordArray(record.comments)} title="Comments" /> : null}
          </article>
        ))}
      </div>
    </div>
  );
}

function StringList({ title, values }: { title: string; values: string[] }) {
  return (
    <div className="stack">
      <h3>{title}</h3>
      <ul className="analysis-list">
        {values.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="analysis-pre">{JSON.stringify(value, null, 2)}</pre>;
}

function buildInspector(analysis: AnalysisRecord) {
  const mainRisks = [
    ...extractEvidenceItems(analysis.structured_output, "layer_2"),
    ...extractEvidenceItems(analysis.structured_output, "layer_1"),
    ...extractEvidenceItems(analysis.structured_output, "findings"),
  ];
  const trailer = asRecord(analysis.predicted_comment_run?.structured_output?.trailer);
  const daRisks = asStringArray(trailer?.key_risks).map((risk, index) => ({
    id: `DA-${index + 1}`,
    title: risk,
    severity: "high",
    evidence: null,
    detail: null,
    recommendation: null,
  }));
  const topRisks = [...mainRisks, ...daRisks]
    .filter((risk) => risk.title)
    .sort((left, right) => severityRank(right.severity) - severityRank(left.severity))
    .slice(0, 5);
  const daDecision = asString(asRecord(analysis.predicted_comment_run?.structured_output?.ic_decision)?.verdict);
  const consultedPages = asStringArray(analysis.predicted_comment_run?.structured_output?.consulted_wiki_pages);
  return { consultedPages, daDecision, topRisks };
}

function extractEvidenceItems(output: Record<string, unknown> | null | undefined, key: string): EvidenceItem[] {
  return asRecordArray(output?.[key]).map((record, index) => {
    const id = asString(record.id) || asString(record.name) || `${index + 1}`;
    const title =
      asString(record.title) ||
      asString(record.name) ||
      asString(record.issue) ||
      asString(record.atomic_issue) ||
      asString(record.risk) ||
      `Item ${index + 1}`;
    const detail =
      asString(record.issue) ||
      asString(record.atomic_issue) ||
      asString(record.risk) ||
      asString(record.impact) ||
      asString(record.explanation);
    return {
      id,
      title,
      severity: asString(record.severity) || asString(record.status),
      evidence: asString(record.evidence),
      detail,
      recommendation: asString(record.recommendation),
    };
  });
}

function extractChecks(output: Record<string, unknown> | null | undefined) {
  return asRecordArray(output?.checks).map((record, index) => ({
    name: asString(record.name) || `Check ${index + 1}`,
    status: asString(record.status) || "unknown",
    explanation: asString(record.explanation),
  }));
}

function summaryFromOutput(output: Record<string, unknown> | null | undefined): string | null {
  const narrative = asRecord(output?.narrative_summary);
  return (
    asString(output?.summary) ||
    asString(narrative?.summary) ||
    asString(narrative?.executive_summary) ||
    asString(narrative?.assessment) ||
    null
  );
}

function pickSummaryOutput(output: Record<string, unknown>) {
  return {
    verdict: output.verdict,
    summary: output.summary,
    narrative_summary: output.narrative_summary,
    findings: output.findings,
    checks: output.checks,
    key_findings: output.key_findings,
  };
}

function bestRecordTitle(record: Record<string, unknown>): string {
  return (
    asString(record.title) ||
    asString(record.question) ||
    asString(record.anchor) ||
    asString(record.voter) ||
    asString(record.persona) ||
    "Structured item"
  );
}

function bestRecordBody(record: Record<string, unknown>): string | null {
  return (
    asString(record.body) ||
    asString(record.comment) ||
    asString(record.rationale) ||
    asString(record.explanation) ||
    asString(record.comment_type)
  );
}

function severityRank(value: string | null): number {
  switch (value) {
    case "critical":
      return 5;
    case "high":
      return 4;
    case "medium":
    case "important":
      return 3;
    case "low":
    case "minor":
      return 2;
    default:
      return 1;
  }
}

function toneForValue(value: string | null | undefined): string {
  if (!value) {
    return "neutral";
  }
  if (["approve", "pass", "completed", "low"].includes(value)) {
    return "good";
  }
  if (["approve_with_conditions", "conditional_approve", "partial", "need_evidence", "medium", "important"].includes(value)) {
    return "warn";
  }
  if (["reject", "rework", "fail", "failed", "critical", "high"].includes(value)) {
    return "bad";
  }
  return "neutral";
}

function shortHash(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  return value.length > 16 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value;
}

function formatNumber(value: number | null): string {
  return value === null ? "-" : new Intl.NumberFormat("en").format(value);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(asRecord(item))) : [];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

const analysisStyles = `
.analysis-workbench {
  width: min(100%, 1480px);
  margin: 0 auto;
  padding: 28px 24px 48px;
  color: #e6edf3;
}

.analysis-workbench h1,
.analysis-workbench h2,
.analysis-workbench h3,
.analysis-workbench p {
  margin: 0;
}

.analysis-workbench h1 {
  font-size: clamp(30px, 4vw, 54px);
  line-height: 1;
}

.analysis-workbench h2 {
  font-size: 18px;
  line-height: 1.25;
}

.analysis-workbench h3 {
  font-size: 15px;
  line-height: 1.35;
}

.analysis-workbench button,
.analysis-workbench .secondary-link {
  border: 1px solid rgba(94, 234, 212, 0.28);
  background: linear-gradient(180deg, #14b8a6 0%, #0f766e 100%);
  color: #f8fafc;
  box-shadow: 0 12px 28px rgba(20, 184, 166, 0.18);
}

.analysis-workbench button:hover:not(:disabled) {
  border-color: rgba(94, 234, 212, 0.55);
  transform: translateY(-1px);
}

.analysis-workbench button:focus-visible,
.analysis-workbench input:focus-visible,
.analysis-workbench select:focus-visible,
.analysis-workbench textarea:focus-visible {
  outline: 3px solid rgba(56, 189, 248, 0.42);
  outline-offset: 2px;
}

.analysis-workbench input,
.analysis-workbench select,
.analysis-workbench textarea {
  border: 1px solid rgba(148, 163, 184, 0.26);
  background: rgba(2, 6, 23, 0.72);
  color: #e2e8f0;
}

.analysis-workbench textarea {
  min-height: 132px;
}

.analysis-workbench label {
  color: #a7b6ca;
}

.analysis-workbench .badge {
  border-color: rgba(148, 163, 184, 0.28);
  background: rgba(15, 23, 42, 0.78);
  color: #cbd5e1;
}

.analysis-workbench .badge.ok {
  border-color: rgba(52, 211, 153, 0.35);
  background: rgba(6, 78, 59, 0.58);
  color: #bbf7d0;
}

.analysis-workbench .badge.info {
  border-color: rgba(56, 189, 248, 0.38);
  background: rgba(12, 74, 110, 0.55);
  color: #bae6fd;
}

.analysis-workbench .badge.danger {
  border-color: rgba(248, 113, 113, 0.44);
  background: rgba(127, 29, 29, 0.55);
  color: #fecaca;
}

.analysis-hero,
.analysis-card,
.analysis-alert,
.analysis-loading {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.96)),
    #020617;
  box-shadow: 0 22px 70px rgba(2, 6, 23, 0.28);
}

.analysis-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
  gap: 18px;
  margin-bottom: 18px;
  padding: 22px;
}

.analysis-hero__main {
  display: grid;
  align-content: start;
  gap: 14px;
}

.analysis-hero__summary,
.analysis-lead {
  max-width: 82ch;
  color: #cbd5e1;
  font-size: 15px;
  line-height: 1.7;
}

.analysis-eyebrow,
.analysis-card__label {
  color: #5eead4;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.analysis-chip-row,
.analysis-trace__grid,
.analysis-action-row,
.analysis-token-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.analysis-chip,
.analysis-token {
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

.analysis-chip span,
.analysis-inspector-row span,
.analysis-metric span {
  color: #7f8ea3;
  font-size: 11px;
  text-transform: uppercase;
}

.analysis-chip strong,
.analysis-inspector-row strong,
.analysis-metric strong {
  color: #f8fafc;
  font-size: 13px;
}

.analysis-verdict,
.analysis-inspector__verdict,
.analysis-severity {
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

.analysis-inspector__verdict {
  min-height: 42px;
  width: fit-content;
  padding: 0 14px;
  font-size: 13px;
}

.analysis-verdict--good,
.analysis-severity--good {
  border: 1px solid rgba(52, 211, 153, 0.4);
  background: rgba(6, 95, 70, 0.72);
  color: #bbf7d0;
}

.analysis-verdict--warn,
.analysis-severity--warn {
  border: 1px solid rgba(251, 191, 36, 0.42);
  background: rgba(120, 53, 15, 0.7);
  color: #fde68a;
}

.analysis-verdict--bad,
.analysis-severity--bad {
  border: 1px solid rgba(248, 113, 113, 0.46);
  background: rgba(127, 29, 29, 0.7);
  color: #fecaca;
}

.analysis-verdict--neutral,
.analysis-severity--neutral {
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(30, 41, 59, 0.78);
  color: #cbd5e1;
}

.analysis-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 18px;
  align-items: start;
}

.analysis-main,
.stack {
  display: grid;
  gap: 14px;
}

.analysis-inspector {
  position: sticky;
  top: 18px;
  display: grid;
  gap: 14px;
}

.analysis-card,
.analysis-alert,
.analysis-loading {
  padding: 18px;
}

.analysis-alert {
  margin-bottom: 14px;
  border-color: rgba(248, 113, 113, 0.42);
  color: #fecaca;
}

.analysis-loading {
  color: #94a3b8;
}

.analysis-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.72);
  padding: 6px;
}

.analysis-tab {
  min-height: 38px;
  border-color: transparent !important;
  background: transparent !important;
  box-shadow: none !important;
  color: #94a3b8 !important;
}

.analysis-tab--active {
  border-color: rgba(94, 234, 212, 0.32) !important;
  background: rgba(20, 184, 166, 0.16) !important;
  color: #f8fafc !important;
}

.analysis-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.analysis-section-heading p,
.analysis-muted,
.analysis-evidence p,
.analysis-check p,
.analysis-risk p,
.analysis-split p {
  color: #9fb0c4;
  font-size: 13px;
  line-height: 1.6;
}

.analysis-pre {
  max-height: 520px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.7);
  color: #dbeafe;
  padding: 14px;
  font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.analysis-pre--narrative {
  max-height: none;
  color: #e2e8f0;
}

.analysis-evidence-grid,
.analysis-check-grid,
.analysis-callout-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 12px;
}

.analysis-evidence,
.analysis-check,
.analysis-callout,
.analysis-risk,
.analysis-metric {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.62);
  padding: 14px;
}

.analysis-evidence {
  display: grid;
  gap: 10px;
}

.analysis-evidence__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #7dd3fc;
  font: 12px/1.2 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.analysis-evidence blockquote {
  display: grid;
  gap: 4px;
  margin: 0;
  border-left: 3px solid rgba(94, 234, 212, 0.6);
  padding-left: 10px;
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.55;
}

.analysis-check,
.analysis-callout,
.analysis-risk {
  display: grid;
  gap: 8px;
}

.analysis-score-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.analysis-metric {
  display: grid;
  gap: 4px;
}

.analysis-inspector-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  padding-bottom: 8px;
}

.analysis-inspector-row strong {
  max-width: 210px;
  overflow-wrap: anywhere;
  text-align: right;
}

.analysis-risk-list {
  display: grid;
  gap: 10px;
}

.analysis-details {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.38);
  padding: 10px;
}

.analysis-details summary {
  cursor: pointer;
  color: #bae6fd;
  font-weight: 700;
}

.analysis-details .analysis-pre {
  margin-top: 10px;
}

.analysis-split {
  display: grid;
  grid-template-columns: minmax(180px, 0.35fr) minmax(0, 1fr);
  gap: 12px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.62);
  padding: 14px;
}

.analysis-checkbox {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 10px;
  color: #dbeafe !important;
}

.analysis-checkbox input {
  min-height: auto;
  width: auto;
}

.analysis-success {
  color: #86efac;
}

.analysis-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 20px;
  color: #dbeafe;
}

.analysis-trace {
  display: grid;
  gap: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.45);
  padding: 12px;
}

.analysis-trace__title {
  color: #a7f3d0;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.analysis-wrap {
  overflow-wrap: anywhere;
}

@media (max-width: 1080px) {
  .analysis-hero,
  .analysis-layout {
    grid-template-columns: 1fr;
  }

  .analysis-inspector {
    position: static;
  }
}

@media (max-width: 640px) {
  .analysis-workbench {
    width: 100%;
    padding: 18px 10px 32px;
  }

  .analysis-hero,
  .analysis-card {
    padding: 14px;
  }

  .analysis-split,
  .analysis-score-grid {
    grid-template-columns: 1fr;
  }
}
`;
