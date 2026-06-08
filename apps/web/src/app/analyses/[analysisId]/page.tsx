"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { getAnalysis, type AnalysisRecord } from "@/lib/api/documents";
import { createEtalonDraft } from "@/lib/api/etalons";
import { submitFeedback } from "@/lib/api/feedback";
import { formatDate, formatLabel } from "@/lib/format";

export default function AnalysisDetailPage() {
  const params = useParams<{ analysisId: string }>();
  const [analysis, setAnalysis] = useState<AnalysisRecord | null>(null);
  const [error, setError] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [usefulness, setUsefulness] = useState<"useful" | "partially_useful" | "useless">("useful");
  const [canUseForBenchmark, setCanUseForBenchmark] = useState(false);
  const [etalonPending, setEtalonPending] = useState(false);

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

  return (
    <AppShell>
      <main className="main stack">
        {error ? <section className="panel error">{error}</section> : null}
        {analysis ? (
          <>
            <section className="panel stack">
              <div className="toolbar">
                <div>
                  <h1>Analysis</h1>
                  <p className="muted">
                    {analysis.skill_name} · {analysis.provider} · {analysis.model}
                  </p>
                </div>
                <StatusBadge status={analysis.status} />
              </div>
              <div className="meta-grid">
                <div>
                  <div className="muted small">Verdict</div>
                  <strong>{formatLabel(analysis.verdict)}</strong>
                </div>
                <div>
                  <div className="muted small">Created</div>
                  <strong>{formatDate(analysis.created_at)}</strong>
                </div>
                <div>
                  <div className="muted small">Skill version</div>
                  <strong>{analysis.skill_version}</strong>
                </div>
              </div>
              {analysis.source_trace ? (
                <div className="meta-grid">
                  <TraceItem label="Source" value={analysis.source_trace.source_slug} />
                  <TraceItem label="Snapshot" value={shortHash(analysis.source_trace.source_snapshot_id)} />
                  <TraceItem label="Fingerprint" value={shortHash(analysis.source_trace.source_fingerprint)} />
                  <TraceItem label="Prompt" value={shortHash(analysis.source_trace.prompt_fingerprint)} />
                </div>
              ) : null}
              {analysis.summary ? <p>{analysis.summary}</p> : null}
              {analysis.error_message ? <div className="error">{analysis.error_message}</div> : null}
              <div className="button-row">
                <button disabled={etalonPending || analysis.status !== "completed"} type="button" onClick={createDraft}>
                  Create etalon draft
                </button>
              </div>
            </section>
            <section className="panel stack">
              <h2>Gate Challenger</h2>
              <MainAnalysisOutput output={analysis.structured_output} />
            </section>
            {analysis.predicted_comment_run ? (
              <section className="panel stack">
                <div className="toolbar">
                  <div>
                    <h2>Devil&apos;s Advocate</h2>
                    <p className="muted">
                      {analysis.predicted_comment_run.skill_name} · {analysis.predicted_comment_run.provider} ·{" "}
                      {analysis.predicted_comment_run.model}
                    </p>
                  </div>
                  <StatusBadge status={analysis.predicted_comment_run.status} />
                </div>
                {analysis.predicted_comment_run.error_message ? (
                  <div className="error">{analysis.predicted_comment_run.error_message}</div>
                ) : null}
                {analysis.predicted_comment_run.source_trace || analysis.predicted_comment_run.retrieval_trace ? (
                  <div className="meta-grid">
                    <TraceItem
                      label="DA source"
                      value={analysis.predicted_comment_run.source_trace?.source_slug}
                    />
                    <TraceItem
                      label="DA snapshot"
                      value={shortHash(analysis.predicted_comment_run.source_trace?.source_snapshot_id)}
                    />
                    <TraceItem
                      label="Retrieval"
                      value={analysis.predicted_comment_run.retrieval_trace?.retrieval_mode}
                    />
                    <TraceItem
                      label="Corpus"
                      value={shortHash(analysis.predicted_comment_run.retrieval_trace?.corpus_fingerprint)}
                    />
                  </div>
                ) : null}
                <PredictedCommentsOutput output={analysis.predicted_comment_run.structured_output} />
                {analysis.predicted_comment_run.raw_output ? (
                  <>
                    <h3>Raw Devil&apos;s Advocate Output</h3>
                    <pre className="text-preview">{analysis.predicted_comment_run.raw_output}</pre>
                  </>
                ) : null}
              </section>
            ) : null}
            {analysis.raw_output ? (
              <section className="panel stack">
                <h2>Raw Output</h2>
                <pre className="text-preview">{analysis.raw_output}</pre>
              </section>
            ) : null}
            <section className="panel stack">
              <h2>Feedback</h2>
              <div className="form-grid">
                <label>
                  Usefulness
                  <select value={usefulness} onChange={(event) => setUsefulness(event.target.value as typeof usefulness)}>
                    <option value="useful">Useful</option>
                    <option value="partially_useful">Partially useful</option>
                    <option value="useless">Useless</option>
                  </select>
                </label>
                <label className="checkbox-label">
                  <input
                    checked={canUseForBenchmark}
                    type="checkbox"
                    onChange={(event) => setCanUseForBenchmark(event.target.checked)}
                  />
                  Use for benchmark review
                </label>
              </div>
              <label>
                Comment
                <textarea value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)} />
              </label>
              <div className="button-row">
                <button type="button" onClick={sendFeedback}>
                  Submit feedback
                </button>
                {feedbackStatus ? <span className="muted">{feedbackStatus}</span> : null}
              </div>
            </section>
          </>
        ) : (
          <section className="panel muted">Loading...</section>
        )}
      </main>
    </AppShell>
  );
}

