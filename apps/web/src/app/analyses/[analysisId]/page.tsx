"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { MarkdownPreview } from "@/components/MarkdownPreview";
import { StatusBadge } from "@/components/StatusBadge";
import {
  createAnalysisDetails,
  deleteAnalysis,
  getAnalysis,
  getDocument,
  getParsedText,
  type AnalysisRecord,
  type DocumentRecord,
  type PredictedCommentRunRecord,
  type RetrievalTrace,
  type SourceTrace,
} from "@/lib/api/documents";
import { submitFeedback } from "@/lib/api/feedback";
import { formatDate, formatLabel } from "@/lib/format";
import {
  analysisGateDetailsOutput,
  analysisShortSummary,
  buildDocumentCommentAnchors,
  buildLayeredGateChecks,
  devilsAdvocateRoleComments,
  type DocumentCommentAnchor,
  type LayeredGateCheck,
  type LayeredGateLayer2Check,
  type DevilsAdvocateRoleComment,
  splitDevilsAdvocateMarkdown,
  stripAssessmentHeading,
} from "./analysisDisplay";
import { usefulnessForFeedbackRating, type FeedbackUsefulness } from "./feedbackDisplay";

type AnalysisTab = "mainOutput" | "documentComments" | "fullOutput";

type EvidenceItem = {
  id: string;
  title: string;
  severity: string | null;
  evidence: string | null;
  detail: string | null;
  recommendation: string | null;
};

const analysisTabs: Array<{ id: AnalysisTab; label: string }> = [
  { id: "mainOutput", label: "Gate Challenger" },
  { id: "documentComments", label: "Document comments" },
  { id: "fullOutput", label: "Full Output" },
];

const feedbackRatings = [
  { value: 1, label: "Not useful" },
  { value: 2, label: "Slightly useful" },
  { value: 3, label: "Neutral" },
  { value: 4, label: "Useful" },
  { value: 5, label: "Very useful" },
] as const;

const ANALYSIS_POLL_INTERVAL_MS = 5000;

type FeedbackRating = (typeof feedbackRatings)[number]["value"];