function TraceItem({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div className="muted small">{label}</div>
      <strong>{value || "n/a"}</strong>
    </div>
  );
}

function shortHash(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  return value.length > 16 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value;
}

function MainAnalysisOutput({ output }: { output: Record<string, unknown> | null }) {
  if (!output) {
    return <p className="muted">No Gate Challenger output yet.</p>;
  }

  const assessment = asString(output.assessment_markdown);
  const layer1 = asString(output.layer_1_markdown);
  const layer2 = asString(output.layer_2_markdown);
  const hasNativeGateOutput = Boolean(assessment || layer1 || layer2);

  return (
    <div className="stack">
      {assessment ? <pre className="text-preview narrative-output">{assessment}</pre> : null}
      {layer1 ? <pre className="text-preview narrative-output">{layer1}</pre> : null}
      {layer2 ? <pre className="text-preview narrative-output">{layer2}</pre> : null}
      {hasNativeGateOutput ? (
        <details>
          <summary>Structured Gate Challenger JSON</summary>
          <pre className="text-preview">{JSON.stringify(output, null, 2)}</pre>
        </details>
      ) : (
        <pre className="text-preview">{JSON.stringify(output, null, 2)}</pre>
      )}
    </div>
  );
}

function PredictedCommentsOutput({ output }: { output: Record<string, unknown> | null }) {
  if (!output) {
    return <p className="muted">No predicted comments output yet.</p>;
  }

  const nativeMarkdown = asString(output.native_markdown);
  const icDecision = asRecord(output.ic_decision);
  const trailer = asRecord(output.trailer);
  const predictedQuestions = asStringArray(output.predicted_questions);
  const consultedPages = asStringArray(output.consulted_wiki_pages);

  if (nativeMarkdown) {
    return (
      <div className="stack">
        <pre className="text-preview narrative-output">{nativeMarkdown}</pre>
        <details>
          <summary>Structured Devil&apos;s Advocate JSON</summary>
          <pre className="text-preview">{JSON.stringify(output, null, 2)}</pre>
        </details>
      </div>
    );
  }

  return (
    <div className="stack">
      {icDecision ? (
        <div className="meta-grid">
          <div>
            <div className="muted small">IC decision</div>
            <strong>{formatLabel(asString(icDecision.verdict))}</strong>
          </div>
          <div>
            <div className="muted small">Run mode</div>
            <strong>{formatLabel(asString(output.run_mode))}</strong>
          </div>
        </div>
      ) : null}
      {icDecision?.rationale ? <p>{asString(icDecision.rationale)}</p> : null}
      {trailer?.executive_summary ? <p>{asString(trailer.executive_summary)}</p> : null}
      {predictedQuestions.length ? (
        <div>
          <h3>Predicted Questions</h3>
          <ul>
            {predictedQuestions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {consultedPages.length ? <p className="muted small">Consulted pages: {consultedPages.join(", ")}</p> : null}
      <details>
        <summary>Full Devil&apos;s Advocate output</summary>
        <pre className="text-preview">{JSON.stringify(output, null, 2)}</pre>
      </details>
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}