export default function AnalysisDetailPage() {
  const params = useParams<{ analysisId: string }>();
  const [analysis, setAnalysis] = useState<AnalysisRecord | null>(null);
  const [analysisDocument, setAnalysisDocument] = useState<DocumentRecord | null>(null);
  const [parsedDocumentText, setParsedDocumentText] = useState<string | null>(null);
  const [parsedDocumentError, setParsedDocumentError] = useState("");
  const [error, setError] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [feedbackRating, setFeedbackRating] = useState<FeedbackRating>(4);
  const [usefulness, setUsefulness] = useState<FeedbackUsefulness>("useful");
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<AnalysisTab>("mainOutput");
  const [runDetailsOpen, setRunDetailsOpen] = useState(false);
  const [isRefreshingAnalysis, setIsRefreshingAnalysis] = useState(false);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [isDeletingAnalysis, setIsDeletingAnalysis] = useState(false);

  useEffect(() => {
    let ignore = false;
    setAnalysis(null);
    setError("");
    getAnalysis(params.analysisId)
      .then((loadedAnalysis) => {
        if (!ignore) {
          setAnalysis(loadedAnalysis);
          setError("");
        }
      })
      .catch((err) => {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load analysis");
        }
      });

    return () => {
      ignore = true;
    };
  }, [params.analysisId]);

  useEffect(() => {
    if (!isAnalysisRefreshPending(analysis)) {
      return;
    }

    let ignore = false;
    async function refreshAnalysis() {
      setIsRefreshingAnalysis(true);
      try {
        const refreshedAnalysis = await getAnalysis(params.analysisId);
        if (!ignore) {
          setAnalysis(refreshedAnalysis);
          setError("");
        }
      } catch (err) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to refresh analysis");
        }
      } finally {
        if (!ignore) {
          setIsRefreshingAnalysis(false);
        }
      }
    }

    const intervalId = window.setInterval(refreshAnalysis, ANALYSIS_POLL_INTERVAL_MS);
    return () => {
      ignore = true;
      window.clearInterval(intervalId);
    };
  }, [analysis?.status, analysis?.predicted_comment_run?.status, analysis?.detail_run?.status, params.analysisId]);

  useEffect(() => {
    if (!analysis?.document_id) {
      setAnalysisDocument(null);
      setParsedDocumentText(null);
      setParsedDocumentError("");
      return;
    }

    let ignore = false;
    setAnalysisDocument(null);
    setParsedDocumentText(null);
    setParsedDocumentError("");
    getDocument(analysis.document_id)
      .then((document) => {
        if (!ignore) {
          setAnalysisDocument(document);
        }
      })
      .catch(() => {
        if (!ignore) {
          setAnalysisDocument(null);
        }
      });
    getParsedText(analysis.document_id)
      .then((text) => {
        if (!ignore) {
          setParsedDocumentText(text);
        }
      })
      .catch((err) => {
        if (!ignore) {
          setParsedDocumentError(err instanceof Error ? err.message : "Failed to load parsed document text");
        }
      });

    return () => {
      ignore = true;
    };
  }, [analysis?.document_id]);

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
        can_use_for_benchmark: false,
      });
      setFeedbackStatus("Feedback saved");
      setFeedbackComment("");
      setFeedbackOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit feedback");
    }
  }

  async function loadAnalysisDetails() {
    if (!analysis) {
      return;
    }
    setIsLoadingDetails(true);
    setError("");
    try {
      const detailRun = await createAnalysisDetails(analysis.id);
      setAnalysis((current) => (current?.id === analysis.id ? { ...current, detail_run: detailRun } : current));
      if (isActiveRunStatus(detailRun.status)) {
        setActiveTab("fullOutput");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analysis details");
    } finally {
      setIsLoadingDetails(false);
    }
  }

  async function deleteCurrentAnalysis() {
    if (!analysis) {
      return;
    }
    if (!window.confirm(`Delete analysis for "${analysisDocument?.title || "this document"}"?`)) {
      return;
    }

    setIsDeletingAnalysis(true);
    setError("");
    try {
      await deleteAnalysis(analysis.id);
      window.location.href = `/documents/${analysis.document_id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete analysis");
      setIsDeletingAnalysis(false);
    }
  }

  function chooseFeedbackRating(rating: FeedbackRating) {
    setFeedbackRating(rating);
    setUsefulness(usefulnessForFeedbackRating(rating));
  }

  useEffect(() => {
    if (!runDetailsOpen) {
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setRunDetailsOpen(false);
      }
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [runDetailsOpen]);

  useEffect(() => {
    if (!feedbackOpen) {
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setFeedbackOpen(false);
      }
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [feedbackOpen]);

  return (
    <AppShell>
      <main className="analysis-workbench">
        <style>{`${analysisStyles}\n${paperAnalysisOverrides}`}</style>
        {error ? <section className="analysis-alert">{error}</section> : null}
        {analysis ? (
          <>
            <section className="analysis-hero">
              <div className="analysis-hero__main">
                <div className="analysis-hero__title-row">
                  <div className="analysis-hero__title-copy">
                    <h1>{analysisDocument?.title ? `Analysis: ${analysisDocument.title}` : "Analysis"}</h1>
                    <p className="analysis-hero__date">{formatDate(analysis.created_at)}</p>
                  </div>
                  <div className="analysis-hero__actions">
                    <button className="analysis-secondary-action analysis-run-details-action" type="button" onClick={() => setRunDetailsOpen(true)}>
                      Run details
                    </button>
                    <button
                      className="analysis-danger-action"
                      disabled={isDeletingAnalysis}
                      type="button"
                      onClick={deleteCurrentAnalysis}
                    >
                      {isDeletingAnalysis ? "Deleting" : "Delete"}
                    </button>
                  </div>
                </div>
                <div className="analysis-chip-row">
                  <span className={`analysis-verdict analysis-verdict--${toneForValue(analysis.verdict)}`}>
                    {formatLabel(analysis.verdict)}
                  </span>
                  <StatusBadge status={analysis.status} />
                </div>
              </div>
            </section>

            {runDetailsOpen ? <RunDetailsDialog analysis={analysis} onClose={() => setRunDetailsOpen(false)} /> : null}

            {analysis.error_message ? <section className="analysis-alert">{analysis.error_message}</section> : null}

            {isAnalysisRefreshPending(analysis) ? (
              <AnalysisWaitingPanel analysis={analysis} isRefreshing={isRefreshingAnalysis} />
            ) : null}

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

                {activeTab === "mainOutput" ? <MainSkillMarkdownPanel analysis={analysis} /> : null}
                {activeTab === "documentComments" ? (
                  <DocumentCommentsPanel
                    documentTitle={analysisDocument?.title || "Source document"}
                    parsedText={parsedDocumentText}
                    parsedTextError={parsedDocumentError}
                    run={analysis.predicted_comment_run}
                  />
                ) : null}
                {activeTab === "fullOutput" ? (
                  <FullOutputPanel
                    analysis={analysis}
                    isLoadingDetails={isLoadingDetails}
                    onLoadDetails={loadAnalysisDetails}
                  />
                ) : null}
              </section>
            </div>

            <button
              aria-expanded={feedbackOpen}
              aria-haspopup="dialog"
              className={
                feedbackStatus
                  ? "analysis-feedback-fab analysis-feedback-fab--saved"
                  : "analysis-feedback-fab"
              }
              type="button"
              onClick={() => setFeedbackOpen(true)}
            >
              {feedbackStatus || "Leave feedback"}
            </button>

            {feedbackOpen ? (
              <FeedbackSheet
                feedbackComment={feedbackComment}
                feedbackRating={feedbackRating}
                feedbackStatus={feedbackStatus}
                onChangeComment={setFeedbackComment}
                onChooseRating={chooseFeedbackRating}
                onClose={() => setFeedbackOpen(false)}
                onSubmit={sendFeedback}
              />
            ) : null}
          </>
        ) : (
          <section className="analysis-loading">Loading...</section>
        )}
      </main>
    </AppShell>
  );
}

function FeedbackSheet({
  feedbackComment,
  feedbackRating,
  feedbackStatus,
  onChangeComment,
  onChooseRating,
  onClose,
  onSubmit,
}: {
  feedbackComment: string;
  feedbackRating: FeedbackRating;
  feedbackStatus: string;
  onChangeComment: (value: string) => void;
  onChooseRating: (rating: FeedbackRating) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="analysis-feedback-sheet-backdrop" role="presentation" onClick={onClose}>
      <section
        aria-labelledby="analysis-feedback-title"
        aria-modal="true"
        className="analysis-feedback-sheet stack"
        role="dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="analysis-feedback-sheet__header">
          <h2 id="analysis-feedback-title">Feedback</h2>
          <button className="analysis-secondary-action" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="analysis-feedback-field">
          <span className="analysis-feedback-label">How useful was this analysis?</span>
          <div className="analysis-feedback-rating" role="radiogroup" aria-label="How useful was this analysis?">
            {feedbackRatings.map((rating) => (
              <button
                aria-checked={feedbackRating === rating.value}
                aria-label={rating.label}
                className={
                  feedbackRating === rating.value
                    ? "analysis-feedback-rating__button analysis-feedback-rating__button--selected"
                    : "analysis-feedback-rating__button"
                }
                key={rating.value}
                role="radio"
                title={rating.label}
                type="button"
                onClick={() => onChooseRating(rating.value)}
              >
                <FeedbackFaceIcon rating={rating.value} />
              </button>
            ))}
          </div>
        </div>
        <label className="analysis-feedback-field">
          <span className="analysis-feedback-label">Your comments (optional)</span>
          <textarea
            className="analysis-feedback-textarea"
            maxLength={1000}
            placeholder="Good coverage of key risks. Need more evidence on long-term deterrence and adversarial testing results."
            value={feedbackComment}
            onChange={(event) => onChangeComment(event.target.value)}
          />
        </label>
        <div className="analysis-feedback-footer">
          <span>{feedbackComment.length} / 1000</span>
        </div>
        <div className="analysis-feedback-actions">
          <button className="analysis-feedback-submit" type="button" onClick={onSubmit}>
            Submit feedback
          </button>
          {feedbackStatus ? <span className="analysis-success">{feedbackStatus}</span> : null}
        </div>
      </section>
    </div>
  );
}

function FeedbackFaceIcon({ rating }: { rating: FeedbackRating }) {
  const mouthPath =
    rating === 1
      ? "M8 15.6C9.15 14.2 10.47 13.5 12 13.5C13.53 13.5 14.85 14.2 16 15.6"
      : rating === 2
        ? "M8.8 15C9.72 14.15 10.78 13.72 12 13.72C13.22 13.72 14.28 14.15 15.2 15"
        : rating === 3
          ? "M8.8 14.1H15.2"
          : rating === 4
            ? "M8.6 13.5C9.65 14.65 10.78 15.22 12 15.22C13.22 15.22 14.35 14.65 15.4 13.5"
            : "M8.4 13.2C9.45 14.78 10.65 15.58 12 15.58C13.35 15.58 14.55 14.78 15.6 13.2";

  return (
    <svg aria-hidden="true" className="analysis-feedback-face" fill="none" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="9" cy="10.5" r="1.05" fill="currentColor" />
      <circle cx="15" cy="10.5" r="1.05" fill="currentColor" />
      <path d={mouthPath} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
    </svg>
  );
}

function AnalysisWaitingPanel({
  analysis,
  isRefreshing,
}: {
  analysis: AnalysisRecord;
  isRefreshing: boolean;
}) {
  const activeStatus = isActiveRunStatus(analysis.status)
    ? analysis.status
    : analysis.predicted_comment_run?.status || analysis.status;
  let title = "Finishing analysis";
  let detail = "The main result is ready while the remaining output finishes.";

  if (analysis.status === "queued") {
    title = "Analysis queued";
    detail = "The run is waiting for a worker. Output will appear when processing completes.";
  }
  if (analysis.status === "running") {
    title = "Analysis running";
    detail = "Gate Challenger is processing the document. Output will appear when the run completes.";
  }

  return (
    <section className="analysis-card analysis-waiting" aria-live="polite">
      <span className="analysis-waiting__spinner" aria-hidden="true" />
      <div className="analysis-waiting__copy">
        <h2>{title}</h2>
        <p>{detail}</p>
        <span>{isRefreshing ? "Refreshing status" : "Waiting for output"}</span>
      </div>
      <StatusBadge status={activeStatus} />
    </section>
  );
}

function RunDetailsDialog({ analysis, onClose }: { analysis: AnalysisRecord; onClose: () => void }) {
  return (
    <div className="analysis-modal-backdrop" role="presentation" onClick={onClose}>
      <section
        aria-labelledby="analysis-run-details-title"
        aria-modal="true"
        className="analysis-modal stack"
        role="dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="analysis-modal__header">
          <div>
            <div className="analysis-card__label">Run metadata</div>
            <h2 id="analysis-run-details-title">Run details</h2>
          </div>
          <button className="analysis-secondary-action" type="button" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="analysis-modal__chips">
          <TraceChip label="Provider" value={formatLabel(analysis.provider)} />
          <TraceChip label="Model" value={analysis.model} />
          <TraceChip label="Skill" value={`${analysis.skill_name} · ${analysis.skill_version}`} />
          <TraceChip label="Created" value={formatDate(analysis.created_at)} />
        </div>

        <div className="analysis-score-grid analysis-score-grid--modal">
          <Metric label="Input" value={formatNumber(analysis.input_tokens)} />
          <Metric label="Output" value={formatNumber(analysis.output_tokens)} />
          <Metric label="Latency" value={analysis.latency_ms ? `${analysis.latency_ms} ms` : "-"} />
          <Metric label="Cost" value={analysis.estimated_cost ?? "-"} />
        </div>

        <TracePanel
          title="Run trace"
          sourceTrace={analysis.source_trace}
          runParameters={analysis.run_parameters}
          startedAt={analysis.started_at}
          completedAt={analysis.completed_at}
        />

        <details className="analysis-details">
          <summary>Run parameters</summary>
          <JsonBlock value={analysis.run_parameters} />
        </details>
      </section>
    </div>
  );
}

function MainSkillMarkdownPanel({ analysis }: { analysis: AnalysisRecord }) {
  const sections = mainSkillMarkdownSections(analysis);
  const layeredChecks = buildLayeredGateChecks(analysis.structured_output);
  const hasDetailedChecks = layeredChecks.length > 0 || Boolean(sections.layer1 || sections.layer2);
  const shortSummary = analysisShortSummary(analysis);

  return (
    <section className="analysis-card stack">
      <div className="analysis-section-heading">
        <div>
          <h2>Gate Challenger</h2>
        </div>
        <StatusBadge status={analysis.status} />
      </div>
      {analysis.error_message ? <div className="analysis-alert">{analysis.error_message}</div> : null}
      {shortSummary ? (
        <section className="analysis-short-summary" aria-label="short summary">
          <h3>Short summary</h3>
          <p>{shortSummary}</p>
        </section>
      ) : null}
      {sections.main ? (
        <MarkdownPreview markdown={sections.main} className="gc-markdown-preview--narrative" />
      ) : hasDetailedChecks ? (
        <p className="analysis-muted">Main analysis text is unavailable. Detailed checks are available in Full Output.</p>
      ) : (
        <p className="analysis-muted">No markdown output is available for this run yet.</p>
      )}
    </section>
  );
}

function DetailedGateChecksOutput({ analysis }: { analysis: AnalysisRecord }) {
  const sections = gateDetailsMarkdownSections(analysis);
  const layeredChecks = buildLayeredGateChecks(analysisGateDetailsOutput(analysis));
  const hasStructuredDetailedChecks = layeredChecks.length > 0;
  const hasDetailedChecks = hasStructuredDetailedChecks || Boolean(sections.layer1 || sections.layer2);

  if (!hasDetailedChecks) {
    return null;
  }

  return (
    <section className="analysis-detail-checks analysis-full-output-section" aria-label="Detailed checks">
      <h3>Detailed checks</h3>
      {hasStructuredDetailedChecks ? (
        <LayeredGateChecks groups={layeredChecks} />
      ) : (
        <>
          {sections.layer1 ? <CollapsibleMarkdown title="Layer 1" markdown={sections.layer1} /> : null}
          {sections.layer2 ? <CollapsibleMarkdown title="Layer 2" markdown={sections.layer2} /> : null}
        </>
      )}
    </section>
  );
}

function LayeredGateChecks({ groups }: { groups: LayeredGateCheck[] }) {
  return (
    <div className="analysis-layered-checks">
      {groups.map((group, index) => {
        const hasMaterialLayer1Finding = group.issue !== "No material issue" || Boolean(group.evidence || group.severity);
        return (
          <details className="analysis-layer-group" key={group.id} open={index === 0}>
            <summary>
              <span className="analysis-layer-group__summary">
                <span>{displayLayer1Id(group.id)}</span>
                <strong>{group.title}</strong>
                {group.description ? <small>{group.description}</small> : null}
              </span>
              <LayerStatusBadge value={group.status} fallbackValue={group.severity} />
            </summary>
            <div className="analysis-layer-group__body">
              {hasMaterialLayer1Finding ? (
                <div className="analysis-layer-finding-card" aria-label={`Layer 1 ${group.id} details`}>
                  <div className="analysis-layer-card-heading">
                    <span>Layer 1 finding</span>
                    {group.severity ? <LayerStatusBadge value={group.severity} label={`Severity ${group.severity}`} /> : null}
                  </div>
                  <div className="analysis-layer-fields">
                    {group.issue !== "No material issue" ? <LabeledText label="Issue" value={group.issue} /> : null}
                    {group.evidence ? <LabeledText label="Evidence" value={group.evidence} /> : null}
                  </div>
                </div>
              ) : (
                <div className="analysis-layer-clear-state">
                  <strong>No Layer 1 issue</strong>
                  <span>This block is PASS, so there is no problem card to show.</span>
                </div>
              )}
              <div className="analysis-layer2-list">
                <div className="analysis-layer-card-heading">
                  <span>Layer 2 checks</span>
                  <small>{group.layer2.length} linked check{group.layer2.length === 1 ? "" : "s"}</small>
                </div>
                {group.layer2.length ? (
                  group.layer2.map((item) => <Layer2Question key={item.id} item={item} />)
                ) : (
                  <p className="analysis-muted">No linked Layer 2 checks.</p>
                )}
              </div>
            </div>
          </details>
        );
      })}
    </div>
  );
}

function Layer2Question({ item }: { item: LayeredGateLayer2Check }) {
  const showPrimaryDetails = Boolean(item.issue || item.evidence);
  const displayId = displayLayer2Id(item.id);

  return (
    <article className="analysis-layer2-question">
      <div className="analysis-layer2-question__top">
        <div>
          {displayId ? <span>{displayId}</span> : null}
          <h4>{item.question}</h4>
        </div>
        <LayerStatusBadge value={item.status} fallbackValue={item.severity} label={item.answer ?? undefined} />
      </div>
      {showPrimaryDetails ? (
        <div className="analysis-layer-fields analysis-layer-fields--compact">
          {item.issue && item.issue !== "No material issue" ? <LabeledText label="Issue" value={item.issue} /> : null}
          {item.evidence ? <LabeledText label="Evidence" value={item.evidence} /> : null}
        </div>
      ) : null}
    </article>
  );
}

function LayerStatusBadge({
  value,
  fallbackValue,
  label,
}: {
  value: string | null | undefined;
  fallbackValue?: string | null | undefined;
  label?: string;
}) {
  const displayValue = value || fallbackValue;
  return (
    <span className={`analysis-answer analysis-answer--${toneForValue(displayValue)}`}>
      {(label || (value ? value.toUpperCase() : fallbackValue ? `SEVERITY ${fallbackValue.toUpperCase()}` : "NO STATUS")).toUpperCase()}
    </span>
  );
}

function DocumentCommentsPanel({
  documentTitle,
  parsedText,
  parsedTextError,
  run,
}: {
  documentTitle: string;
  parsedText: string | null;
  parsedTextError: string;
  run: PredictedCommentRunRecord | null;
}) {
  const anchorRefs = useRef<Record<string, HTMLSpanElement | null>>({});
  const cardRefs = useRef<Record<string, HTMLElement | null>>({});
  const roleComments = useMemo(() => devilsAdvocateRoleComments(run?.structured_output), [run?.structured_output]);
  const documentComments = useMemo(
    () => buildDocumentCommentAnchors(parsedText, roleComments),
    [parsedText, roleComments],
  );
  const [activeAnchorId, setActiveAnchorId] = useState<string | null>(documentComments.anchors[0]?.id ?? null);
  const commentById = useMemo(
    () => new Map(roleComments.map((comment) => [comment.id, comment])),
    [roleComments],
  );
  const anchorByCommentId = useMemo(() => {
    const map = new Map<string, DocumentCommentAnchor>();
    for (const anchor of documentComments.anchors) {
      for (const commentId of anchor.commentIds) {
        map.set(commentId, anchor);
      }
    }
    return map;
  }, [documentComments.anchors]);
  const orderedComments = useMemo(() => {
    const matchedComments = documentComments.anchors.flatMap((anchor) =>
      anchor.commentIds.map((commentId) => commentById.get(commentId)).filter((comment): comment is DevilsAdvocateRoleComment => Boolean(comment)),
    );
    return [...matchedComments, ...documentComments.unmatchedComments];
  }, [commentById, documentComments.anchors, documentComments.unmatchedComments]);

  useEffect(() => {
    if (!documentComments.anchors.length) {
      setActiveAnchorId(null);
      return;
    }
    if (!activeAnchorId || !documentComments.anchors.some((anchor) => anchor.id === activeAnchorId)) {
      setActiveAnchorId(documentComments.anchors[0].id);
    }
  }, [activeAnchorId, documentComments.anchors]);

  function selectAnchor(anchorId: string | null, source: "card" | "document") {
    if (!anchorId) {
      return;
    }
    setActiveAnchorId(anchorId);
    window.requestAnimationFrame(() => {
      const target = source === "card" ? anchorRefs.current[anchorId] : cardRefs.current[anchorId];
      target?.scrollIntoView({ behavior: "smooth", block: source === "card" ? "center" : "nearest" });
    });
  }

  if (!run) {
    return (
      <section className="analysis-card stack">
        <h2>Document comments</h2>
        <p className="analysis-muted">No Devil&apos;s Advocate role comments are attached yet.</p>
      </section>
    );
  }

  return (
    <section className="analysis-document-comments">
      <article className="analysis-document-panel" aria-label="Source document">
        <header className="analysis-document-panel__header">
          <h2>{documentTitle}</h2>
          <p>Source document with Devil&apos;s Advocate comments anchored to exact parsed text fragments.</p>
        </header>
        {parsedTextError ? <div className="analysis-alert">{parsedTextError}</div> : null}
        {!parsedText && !parsedTextError ? <p className="analysis-muted">Loading parsed document text...</p> : null}
        {parsedText ? (
          <div className="analysis-document-text">
            {documentComments.segments.map((segment) =>
              segment.anchorId ? (
                <span
                  aria-pressed={activeAnchorId === segment.anchorId}
                  className={
                    activeAnchorId === segment.anchorId
                      ? `analysis-document-anchor analysis-document-anchor--${segment.tone} analysis-document-anchor--active`
                      : `analysis-document-anchor analysis-document-anchor--${segment.tone}`
                  }
                  data-count={segment.commentCount}
                  key={segment.id}
                  ref={(element) => {
                    anchorRefs.current[segment.anchorId || ""] = element;
                  }}
                  role="button"
                  tabIndex={0}
                  onClick={() => selectAnchor(segment.anchorId, "document")}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      selectAnchor(segment.anchorId, "document");
                    }
                  }}
                >
                  {segment.text}
                </span>
              ) : (
                <span key={segment.id}>{segment.text}</span>
              ),
            )}
          </div>
        ) : null}
      </article>

      <aside className="analysis-comments-panel" aria-label="Expert comments">
        <header className="analysis-comments-panel__header">
          <h2>Expert comments</h2>
          <p>
            {roleComments.length} comment{roleComments.length === 1 ? "" : "s"} · sorted by document order
          </p>
        </header>
        {orderedComments.length ? (
          <div className="analysis-comment-list">
            {orderedComments.map((comment) => {
              const anchor = anchorByCommentId.get(comment.id) || null;
              const anchorId = anchor?.id || null;
              const voteTone = commentVoteTone(comment.vote);
              const isActive = Boolean(anchorId && activeAnchorId === anchorId);
              const isFirstCardForAnchor = Boolean(anchor && anchor.commentIds[0] === comment.id);
              return (
                <article
                  aria-pressed={anchorId ? isActive : undefined}
                  className={isActive ? "analysis-comment-card analysis-comment-card--active" : "analysis-comment-card"}
                  key={comment.id}
                  ref={(element) => {
                    if (anchorId && isFirstCardForAnchor) {
                      cardRefs.current[anchorId] = element;
                    }
                  }}
                  role={anchorId ? "button" : undefined}
                  tabIndex={anchorId ? 0 : undefined}
                  onClick={() => selectAnchor(anchorId, "card")}
                  onKeyDown={(event) => {
                    if ((event.key === "Enter" || event.key === " ") && anchorId) {
                      event.preventDefault();
                      selectAnchor(anchorId, "card");
                    }
                  }}
                >
                  <div className="analysis-comment-card__top">
                    <span className={`analysis-comment-avatar analysis-comment-avatar--${voteTone}`} aria-hidden="true">
                      <RoleAvatarIcon />
                    </span>
                    <div className="analysis-comment-card__identity">
                      <div className="analysis-comment-card__role-row">
                        <strong>{comment.voter}</strong>
                        <span className={`analysis-comment-vote analysis-comment-vote--${voteTone}`}>
                          {comment.vote ? formatLabel(comment.vote) : "No vote"}
                        </span>
                      </div>
                      <span className="analysis-comment-severity">
                        Comment severity · {comment.severity ? formatLabel(comment.severity) : "Not set"}
                      </span>
                    </div>
                  </div>
                  <p>{comment.body}</p>
                  <blockquote>
                    <strong>Anchor</strong>
                    <span>{comment.anchorText}</span>
                  </blockquote>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="analysis-muted">No role comments were returned by Devil&apos;s Advocate.</p>
        )}
      </aside>
    </section>
  );
}

function RoleAvatarIcon() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
      <circle cx="12" cy="8" r="3.2" />
      <path d="M5.8 19c1.1-3.7 3.2-5.6 6.2-5.6s5.1 1.9 6.2 5.6" />
    </svg>
  );
}

function displayLayer1Id(id: string): string {
  return id.startsWith("layer-1-") ? "Layer 1" : `Layer 1 · ${id}`;
}

function displayLayer2Id(id: string): string | null {
  return id.startsWith("layer-2-") ? null : id;
}

function LabeledText({ label, value }: { label: string; value: string | null }) {
  if (!value) {
    return null;
  }
  return (
    <div className="analysis-layer-field">
      <span>{label}</span>
      <p>{value}</p>
    </div>
  );
}

function PredictedSkillOutputSection({ run }: { run: PredictedCommentRunRecord | null }) {
  if (!run) {
    return (
      <section className="analysis-full-output-section stack">
        <h3>Devil&apos;s Advocate</h3>
        <p className="analysis-muted">No Devil&apos;s Advocate run is attached yet.</p>
      </section>
    );
  }

  const markdown = predictedSkillMarkdown(run);
  const sections = splitDevilsAdvocateMarkdown(markdown);
  const roleComments = devilsAdvocateRoleComments(run.structured_output);

  return (
    <section className="analysis-full-output-section stack">
      <div className="analysis-section-heading">
        <div>
          <h3>Devil&apos;s Advocate</h3>
          <p>
            {run.skill_name} · {run.provider} · {run.model}
          </p>
        </div>
        <StatusBadge status={run.status} />
      </div>
      {run.error_message ? <div className="analysis-alert">{run.error_message}</div> : null}
      {sections.length ? (
        <div className="analysis-da-sections">
          {sections.map((section) => (
            <section aria-label={section.title} className="analysis-da-section" key={section.title}>
              <h3>{section.title}</h3>
              {section.title === "Role comments / voter synthesis" && roleComments.length ? (
                <DevilsAdvocateRoleCommentsTable comments={roleComments} />
              ) : (
                <MarkdownPreview markdown={section.markdown} className="gc-markdown-preview--narrative" />
              )}
            </section>
          ))}
        </div>
      ) : roleComments.length ? (
        <div className="analysis-da-sections">
          <section aria-label="Role comments / voter synthesis" className="analysis-da-section">
            <h3>Role comments / voter synthesis</h3>
            <DevilsAdvocateRoleCommentsTable comments={roleComments} />
          </section>
        </div>
      ) : (
        <p className="analysis-muted">No markdown output is available for this run yet.</p>
      )}
    </section>
  );
}

function DevilsAdvocateRoleCommentsTable({ comments }: { comments: DevilsAdvocateRoleComment[] }) {
  return (
    <div className="analysis-role-comments-scroll">
      <table className="analysis-role-comments-table">
        <thead>
          <tr>
            <th>Voter</th>
            <th>Vote</th>
            <th>Anchor</th>
            <th>Comment</th>
            <th>Type</th>
            <th>Severity</th>
          </tr>
        </thead>
        <tbody>
          {comments.map((comment) => (
            <tr key={comment.id}>
              <td>{comment.voter}</td>
              <td>{comment.vote ? formatLabel(comment.vote) : "-"}</td>
              <td>{comment.anchorText}</td>
              <td>{comment.body}</td>
              <td>{comment.commentType ? formatLabel(comment.commentType) : "-"}</td>
              <td>{comment.severity ? formatLabel(comment.severity) : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function mainSkillMarkdownSections(analysis: AnalysisRecord): { main: string | null; layer1: string | null; layer2: string | null } {
  const output = analysis.structured_output;
  const layer1 = asString(output?.layer_1_markdown);
  const layer2 = asString(output?.layer_2_markdown);
  const rawMain =
    asString(output?.assessment_markdown) ||
    asString(output?.native_markdown) ||
    asString(output?.markdown) ||
    asString(output?.output_markdown) ||
    asString(output?.summary_markdown) ||
    (!layer1 && !layer2 ? extractProviderMessageContent(analysis.raw_output) : null);
  const main = stripAssessmentHeading(rawMain);

  return { main, layer1, layer2 };
}

function gateDetailsMarkdownSections(analysis: AnalysisRecord): { layer1: string | null; layer2: string | null } {
  const output = analysisGateDetailsOutput(analysis);
  return {
    layer1: asString(output?.layer_1_markdown),
    layer2: asString(output?.layer_2_markdown),
  };
}

function canRequestAnalysisDetails(analysis: AnalysisRecord): boolean {
  if (analysis.status !== "completed") {
    return false;
  }
  if (!isStagedSummaryAnalysis(analysis)) {
    return false;
  }
  if (analysis.detail_run?.status === "completed" || isActiveRunStatus(analysis.detail_run?.status)) {
    return false;
  }
  return true;
}

function isStagedSummaryAnalysis(analysis: AnalysisRecord): boolean {
  const output = analysis.structured_output;
  if (!output) {
    return false;
  }
  const hasLegacyDetails = Boolean(output.layer_1_markdown || output.layer_2_markdown);
  if (hasLegacyDetails) {
    return false;
  }
  return Boolean(
    analysis.run_parameters?.gate_challenger_response_id ||
      output.details_status ||
      Array.isArray(output.layer_1_index) ||
      Array.isArray(output.layer_2_index),
  );
}

function predictedSkillMarkdown(run: PredictedCommentRunRecord): string | null {
  return bestMarkdownOutput(run.structured_output) || extractProviderMessageContent(run.raw_output);
}

function CollapsibleMarkdown({ markdown, title }: { markdown: string; title: string }) {
  return (
    <details className="analysis-markdown-details">
      <summary>{title}</summary>
      <MarkdownPreview markdown={markdown} className="gc-markdown-preview--narrative" />
    </details>
  );
}

function FullOutputPanel({
  analysis,
  isLoadingDetails,
  onLoadDetails,
}: {
  analysis: AnalysisRecord;
  isLoadingDetails: boolean;
  onLoadDetails: () => void;
}) {
  const detailRun = analysis.detail_run;
  const isDetailActive = isActiveRunStatus(analysis.detail_run?.status);
  const canRequestDetails = canRequestAnalysisDetails(analysis);
  const showDetailsButton = canRequestDetails || isDetailActive || isLoadingDetails;
  return (
    <section className="analysis-card stack">
      <div className="analysis-section-heading">
        <div>
          <h2>Full Output</h2>
          <p>Detailed checks, Devil&apos;s Advocate output, structured result, raw model text when authorized, and run parameters.</p>
        </div>
      </div>
      {showDetailsButton ? (
        <div className="analysis-detail-loader">
          <button
            className="analysis-secondary-action"
            disabled={!canRequestDetails || isDetailActive || isLoadingDetails}
            type="button"
            onClick={onLoadDetails}
          >
            Load detailed Layer 1 / Layer 2
          </button>
          {isDetailActive || isLoadingDetails ? (
            <span>Loading detailed checks. This panel will refresh automatically.</span>
          ) : (
            <span>Gate Challenger summary is available. Detailed Layer 1 / Layer 2 will be requested on demand.</span>
          )}
        </div>
      ) : null}
      {detailRun?.status === "failed" ? (
        <div className="analysis-alert">
          <strong>Detail run failed</strong>
          {detailRun.error_message ? <span>{detailRun.error_message}</span> : null}
        </div>
      ) : null}
      <DetailedGateChecksOutput analysis={analysis} />
      <PredictedSkillOutputSection run={analysis.predicted_comment_run} />
      <details className="analysis-details" open>
        <summary>Gate Challenger structured JSON</summary>
        <JsonBlock value={analysis.structured_output ?? {}} />
      </details>
      {detailRun?.structured_output ? (
        <details className="analysis-details" open={detailRun.status === "completed"}>
          <summary>Gate Challenger detail structured JSON</summary>
          <JsonBlock value={detailRun.structured_output} />
        </details>
      ) : null}
      {analysis.raw_output ? (
        <details className="analysis-details">
          <summary>Raw Gate Challenger Output</summary>
          <pre className="analysis-pre">{analysis.raw_output}</pre>
        </details>
      ) : null}
      {detailRun?.raw_output ? (
        <details className="analysis-details">
          <summary>Raw Gate Challenger Detail Output</summary>
          <pre className="analysis-pre">{detailRun.raw_output}</pre>
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
      <MarkdownPreview markdown={value} className="gc-markdown-preview--narrative" />
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
  const gateDetailsOutput = analysisGateDetailsOutput(analysis);
  const mainRisks = [
    ...extractEvidenceItems(gateDetailsOutput, "layer_2"),
    ...extractEvidenceItems(gateDetailsOutput, "layer_1"),
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
  if (["approve", "pass", "completed", "low", "yes"].includes(value)) {
    return "good";
  }
  if (["approve_with_conditions", "conditional_approve", "partial", "need_evidence", "medium", "important"].includes(value)) {
    return "warn";
  }
  if (["reject", "rework", "fail", "failed", "critical", "high", "no"].includes(value)) {
    return "bad";
  }
  return "neutral";
}

function commentVoteTone(value: string | null | undefined): "good" | "warn" | "bad" {
  const normalized = value?.trim().toLowerCase();
  if (normalized === "reject") {
    return "bad";
  }
  if (["approve", "approved", "pass", "yes", "for", "за"].includes(normalized || "")) {
    return "good";
  }
  return "warn";
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

function isAnalysisRefreshPending(analysis: AnalysisRecord | null): boolean {
  return Boolean(
    analysis &&
      (isActiveRunStatus(analysis.status) ||
        isActiveRunStatus(analysis.predicted_comment_run?.status) ||
        isActiveRunStatus(analysis.detail_run?.status)),
  );
}

function isActiveRunStatus(status: AnalysisRecord["status"] | null | undefined): boolean {
  return status === "queued" || status === "running";
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

function bestMarkdownOutput(output: Record<string, unknown> | null | undefined): string | null {
  if (!output) {
    return null;
  }

  const directFields = [
    output.native_markdown,
    output.markdown,
    output.output_markdown,
    output.assessment_markdown,
    output.summary_markdown,
  ];
  const direct = directFields.map(asString).find(Boolean);
  if (direct) {
    return direct;
  }

  const sections = [output.layer_1_markdown, output.layer_2_markdown].map(asString).filter((section): section is string => Boolean(section));
  return sections.length ? sections.join("\n\n---\n\n") : null;
}

function extractProviderMessageContent(rawOutput: string | null): string | null {
  const raw = asString(rawOutput);
  if (!raw) {
    return null;
  }

  const trimmed = raw.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return trimmed;
  }

  try {
    return extractMessageContent(JSON.parse(trimmed));
  } catch {
    return null;
  }
}

function extractMessageContent(value: unknown): string | null {
  if (typeof value === "string") {
    return asString(value);
  }
  if (Array.isArray(value)) {
    const parts = value.map(extractMessageContent).filter((part): part is string => Boolean(part));
    return parts.length ? parts.join("\n") : null;
  }
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const direct = [record.structured_text, record.content, record.output, record.text].map(asString).find(Boolean);
  if (direct) {
    return direct;
  }

  const openAiContent = asRecord(asRecordArray(record.choices)[0]?.message)?.content;
  const openAiText = extractMessageContent(openAiContent);
  if (openAiText) {
    return openAiText;
  }

  return extractMessageContent(record.content);
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

.analysis-secondary-action {
  min-height: 44px;
  border-radius: 8px;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0;
  white-space: nowrap;
}

.analysis-hero__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.analysis-run-details-action {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.52);
  color: #94a3b8;
  box-shadow: none;
}

.analysis-run-details-action:hover:not(:disabled) {
  border-color: rgba(148, 163, 184, 0.36);
  background: rgba(30, 41, 59, 0.72);
  color: #cbd5e1;
}

.analysis-danger-action {
  min-height: 44px;
  border-radius: 8px;
  border-color: rgba(248, 113, 113, 0.34) !important;
  background: rgba(127, 29, 29, 0.42) !important;
  color: #fecaca !important;
  box-shadow: none !important;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 800;
}

.analysis-danger-action:hover:not(:disabled) {
  border-color: rgba(248, 113, 113, 0.58) !important;
  background: rgba(153, 27, 27, 0.6) !important;
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
  grid-template-columns: 1fr;
  gap: 18px;
  margin-bottom: 18px;
  padding: 22px;
}

.analysis-hero__main {
  display: grid;
  align-content: start;
  gap: 14px;
}

.analysis-hero__title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
}

.analysis-hero__title-copy {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.analysis-hero__title-copy h1 {
  overflow-wrap: anywhere;
}

.analysis-hero__date {
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.4;
}

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

.analysis-modal-backdrop {
  position: fixed;
  z-index: 50;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(2, 6, 23, 0.74);
  padding: 24px;
}

.analysis-modal {
  width: min(920px, 100%);
  max-height: min(760px, calc(100vh - 48px));
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: #08111f;
  box-shadow: 0 28px 90px rgba(0, 0, 0, 0.48);
  padding: 18px;
}

.analysis-modal__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.analysis-modal__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
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

.analysis-waiting {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
  border-color: rgba(56, 189, 248, 0.36);
  background:
    linear-gradient(180deg, rgba(12, 74, 110, 0.3), rgba(15, 23, 42, 0.96)),
    #020617;
}

.analysis-waiting__spinner {
  width: 34px;
  height: 34px;
  border: 3px solid rgba(125, 211, 252, 0.18);
  border-top-color: #5eead4;
  border-radius: 999px;
  animation: analysis-spin 900ms linear infinite;
}

.analysis-waiting__copy {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.analysis-waiting__copy p {
  color: #cbd5e1;
  font-size: 13px;
  line-height: 1.55;
}

.analysis-waiting__copy span {
  color: #7dd3fc;
  font-size: 12px;
  font-weight: 750;
  text-transform: uppercase;
}

@keyframes analysis-spin {
  to {
    transform: rotate(360deg);
  }
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
  min-height: 44px;
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

.analysis-score-grid--modal {
  grid-template-columns: repeat(4, minmax(0, 1fr));
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

.analysis-full-output-section {
  display: grid;
  gap: 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
  padding-top: 16px;
}

.analysis-full-output-section h3 {
  color: #f8fafc;
}

.analysis-detail-loader {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  align-items: center;
  justify-content: space-between;
  border: 1px solid rgba(94, 234, 212, 0.18);
  border-radius: 8px;
  background: rgba(15, 118, 110, 0.08);
  padding: 12px;
}

.analysis-detail-loader span {
  color: #94a3b8;
  font-size: 13px;
  line-height: 18px;
}

.analysis-detail-checks {
  display: grid;
  gap: 10px;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
  margin-top: 4px;
  padding-top: 16px;
}

.analysis-short-summary {
  display: grid;
  gap: 8px;
  border: 1px solid rgba(94, 234, 212, 0.22);
  border-radius: 8px;
  background: rgba(15, 118, 110, 0.12);
  padding: 14px;
}

.analysis-short-summary h3 {
  color: #a7f3d0;
  font-size: 12px;
  font-weight: 800;
}

.analysis-short-summary p {
  width: 100%;
  color: #dbeafe;
  font-size: 14px;
  line-height: 1.65;
}

.analysis-detail-checks h3 {
  color: #f8fafc;
}

.analysis-layered-checks {
  display: grid;
  gap: 0;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  overflow: hidden;
}

.analysis-layer-group {
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(2, 6, 23, 0.28);
}

.analysis-layer-group:last-child {
  border-bottom: 0;
}

.analysis-layer-group summary {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 64px;
  cursor: pointer;
  padding: 14px;
}

.analysis-layer-group summary::-webkit-details-marker,
.analysis-layer2-probe summary::-webkit-details-marker {
  display: none;
}

.analysis-layer-group summary::before,
.analysis-layer2-probe summary::before {
  content: "›";
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 6px;
  color: #93c5fd;
  font-size: 14px;
}

.analysis-layer-group[open] summary::before,
.analysis-layer2-probe[open] summary::before {
  content: "⌄";
}

.analysis-layer-group__summary {
  display: grid;
  flex: 1 1 auto;
  min-width: 0;
  gap: 5px;
}

.analysis-layer-group__summary span {
  color: #93c5fd;
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0;
  text-transform: uppercase;
}

.analysis-layer-group__summary strong {
  color: #f8fafc;
  font-size: 14px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.analysis-layer-group__summary small {
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.4;
}

.analysis-layer-group__body {
  display: grid;
  gap: 12px;
  min-width: 0;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
  padding: 0 14px 16px 50px;
}

.analysis-layer-finding-card {
  display: grid;
  gap: 10px;
  min-width: 0;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.44);
  padding: 12px;
}

.analysis-layer-clear-state {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid rgba(34, 197, 94, 0.22);
  border-radius: 8px;
  background: rgba(22, 163, 74, 0.1);
  padding: 12px;
}

.analysis-layer-clear-state strong {
  color: #bbf7d0;
  font-size: 13px;
}

.analysis-layer-clear-state span {
  color: #9fb0c4;
  font-size: 12px;
  line-height: 1.45;
  text-align: right;
}

.analysis-layer-card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #bfdbfe;
  font-size: 12px;
  font-weight: 850;
  text-transform: uppercase;
}

.analysis-layer-card-heading small {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 850;
  text-transform: uppercase;
}

.analysis-layer-fields {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.analysis-layer-fields--compact {
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(2, 6, 23, 0.28);
  padding: 10px 12px 12px;
}

.analysis-layer-field {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.analysis-layer-field span {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0;
  text-transform: uppercase;
}

.analysis-layer-field p {
  color: #dbeafe;
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.analysis-layer2-list {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.analysis-layer2-question {
  display: grid;
  gap: 0;
  min-width: 0;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.34);
  overflow: hidden;
}

.analysis-layer2-question__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  padding: 12px;
}

.analysis-layer2-question__top > div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.analysis-layer2-question__top > span:first-child {
  color: #93c5fd;
  font-size: 11px;
  font-weight: 850;
}

.analysis-layer2-question h4 {
  margin-top: 5px;
  color: #f8fafc;
  font-size: 14px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.analysis-layer2-probes {
  display: grid;
}

.analysis-layer2-probe {
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(2, 6, 23, 0.22);
}

.analysis-layer2-probe summary {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
  padding: 12px;
}

.analysis-layer2-probe summary strong {
  flex: 1 1 auto;
  min-width: 0;
  color: #dbeafe;
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.analysis-layer2-probe__body {
  display: grid;
  gap: 10px;
  margin: 0 12px 12px 46px;
  border-left: 3px solid rgba(59, 130, 246, 0.7);
  border-radius: 0 6px 6px 0;
  background: rgba(30, 64, 175, 0.16);
  padding: 10px 12px;
}

.analysis-answer {
  flex-shrink: 0;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  padding: 5px 8px;
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
}

.analysis-answer--good {
  border-color: rgba(34, 197, 94, 0.35);
  background: rgba(22, 163, 74, 0.14);
  color: #86efac;
}

.analysis-answer--warn {
  border-color: rgba(245, 158, 11, 0.35);
  background: rgba(180, 83, 9, 0.16);
  color: #fde68a;
}

.analysis-answer--bad {
  border-color: rgba(239, 68, 68, 0.36);
  background: rgba(185, 28, 28, 0.16);
  color: #fecaca;
}

.analysis-da-sections {
  display: grid;
  gap: 16px;
}

.analysis-da-section {
  display: grid;
  gap: 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
  padding-top: 16px;
}

.analysis-da-section:first-child {
  border-top: 0;
  padding-top: 0;
}

.analysis-da-section h3 {
  color: #f8fafc;
  font-size: 15px;
  font-weight: 800;
}

.analysis-role-comments-scroll {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: #070a12;
  -webkit-overflow-scrolling: touch;
}

.analysis-role-comments-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  color: #dbeafe;
  font-size: 13px;
  line-height: 1.45;
}

.analysis-role-comments-table th,
.analysis-role-comments-table td {
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  padding: 10px 12px;
  text-align: left;
  vertical-align: top;
}

.analysis-role-comments-table th {
  background: rgba(15, 23, 42, 0.9);
  color: #bfdbfe;
  font-size: 11px;
  font-weight: 850;
  text-transform: uppercase;
  white-space: nowrap;
}

.analysis-role-comments-table tr:last-child td {
  border-bottom: 0;
}

.analysis-role-comments-table th:nth-child(1),
.analysis-role-comments-table td:nth-child(1),
.analysis-role-comments-table th:nth-child(2),
.analysis-role-comments-table td:nth-child(2),
.analysis-role-comments-table th:nth-child(5),
.analysis-role-comments-table td:nth-child(5),
.analysis-role-comments-table th:nth-child(6),
.analysis-role-comments-table td:nth-child(6) {
  min-width: 96px;
  max-width: 140px;
}

.analysis-role-comments-table th:nth-child(3),
.analysis-role-comments-table td:nth-child(3) {
  min-width: 220px;
  max-width: 320px;
}

.analysis-role-comments-table th:nth-child(4),
.analysis-role-comments-table td:nth-child(4) {
  min-width: 420px;
  max-width: 680px;
}

.analysis-markdown-details {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.4);
  padding: 0;
}

.analysis-markdown-details summary {
  min-height: 46px;
  cursor: pointer;
  color: #bae6fd;
  font-weight: 800;
  padding: 13px 14px;
}

.analysis-markdown-details .gc-markdown-preview {
  border-top: 1px solid rgba(148, 163, 184, 0.14);
  padding: 14px;
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

  .analysis-waiting {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .analysis-waiting .badge {
    grid-column: 1 / -1;
    justify-self: start;
  }

  .analysis-hero__title-row {
    align-items: stretch;
    flex-direction: column;
  }

  .analysis-hero__actions {
    justify-content: flex-start;
  }

  .analysis-run-details-action {
    align-self: flex-start;
    min-height: 44px;
    padding-inline: 12px;
    font-size: 12px;
  }

  .analysis-split,
  .analysis-score-grid,
  .analysis-score-grid--modal {
    grid-template-columns: 1fr;
  }

  .analysis-modal-backdrop {
    align-items: stretch;
    padding: 10px;
  }

  .analysis-modal {
    max-height: calc(100vh - 20px);
    padding: 14px;
  }

  .analysis-modal__header {
    align-items: stretch;
    flex-direction: column;
  }
}
`;

const paperAnalysisOverrides = `
.analysis-workbench {
  width: min(100%, 1536px);
  padding: 28px 36px 48px;
  color: #111827;
}

.analysis-workbench h1 {
  color: #111827;
  font-size: 30px;
  font-weight: 800;
  line-height: 38px;
}

.analysis-workbench h2,
.analysis-workbench h3 {
  color: #111827;
}

.analysis-workbench button,
.analysis-workbench .secondary-link {
  border-color: #0e9f6e;
  background: #0e9f6e;
  color: #ffffff;
  box-shadow: none;
}

.analysis-workbench button:hover:not(:disabled) {
  border-color: #087d5f;
  background: #087d5f;
  transform: none;
}

.analysis-run-details-action,
.analysis-secondary-action {
  border-color: #d6dee8 !important;
  background: #ffffff !important;
  color: #111827 !important;
}

.analysis-run-details-action:hover:not(:disabled),
.analysis-secondary-action:hover:not(:disabled) {
  border-color: #0e9f6e !important;
  background: #eaf8f2 !important;
  color: #075e45 !important;
}

.analysis-danger-action {
  border-color: #f2d7d9 !important;
  background: #ffffff !important;
  color: #a5122a !important;
}

.analysis-danger-action:hover:not(:disabled) {
  border-color: #c92036 !important;
  background: #fcecee !important;
  color: #8f1024 !important;
}

.analysis-workbench button:focus-visible,
.analysis-workbench input:focus-visible,
.analysis-workbench select:focus-visible,
.analysis-workbench textarea:focus-visible {
  outline: 2px solid rgba(14, 159, 110, 0.6);
}

.analysis-workbench input,
.analysis-workbench select,
.analysis-workbench textarea {
  border-color: #d6dee8;
  background: #ffffff;
  color: #111827;
}

.analysis-workbench label,
.analysis-hero__date,
.analysis-lead,
.analysis-card p,
.analysis-card__label,
.analysis-wrap,
.analysis-token,
.analysis-chip {
  color: #5b6472;
}

.analysis-hero,
.analysis-card,
.analysis-alert,
.analysis-loading,
.analysis-modal,
.analysis-details,
.analysis-trace,
.analysis-token,
.analysis-chip,
.analysis-layer-group,
.analysis-layer-table,
.analysis-layer-question,
.analysis-short-summary,
.analysis-empty,
.analysis-json,
.analysis-markdown-card {
  border-color: #d6dee8;
  background: #ffffff;
  box-shadow: none;
}

.analysis-hero {
  margin-bottom: 22px;
  padding: 0;
  border: 0;
  background: transparent;
}

.analysis-chip-row {
  margin-top: 2px;
}

.analysis-verdict,
.analysis-workbench .badge,
.analysis-status-pill,
.analysis-layer-status {
  border-color: transparent;
  background: #f2f4f7;
  color: #344054;
}

.analysis-verdict--ok,
.analysis-workbench .badge.ok,
.analysis-status-pill--pass,
.analysis-layer-status--pass {
  background: #eaf8f2;
  color: #075e45;
}

.analysis-verdict--warning,
.analysis-workbench .badge.warning,
.analysis-status-pill--partial,
.analysis-layer-status--partial {
  background: #fff7df;
  color: #7a4300;
}

.analysis-verdict--danger,
.analysis-workbench .badge.danger,
.analysis-status-pill--fail,
.analysis-layer-status--fail {
  background: #fcecee;
  color: #a5122a;
}

.analysis-workbench .badge.info {
  background: #eaf3fb;
  color: #1d70b8;
}

.analysis-layout {
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.analysis-tabs {
  min-height: 52px;
  border: 1px solid #d6dee8;
  border-radius: 8px;
  background: #ffffff;
  padding: 6px;
}

.analysis-tab {
  min-height: 44px;
  border: 0 !important;
  border-radius: 7px;
  background: transparent !important;
  color: #344054 !important;
  box-shadow: none !important;
}

.analysis-tab--active,
.analysis-tab[aria-pressed="true"] {
  background: #eaf8f2 !important;
  color: #075e45 !important;
}

.analysis-card {
  border-radius: 8px;
  padding: 22px 24px;
}

.analysis-waiting {
  border-color: #b7dfcf;
  background: #f7fcfa;
}

.analysis-waiting__spinner {
  border-color: #ccebdd;
  border-top-color: #0e9f6e;
}

.analysis-waiting__copy p {
  color: #344054;
}

.analysis-waiting__copy span {
  color: #087d5f;
}

.analysis-short-summary {
  border-color: #e5eaf0;
  background: #f7f9fb;
}

.analysis-section-heading,
.analysis-modal__header,
.analysis-layer-row,
.analysis-layer-question__header {
  border-color: #eef2f6;
}

.analysis-layer-group {
  border-color: #e5eaf0;
  background: #ffffff;
}

.analysis-layered-checks {
  border-color: #d6dee8;
  background: #ffffff;
}

.analysis-full-output-section {
  border-top-color: #e5eaf0;
}

.analysis-full-output-section h3 {
  color: #111827;
}

.analysis-detail-loader {
  border-color: #ccebdd;
  background: #f2fbf6;
}

.analysis-detail-loader span {
  color: #344054;
}

.analysis-detail-checks {
  border-top-color: #e5eaf0;
}

.analysis-detail-checks h3,
.analysis-layer-group__summary strong,
.analysis-layer2-question h4 {
  color: #111827;
}

.analysis-layer-group__summary span,
.analysis-layer2-question__top > span:first-child {
  color: #1d70b8;
}

.analysis-layer-group__summary small {
  color: #5b6472;
}

.analysis-layer-group__body {
  border-top-color: #eef2f6;
}

.analysis-layer-finding-card,
.analysis-layer2-question {
  border-color: #e5eaf0;
  background: #ffffff;
}

.analysis-layer-clear-state {
  border-color: #ccebdd;
  background: #f2fbf6;
}

.analysis-layer-clear-state strong {
  color: #075e45;
}

.analysis-layer-clear-state span {
  color: #5b6472;
}

.analysis-layer-fields--compact,
.analysis-layer2-probe {
  border-color: #eef2f6;
  background: #f9fafb;
}

.analysis-layer-card-heading {
  color: #5b6472;
}

.analysis-layer-card-heading small {
  color: #5b6472;
}

.analysis-layer-group summary::before,
.analysis-layer2-probe summary::before {
  border-color: #d6dee8;
  color: #5b6472;
  background: #ffffff;
}

.analysis-layer-field span {
  color: #5b6472;
}

.analysis-layer-field p {
  color: #344054;
}

.analysis-answer {
  border-color: #e5eaf0;
  background: #f2f4f7;
  color: #344054;
}

.analysis-answer--good {
  border-color: transparent;
  background: #eaf8f2;
  color: #075e45;
}

.analysis-answer--warn {
  border-color: transparent;
  background: #fff7df;
  color: #7a4300;
}

.analysis-answer--bad {
  border-color: transparent;
  background: #fcecee;
  color: #a5122a;
}

.analysis-layer2-question__top,
.analysis-layer2-probe {
  border-color: #e5eaf0;
}

.analysis-layer2-probe summary strong {
  color: #111827;
}

.analysis-layer2-probe__body {
  border-left-color: #1d70b8;
  background: #eaf3fb;
}

.analysis-layer-group h3 {
  color: #064e3b;
}

.analysis-layer-table__header {
  border-bottom-color: #bfebdd;
  background: #ecfdf5;
  color: #0f766e;
}

.analysis-layer-row,
.analysis-layer-question__detail {
  background: #ffffff;
}

.analysis-layer-question__detail:nth-child(n + 2) {
  background: #f9fafb;
}

.analysis-role-comments-scroll {
  border-color: #e5eaf0;
  background: #ffffff;
}

.analysis-role-comments-table {
  color: #344054;
}

.analysis-role-comments-table th,
.analysis-role-comments-table td {
  border-bottom-color: #edf1f5;
}

.analysis-role-comments-table th {
  background: #fbfcfd;
  color: #111827;
}

.analysis-inspector {
  width: 380px;
}

.analysis-modal-backdrop {
  background: rgba(17, 24, 39, 0.28);
}

.analysis-modal {
  box-shadow: 0 16px 42px rgba(17, 24, 39, 0.12);
}

.analysis-alert {
  border-color: #f2d7d9;
  background: #fcecee;
  color: #a5122a;
}

.analysis-success {
  color: #075e45;
}

.analysis-json,
.analysis-details pre {
  background: #fbfcfd;
  color: #111827;
}

.analysis-markdown :where(p, li, td, th),
.analysis-markdown-card,
.analysis-native-output {
  color: #344054;
}

.analysis-markdown :where(h1, h2, h3, h4, strong),
.analysis-native-output :where(h1, h2, h3, h4, strong) {
  color: #111827;
}

.analysis-markdown table,
.analysis-native-output table {
  border-color: #e5eaf0;
}

.analysis-markdown th,
.analysis-native-output th {
  background: #fbfcfd;
  color: #111827;
}

.analysis-feedback-card {
  gap: 18px;
}

.analysis-feedback-card h2 {
  font-size: 18px;
  line-height: 24px;
}

.analysis-feedback-fab {
  position: fixed;
  right: max(20px, env(safe-area-inset-right));
  bottom: max(20px, env(safe-area-inset-bottom));
  z-index: 45;
  min-height: 46px;
  border: 1px solid #0e9f6e !important;
  border-radius: 8px;
  background: #0e9f6e !important;
  color: #ffffff !important;
  box-shadow: 0 14px 28px rgba(16, 24, 40, 0.18);
  padding: 0 18px;
  font-size: 14px;
  font-weight: 850;
}

.analysis-feedback-fab:hover:not(:disabled) {
  background: #0b7c59 !important;
  color: #ffffff !important;
}

.analysis-feedback-fab--saved {
  border-color: #73c8a6 !important;
  background: #eaf8f2 !important;
  color: #075e45 !important;
}

.analysis-feedback-fab--saved:hover:not(:disabled) {
  background: #d9f1e8 !important;
  color: #075e45 !important;
}

.analysis-feedback-sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: flex-end;
  justify-content: flex-end;
  background: rgba(17, 24, 39, 0.2);
  padding: 24px;
}

.analysis-feedback-sheet {
  width: min(420px, 100%);
  max-height: calc(100vh - 48px);
  overflow: auto;
  border: 1px solid #d6dee8;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 24px 50px rgba(16, 24, 40, 0.22);
  padding: 18px;
}

.analysis-feedback-sheet__header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.analysis-feedback-sheet__header h2 {
  margin: 0;
  color: #111827;
  font-size: 18px;
  line-height: 24px;
}

.analysis-feedback-field {
  display: grid;
  gap: 10px;
}

.analysis-feedback-label {
  color: #344054;
  font-size: 14px;
  font-weight: 750;
  line-height: 20px;
}

.analysis-feedback-rating {
  display: grid;
  grid-template-columns: repeat(5, 44px);
  justify-content: space-between;
  gap: 10px;
}

.analysis-feedback-rating__button {
  display: grid;
  width: 44px;
  height: 44px;
  min-height: 44px;
  place-items: center;
  border: 1px solid transparent !important;
  border-radius: 8px;
  background: #f7f9fb !important;
  color: #6b7280 !important;
  box-shadow: none !important;
  padding: 0;
}

.analysis-feedback-rating__button:hover:not(:disabled) {
  border-color: #b9c4d1 !important;
  background: #f2f5f8 !important;
  color: #344054 !important;
}

.analysis-feedback-rating__button--selected,
.analysis-feedback-rating__button--selected:hover:not(:disabled) {
  border-color: #73c8a6 !important;
  background: #eaf8f2 !important;
  color: #0e9f6e !important;
}

.analysis-feedback-face {
  width: 26px;
  height: 26px;
}

.analysis-feedback-textarea {
  width: 100%;
  min-height: 92px !important;
  resize: vertical;
  border-radius: 8px;
  padding: 12px;
  color: #344054 !important;
  font-size: 14px;
  line-height: 20px;
}

.analysis-feedback-textarea::placeholder {
  color: #344054;
  opacity: 1;
}

.analysis-feedback-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: -8px;
  color: #6b7280;
  font-size: 12px;
  line-height: 16px;
}

.analysis-feedback-actions {
  display: grid;
  gap: 8px;
}

.analysis-feedback-submit {
  width: 100%;
  min-height: 44px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 800;
}

.analysis-document-comments {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 420px;
  gap: 16px;
  align-items: start;
}

.analysis-document-panel,
.analysis-comments-panel,
.analysis-comment-card {
  border: 1px solid #d6dee8;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: none;
}

.analysis-document-panel {
  min-width: 0;
  padding: 28px 34px;
}

.analysis-document-panel__header {
  margin-bottom: 24px;
  border-bottom: 1px solid #e5eaf0;
  padding-bottom: 18px;
}

.analysis-document-panel__header h2,
.analysis-comments-panel__header h2 {
  margin: 0 0 8px;
  color: #111827;
  font-size: 22px;
  font-weight: 800;
  line-height: 28px;
}

.analysis-document-panel__header p,
.analysis-comments-panel__header p {
  margin: 0;
  color: #5b6472;
  font-size: 13px;
  line-height: 19px;
}

.analysis-document-text {
  color: #2f3a49;
  font-size: 15px;
  line-height: 1.72;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.analysis-document-anchor {
  display: inline-block;
  max-width: 100%;
  border-radius: 4px;
  padding: 1px 3px;
  cursor: pointer;
  font-weight: 700;
  line-height: 1.35;
  scroll-margin-top: 92px;
  transition:
    background 160ms ease,
    box-shadow 160ms ease,
    outline-color 160ms ease;
}

.analysis-document-anchor::after {
  display: inline-flex;
  min-width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  margin-left: 4px;
  border-radius: 999px;
  color: #ffffff;
  font-size: 11px;
  font-weight: 900;
  vertical-align: 1px;
  content: attr(data-count);
}

.analysis-document-anchor--bad {
  background: #fde8eb;
  color: #8f1024;
}

.analysis-document-anchor--bad::after {
  background: #c92036;
}

.analysis-document-anchor--warn {
  background: #fff1c7;
  color: #6b3b00;
}

.analysis-document-anchor--warn::after {
  background: #f5b544;
  color: #3a2600;
}

.analysis-document-anchor--good {
  background: #def7ec;
  color: #075e45;
}

.analysis-document-anchor--good::after {
  background: #0e9f6e;
}

.analysis-document-anchor--neutral {
  background: #f2f4f7;
  color: #344054;
}

.analysis-document-anchor--neutral::after {
  background: #6b7280;
}

.analysis-document-anchor--active {
  outline: 2px solid #1d70b8;
  outline-offset: 2px;
  box-shadow: 0 0 0 5px rgba(29, 112, 184, 0.12);
}

.analysis-comments-panel {
  position: sticky;
  top: 82px;
  max-height: calc(100vh - 104px);
  overflow: auto;
  padding: 14px;
}

.analysis-comments-panel__header {
  margin-bottom: 16px;
  border-bottom: 1px solid #e5eaf0;
  padding: 4px 2px 16px;
}

.analysis-comment-list {
  display: grid;
  gap: 12px;
}

.analysis-comment-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  scroll-margin-top: 92px;
  transition:
    border-color 160ms ease,
    box-shadow 160ms ease,
    transform 160ms ease;
}

.analysis-comment-card[role="button"] {
  cursor: pointer;
}

.analysis-comment-card[role="button"]:hover {
  border-color: #b8c5d6;
}

.analysis-comment-card--active {
  border-color: #1d70b8;
  box-shadow:
    inset 3px 0 0 #1d70b8,
    0 0 0 3px rgba(29, 112, 184, 0.12);
  transform: translateY(-1px);
}

.analysis-comment-card__top {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 11px;
  align-items: start;
}

.analysis-comment-avatar {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border: 3px solid #f5b544;
  border-radius: 50%;
  background: #ffffff;
  color: #344054;
}

.analysis-comment-avatar svg {
  width: 22px;
  height: 22px;
  stroke: currentColor;
  stroke-width: 1.8;
}

.analysis-comment-avatar--bad {
  border-color: #c92036;
}

.analysis-comment-avatar--good {
  border-color: #0e9f6e;
}

.analysis-comment-avatar--warn {
  border-color: #f5b544;
}

.analysis-comment-card__identity {
  min-width: 0;
}

.analysis-comment-card__role-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.analysis-comment-card__role-row strong {
  color: #111827;
  font-size: 14px;
  font-weight: 850;
}

.analysis-comment-vote {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  border-radius: 999px;
  padding: 0 8px;
  font-size: 10px;
  font-weight: 850;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.analysis-comment-vote--bad {
  background: #fcecee;
  color: #a5122a;
}

.analysis-comment-vote--good {
  background: #eaf8f2;
  color: #075e45;
}

.analysis-comment-vote--warn {
  background: #fff7df;
  color: #7a4300;
}

.analysis-comment-severity {
  display: block;
  margin-top: 5px;
  color: #5b6472;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.analysis-comment-card p {
  margin: 0;
  color: #243041;
  font-size: 14px;
  line-height: 1.58;
}

.analysis-comment-card blockquote {
  display: grid;
  gap: 4px;
  margin: 0;
  border-left: 3px solid #d6dee8;
  background: #f7f9fb;
  padding: 9px 10px;
}

.analysis-comment-card blockquote strong {
  color: #5b6472;
  font-size: 11px;
  text-transform: uppercase;
}

.analysis-comment-card blockquote span {
  color: #344054;
  font-size: 13px;
  line-height: 1.45;
}

@media (max-width: 1080px) {
  .analysis-inspector {
    width: 100%;
  }

  .analysis-document-comments {
    grid-template-columns: 1fr;
  }

  .analysis-comments-panel {
    position: static;
    max-height: none;
  }
}

@media (max-width: 640px) {
  .analysis-workbench {
    padding: 18px 12px 96px;
  }

  .analysis-tabs {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  }

  .analysis-feedback-fab {
    right: 12px;
    bottom: 12px;
    left: 12px;
    width: auto;
  }

  .analysis-feedback-sheet-backdrop {
    align-items: flex-end;
    padding: 12px;
  }

  .analysis-feedback-sheet {
    width: 100%;
    max-height: calc(100vh - 24px);
  }

  .analysis-document-panel {
    padding: 20px 18px;
  }
}
`;
