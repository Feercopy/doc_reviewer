"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { MarkdownPreview } from "@/components/MarkdownPreview";
import { resolveApiBaseUrl } from "@/lib/api/client";
import {
  getProviderDefaultModel,
  listProviderModels,
  type ProviderModelOptions,
} from "@/lib/api/provider-settings";
import {
  createAnalysis,
  deleteDocument,
  getDocument,
  getParsedText,
  listAnalyses,
  patchDocumentTitle,
  reparseDocument,
  type AnalysisRecord,
  type DocumentRecord,
  type OutputLanguage,
  type Provider,
  type RunStatus,
} from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

type WorkflowStep = {
  label: string;
  note: string;
  state: "done" | "active" | "blocked" | "idle";
};

const providerLabels: Record<Provider, string> = {
  openai_compatible: "OpenAI compatible",
  anthropic_compatible: "Anthropic compatible",
  hermes: "Hermes",
};

const outputLanguageOptions: readonly OutputLanguage[] = ["ru", "en"];

function buildWorkflowSteps(document: DocumentRecord, analyses: AnalysisRecord[]): WorkflowStep[] {
  const completedAnalyses = analyses
    .filter((analysis) => analysis.status === "completed")
    .sort(
      (left, right) =>
        new Date(right.completed_at ?? right.created_at).getTime() -
        new Date(left.completed_at ?? left.created_at).getTime(),
    );
  const latestCompletedAnalysis = completedAnalyses[0] ?? null;
  const hasCompletedAnalysis = completedAnalyses.length > 0;
  const hasRunningAnalysis = analyses.some((analysis) => analysis.status === "queued" || analysis.status === "running");
  const hasFailedAnalysis = analyses.some((analysis) => analysis.status === "failed");
  const parseDone = document.parse_status === "completed";
  const parseFailed = document.parse_status === "failed";

  return [
    {
      label: "Uploaded",
      note: formatDate(document.created_at),
      state: "done",
    },
    {
      label: "Parsed",
      note: parseDone ? formatDate(document.updated_at) : formatLabel(document.parse_status),
      state: parseDone ? "done" : parseFailed ? "blocked" : "active",
    },
    {
      label: "Ready",
      note: parseDone ? formatLabel(document.manual_document_type ?? document.detected_document_type) : "Waiting on parser",
      state: parseDone ? "done" : "idle",
    },
    {
      label: "Analysis complete",
      note: latestCompletedAnalysis
        ? formatDate(latestCompletedAnalysis.completed_at ?? latestCompletedAnalysis.created_at)
        : hasRunningAnalysis
          ? "Run in progress"
          : "No completed run",
      state: hasCompletedAnalysis ? "done" : hasRunningAnalysis ? "active" : hasFailedAnalysis ? "blocked" : "idle",
    },
  ];
}

function getAnalysisTone(status: RunStatus): "good" | "info" | "bad" | "neutral" {
  if (status === "completed") {
    return "good";
  }
  if (status === "queued" || status === "running") {
    return "info";
  }
  if (status === "failed" || status === "cancelled") {
    return "bad";
  }
  return "neutral";
}

function getSourceTraceLabel(analysis: AnalysisRecord): string {
  const trace = analysis.source_trace;
  if (!trace) {
    return "-";
  }
  if (trace.source_slug || trace.source_revision) {
    return [trace.source_slug, trace.source_revision].filter(Boolean).join(" @ ");
  }
  if (trace.source_fingerprint) {
    return trace.source_fingerprint.slice(0, 12);
  }
  return "-";
}

function getVerdictTone(verdict: string | null): "good" | "warn" | "bad" | "neutral" {
  if (!verdict) {
    return "neutral";
  }
  if (["approve", "pass", "completed", "low"].includes(verdict)) {
    return "good";
  }
  if (["approve_with_conditions", "conditional_approve", "partial", "need_evidence", "medium", "important"].includes(verdict)) {
    return "warn";
  }
  if (["reject", "rework", "fail", "failed", "critical", "high"].includes(verdict)) {
    return "bad";
  }
  return "neutral";
}

function formatDateStack(value: string | null | undefined): { date: string; time: string } {
  if (!value) {
    return { date: "-", time: "" };
  }
  const date = new Date(value);
  return {
    date: new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(date),
    time: new Intl.DateTimeFormat("en", { timeStyle: "short" }).format(date),
  };
}

function formatAnalysisError(message: string): string {
  const normalized = message
    .replace(/\\n/g, " ")
    .replace(/\\"/g, "\"")
    .replace(/\\'/g, "'")
    .replace(/\s+/g, " ")
    .trim();
  const code = /Error code:\s*(\d+)/i.exec(normalized)?.[1] ?? /["']code["']:\s*(\d+)/i.exec(normalized)?.[1] ?? "";
  const doubleQuotedMessages = Array.from(normalized.matchAll(/"message"\s*:\s*"([^"]+)"/g));
  const singleQuotedMessages = Array.from(normalized.matchAll(/'message'\s*:\s*'([^']+)'/g));
  const messages = [...doubleQuotedMessages, ...singleQuotedMessages]
    .map((match) => match[1].trim())
    .filter((item) => item && !/provider returned error/i.test(item));
  const usefulMessage = messages.find((item) => /invalid schema|invalid request|response_format|required/i.test(item)) ?? messages[0];

  if (usefulMessage) {
    return compactErrorText(usefulMessage, code);
  }

  return compactErrorText(normalized.replace(/^Error code:\s*\d+\s*-\s*/i, ""), code);
}

function compactErrorText(message: string, code: string): string {
  if (/Invalid schema for response_format/i.test(message)) {
    const schemaName = /Invalid schema for response_format\s+['"]?([^'":\s]+)?/i.exec(message)?.[1];
    const suffix = schemaName ? ` (${schemaName})` : "";
    return `${code ? `${code}: ` : ""}Invalid response schema${suffix}. Required fields are missing.`;
  }

  const firstSentence = message.split(/(?<=[.!?])\s+/)[0] ?? message;
  const compact = firstSentence.length > 150 ? `${firstSentence.slice(0, 147)}...` : firstSentence;
  return code && !compact.startsWith(code) ? `${code}: ${compact}` : compact;
}

export default function DocumentDetailPage() {
  const params = useParams<{ documentId: string }>();
  const documentId = params.documentId;
  const [document, setDocument] = useState<DocumentRecord | null>(null);
  const [parsedText, setParsedText] = useState("");
  const [analyses, setAnalyses] = useState<AnalysisRecord[]>([]);
  const [providerModels, setProviderModels] = useState<ProviderModelOptions[]>([]);
  const [provider, setProvider] = useState<Provider>("openai_compatible");
  const [model, setModel] = useState("");
  const [modelEdited, setModelEdited] = useState(false);
  const [outputLanguage, setOutputLanguage] = useState<OutputLanguage>("en");
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [draftModel, setDraftModel] = useState("");
  const [copiedParsed, setCopiedParsed] = useState(false);
  const [titleEditing, setTitleEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [titleSaving, setTitleSaving] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    const nextDocument = await getDocument(documentId);
    setDocument(nextDocument);
    listAnalyses(documentId)
      .then((response) => setAnalyses(response.analyses))
      .catch(() => setAnalyses([]));
    if (nextDocument.parse_status === "completed") {
      try {
        setParsedText(await getParsedText(documentId));
      } catch {
        setParsedText("");
      }
    } else {
      setParsedText("");
    }
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load document"));
  }, [documentId]);

  useEffect(() => {
    let ignore = false;

    listProviderModels()
      .then((response) => {
        if (!ignore) {
          setProviderModels(response.provider_models);
        }
      })
      .catch(() => setProviderModels([]));

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (modelEdited) {
      return;
    }
    const defaultModel = getProviderDefaultModel(providerModels, provider);
    if (defaultModel) {
      setModel(defaultModel);
    }
  }, [modelEdited, provider, providerModels]);

  const configuredProviderModels = useMemo(() => providerModels.filter((item) => item.has_key), [providerModels]);
  const selectedProviderModel = useMemo(
    () => providerModels.find((item) => item.provider === provider) ?? null,
    [provider, providerModels],
  );
  const workflowSteps = useMemo(() => (document ? buildWorkflowSteps(document, analyses) : []), [analyses, document]);

  useEffect(() => {
    if (!modelDialogOpen) {
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setModelDialogOpen(false);
      }
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [modelDialogOpen]);

  useEffect(() => {
    if (configuredProviderModels.length === 0 || configuredProviderModels.some((item) => item.provider === provider)) {
      return;
    }

    const nextProvider = configuredProviderModels[0].provider;
    setProvider(nextProvider);
    setModelEdited(false);
    setModel(getProviderDefaultModel(providerModels, nextProvider));
  }, [provider, providerModels, configuredProviderModels]);

  function openModelDialog() {
    setDraftModel(model);
    setModelDialogOpen(true);
  }

  function changeDraftModel(nextModel: string) {
    setDraftModel(nextModel);
  }

  function saveModelSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextModel = draftModel.trim();
    if (!nextModel || !selectedProviderModel?.has_key) {
      return;
    }

    setModel(nextModel);
    setModelEdited(nextModel !== getProviderDefaultModel(providerModels, provider));
    setModelDialogOpen(false);
  }

  function openTitleEditor() {
    if (!document) {
      return;
    }
    setDraftTitle(document.title);
    setTitleEditing(true);
  }

  function cancelTitleEditor() {
    setDraftTitle(document?.title ?? "");
    setTitleEditing(false);
  }

  async function saveTitle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!document) {
      return;
    }

    const nextTitle = draftTitle.trim();
    if (!nextTitle) {
      return;
    }
    if (nextTitle === document.title) {
      setTitleEditing(false);
      return;
    }

    setTitleSaving(true);
    setError("");
    try {
      const updated = await patchDocumentTitle(document.id, nextTitle);
      setDocument(updated);
      setDraftTitle(updated.title);
      setTitleEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update document title");
    } finally {
      setTitleSaving(false);
    }
  }

  async function copyParsedText() {
    if (!parsedText || !navigator.clipboard) {
      return;
    }

    await navigator.clipboard.writeText(parsedText);
    setCopiedParsed(true);
    window.setTimeout(() => setCopiedParsed(false), 1600);
  }

  async function reparse() {
    setPending(true);
    setError("");
    try {
      const updated = await reparseDocument(documentId);
      setDocument(updated);
      setParsedText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reparse document");
    } finally {
      setPending(false);
    }
  }

  async function removeDocument() {
    if (!document || !window.confirm(`Delete document "${document.title}"?`)) {
      return;
    }
    setPending(true);
    setError("");
    try {
      await deleteDocument(document.id);
      window.location.href = "/documents";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete document");
      setPending(false);
    }
  }

  async function launchAnalysis() {
    setPending(true);
    setError("");
    try {
      const analysis = await createAnalysis(documentId, {
        provider,
        model: model.trim(),
        document_type_override: document?.detected_document_type,
        run_parameters: {
          output_language: outputLanguage,
        },
      });
      window.location.href = `/analyses/${analysis.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to launch analysis");
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell>
      <main className="document-detail">
        <style>{documentDetailStyles}</style>
        {document ? (
          <>
            <Link className="gc-back-link" href="/documents">
              ‹ Documents
            </Link>

            <section className="gc-document-hero">
              <div className="gc-document-summary">
                <div className="gc-title-line">
                  {titleEditing ? (
                    <form aria-label="Edit document title" className="gc-title-edit-form" onSubmit={saveTitle}>
                      <input
                        aria-label="Document title"
                        autoFocus
                        disabled={titleSaving}
                        maxLength={256}
                        value={draftTitle}
                        onChange={(event) => setDraftTitle(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            cancelTitleEditor();
                          }
                        }}
                      />
                      <button className="gc-title-save-button" disabled={titleSaving || !draftTitle.trim()} type="submit">
                        {titleSaving ? "Saving..." : "Save"}
                      </button>
                      <button className="gc-title-cancel-button" disabled={titleSaving} type="button" onClick={cancelTitleEditor}>
                        Cancel
                      </button>
                    </form>
                  ) : (
                    <>
                      <h1>{document.title}</h1>
                      <button
                        aria-label="Edit document title"
                        className="gc-title-edit-button"
                        disabled={titleSaving}
                        title="Edit document title"
                        type="button"
                        onClick={openTitleEditor}
                      >
                        <span aria-hidden="true">✎</span>
                      </button>
                    </>
                  )}
                </div>
                <p className="gc-muted">
                  {document.original_filename} · {formatDate(document.created_at)}
                </p>

                <div className="gc-stepper" aria-label="Document workflow status">
                  {workflowSteps.map((step) => (
                    <div className={`gc-step is-${step.state}`} key={step.label}>
                      <span aria-hidden="true" />
                      <div>
                        <strong>{step.label}</strong>
                        <small>{step.note}</small>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="gc-action-stack">
                <div className="gc-top-actions" aria-label="Document and analysis actions">
                  <a className="gc-ghost" href={`${resolveApiBaseUrl()}/documents/${document.id}/raw`}>
                    Download raw
                  </a>
                  <button className="gc-ghost" disabled={pending} type="button" onClick={reparse}>
                    Reparse
                  </button>
                  <button className="gc-danger" disabled={pending} type="button" onClick={removeDocument}>
                    Delete
                  </button>
                  <button
                    aria-expanded={modelDialogOpen}
                    className="gc-ghost gc-model-trigger"
                    disabled={pending}
                    type="button"
                    onClick={openModelDialog}
                  >
                    <span>Model</span>
                    <span
                      aria-hidden="true"
                      className={`gc-model-chevron${modelDialogOpen ? " is-open" : ""}`}
                    />
                  </button>
                  <button
                    className="gc-primary"
                    disabled={pending || document.parse_status !== "completed" || !model.trim() || !selectedProviderModel?.has_key}
                    type="button"
                    onClick={launchAnalysis}
                  >
                    {pending ? "Starting..." : "▷ Start analysis"}
                  </button>
                </div>

                {modelDialogOpen ? (
                  <form aria-label="Model settings" className="gc-model-popover" onSubmit={saveModelSettings}>
                    <div className="gc-popover-field">
                      <span>Output language</span>
                      <div className="gc-language-toggle" aria-label="Output language">
                        {outputLanguageOptions.map((language) => (
                          <button
                            aria-pressed={outputLanguage === language}
                            className={`gc-language-option${outputLanguage === language ? " is-active" : ""}`}
                            disabled={pending}
                            key={language}
                            type="button"
                            onClick={() => setOutputLanguage(language)}
                          >
                            {language.toUpperCase()}
                          </button>
                        ))}
                      </div>
                    </div>

                    <label>
                      <span>Model</span>
                      <select
                        disabled={!selectedProviderModel?.has_key || selectedProviderModel.available_models.length === 0}
                        value={draftModel}
                        onChange={(event) => changeDraftModel(event.target.value)}
                      >
                        {(selectedProviderModel?.available_models ?? []).map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>
                    </label>

                    <div className="gc-popover-actions">
                      <button className="gc-primary" disabled={!draftModel.trim() || !selectedProviderModel?.has_key} type="submit">
                        Save
                      </button>
                    </div>
                  </form>
                ) : null}
              </div>
            </section>

            {error ? <section className="gc-alert">{error}</section> : null}

            <div className="gc-detail-columns">
              <section className="gc-panel gc-text-panel">
                <div className="gc-panel-heading">
                  <h2>Parsed document</h2>
                  <button className="gc-copy-action" disabled={!parsedText} type="button" onClick={copyParsedText}>
                    {copiedParsed ? "Copied" : "Copy markdown ⛶"}
                  </button>
                </div>

                {parsedText ? (
                  <MarkdownPreview markdown={parsedText} className="gc-markdown-preview--full" />
                ) : (
                  <div className="gc-empty">Parsed document appears after parsing completes.</div>
                )}
              </section>

              <section className="gc-panel gc-history-panel">
                <div className="gc-panel-heading">
                  <h2>Analysis history</h2>
                </div>

                {analyses.length > 0 ? (
                  <div className="gc-table-scroll">
                    <table className="gc-table">
                      <thead>
                        <tr>
                          <th>Status &amp; verdict</th>
                          <th>Provider</th>
                          <th>Run date</th>
                          <th>Open</th>
                        </tr>
                      </thead>
                      <tbody>
                        {analyses.map((analysis) => {
                          const runDate = formatDateStack(analysis.completed_at ?? analysis.created_at);

                          return (
                            <tr key={analysis.id}>
                              <td>
                                <span className={`gc-run-status is-${getAnalysisTone(analysis.status)}`}>
                                  {formatLabel(analysis.status)}
                                </span>
                                <div className={`gc-verdict-line is-${getVerdictTone(analysis.verdict)}`}>
                                  {formatLabel(analysis.verdict)}
                                </div>
                                {analysis.error_message ? (
                                  <div className="gc-error-text" title={analysis.error_message}>
                                    {formatAnalysisError(analysis.error_message)}
                                  </div>
                                ) : null}
                              </td>
                              <td>
                                <strong>{providerLabels[analysis.provider] ?? formatLabel(analysis.provider)}</strong>
                                <small>{analysis.model}</small>
                                <small className="gc-source-trace">{getSourceTraceLabel(analysis)}</small>
                              </td>
                              <td>
                                <span>{runDate.date}</span>
                                {runDate.time ? <small>{runDate.time}</small> : null}
                              </td>
                              <td className="gc-open-cell">
                                <Link className="gc-compact-link" href={`/analyses/${analysis.id}`}>
                                  Open
                                </Link>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="gc-empty compact">Analysis history appears here after the first run.</div>
                )}
              </section>
            </div>
          </>
        ) : (
          <section className="gc-panel gc-loading">Loading document...</section>
        )}
      </main>
    </AppShell>
  );
}

const documentDetailStyles = `
.document-detail {
  width: min(1536px, 100%);
  min-height: calc(100vh - var(--app-header-height));
  margin: 0 auto;
  padding: 28px 36px 48px;
  color: #111827;
}

.document-detail .gc-back-link {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  margin-bottom: 10px;
  color: #111827;
  font-size: 13px;
  line-height: 18px;
}

.document-detail .gc-back-link:hover {
  color: #075e45;
}

.document-detail .gc-document-hero {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
}

.document-detail .gc-document-summary {
  display: grid;
  min-width: 0;
  gap: 16px;
}

.document-detail .gc-title-line {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 12px;
}

.document-detail h1 {
  margin: 0;
  overflow-wrap: anywhere;
  color: #111827;
  font-size: 28px;
  font-weight: 760;
  line-height: 36px;
  letter-spacing: 0;
}

.document-detail .gc-title-edit-button {
  display: inline-grid;
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  place-items: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #5b6472;
  font-size: 18px;
  line-height: 22px;
}

.document-detail .gc-title-edit-button:hover:not(:disabled) {
  background: #eef8f4;
  color: #075e45;
}

.document-detail .gc-title-edit-form {
  display: flex;
  width: min(720px, 100%);
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.document-detail .gc-title-edit-form input {
  width: 100%;
  min-width: 0;
  min-height: 44px;
  border: 1px solid #b8d8f1;
  border-radius: 6px;
  background: #ffffff;
  color: #111827;
  padding: 0 12px;
  font-size: 24px;
  font-weight: 760;
  line-height: 31px;
}

.document-detail .gc-title-save-button,
.document-detail .gc-title-cancel-button {
  display: inline-flex;
  min-height: 44px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 750;
  line-height: 16px;
  white-space: nowrap;
}

.document-detail .gc-title-save-button {
  border: 1px solid #0e9f6e;
  background: #0e9f6e;
  color: #ffffff;
}

.document-detail .gc-title-save-button:hover:not(:disabled) {
  border-color: #087d5f;
  background: #087d5f;
}

.document-detail .gc-title-cancel-button {
  border: 1px solid #d9e0ea;
  background: #ffffff;
  color: #111827;
}

.document-detail .gc-title-cancel-button:hover:not(:disabled) {
  border-color: #0e9f6e;
  color: #075e45;
}

.document-detail .gc-muted {
  margin: -8px 0 0;
  color: #5b6472;
  font-size: 13px;
  line-height: 18px;
}

.document-detail .gc-action-stack {
  position: relative;
  display: grid;
  justify-items: end;
  gap: 10px;
  min-width: 0;
}

.document-detail .gc-top-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.document-detail .gc-primary,
.document-detail .gc-ghost,
.document-detail .gc-danger,
.document-detail .gc-compact-link,
.document-detail .gc-copy-action {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 750;
  line-height: 16px;
  letter-spacing: 0;
  white-space: nowrap;
}

.document-detail .gc-primary {
  border: 1px solid #0e9f6e;
  background: #0e9f6e;
  color: #ffffff;
  padding: 0 18px;
}

.document-detail .gc-primary:hover:not(:disabled) {
  border-color: #087d5f;
  background: #087d5f;
  color: #ffffff;
}

.document-detail .gc-ghost,
.document-detail .gc-compact-link {
  border: 1px solid #d9e0ea;
  background: #ffffff;
  color: #111827;
  padding: 0 16px;
}

.document-detail .gc-ghost:hover:not(:disabled),
.document-detail .gc-compact-link:hover {
  border-color: #0e9f6e;
  background: #ffffff;
  color: #075e45;
}

.document-detail .gc-model-trigger {
  gap: 8px;
}

.document-detail .gc-model-chevron {
  display: block;
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: translateY(-2px) rotate(45deg);
}

.document-detail .gc-model-chevron.is-open {
  transform: translateY(2px) rotate(225deg);
}

.document-detail .gc-danger {
  border: 1px solid #f2d7d9;
  background: #ffffff;
  color: #c92036;
  padding: 0 16px;
}

.document-detail .gc-danger:hover:not(:disabled) {
  border-color: #e7a8b4;
  background: #fcecee;
  color: #a5122a;
}

.document-detail .gc-primary:disabled,
.document-detail .gc-ghost:disabled,
.document-detail .gc-danger:disabled,
.document-detail .gc-title-edit-button:disabled,
.document-detail .gc-title-save-button:disabled,
.document-detail .gc-title-cancel-button:disabled,
.document-detail .gc-copy-action:disabled {
  cursor: not-allowed;
  opacity: 0.52;
  transform: none;
}

.document-detail .gc-stepper {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 10px;
}

.document-detail .gc-step {
  display: flex;
  width: auto;
  min-width: 150px;
  min-height: 50px;
  flex: 1 1 150px;
  align-items: flex-start;
  gap: 10px;
  border: 1px solid #e5eaf0;
  border-radius: 6px;
  background: #ffffff;
  padding: 9px 12px;
}

.document-detail .gc-step span {
  display: block;
  width: 11px;
  height: 11px;
  flex: 0 0 11px;
  border: 0;
  border-radius: 999px;
  background: #0e9f6e;
}

.document-detail .gc-step.is-active span {
  background: #1d70b8;
}

.document-detail .gc-step.is-idle span {
  border: 1px solid #8a93a3;
  background: transparent;
}

.document-detail .gc-step.is-blocked span {
  border-radius: 2px;
  background: #c92036;
}

.document-detail .gc-step.is-active {
  border-color: #b8d8f1;
}

.document-detail .gc-step.is-blocked {
  border-color: #f2d7d9;
}

.document-detail .gc-step div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.document-detail .gc-step strong,
.document-detail .gc-step small {
  overflow: visible;
  overflow-wrap: anywhere;
  text-overflow: clip;
  white-space: normal;
}

.document-detail .gc-step strong {
  color: #111827;
  font-size: 12px;
  font-weight: 750;
  line-height: 16px;
}

.document-detail .gc-step small {
  color: #5b6472;
  font-size: 11px;
  line-height: 14px;
}

.document-detail .gc-detail-columns {
  display: grid;
  grid-template-columns: minmax(0, 56fr) minmax(420px, 44fr);
  gap: 12px;
  align-items: start;
}

.document-detail .gc-panel {
  min-width: 0;
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: none;
  padding: 24px;
}

.document-detail .gc-text-panel,
.document-detail .gc-history-panel {
  min-height: 728px;
}

.document-detail .gc-panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.document-detail .gc-panel-heading h2 {
  margin: 0;
  color: #111827;
  font-size: 17px;
  font-weight: 760;
  line-height: 22px;
  letter-spacing: 0;
}

.document-detail .gc-copy-action {
  min-height: 44px;
  border: 0;
  background: transparent;
  color: #5b6472;
  padding: 0;
  font-weight: 500;
}

.document-detail .gc-copy-action:hover:not(:disabled) {
  background: transparent;
  color: #075e45;
}

.document-detail .gc-markdown-preview--full {
  overflow-x: auto;
  overflow-y: visible;
  color: #111827;
  font-size: 13px;
  line-height: 22px;
}

.document-detail .gc-markdown-preview--full h1,
.document-detail .gc-markdown-preview--full h2,
.document-detail .gc-markdown-preview--full h3 {
  color: #111827;
  letter-spacing: 0;
}

.document-detail .gc-markdown-preview--full h1 {
  font-size: 22px;
  line-height: 30px;
}

.document-detail .gc-markdown-preview--full h2 {
  font-size: 20px;
  line-height: 28px;
}

.document-detail .gc-markdown-preview--full h3 {
  font-size: 17px;
  line-height: 24px;
}

.document-detail .gc-markdown-preview--full table {
  min-width: 620px;
  overflow: visible;
  border: 1px solid #e5eaf0;
  border-radius: 6px;
  background: #ffffff;
}

.document-detail .gc-markdown-preview--full th,
.document-detail .gc-markdown-preview--full td {
  min-width: 0;
  border-color: #e5eaf0;
  padding: 9px 10px;
  color: #111827;
  font-size: 12px;
  line-height: 22px;
  overflow-wrap: anywhere;
  white-space: normal;
}

.document-detail .gc-markdown-preview--full th {
  background: #fbfcfd;
  font-weight: 750;
  text-transform: none;
}

.document-detail .gc-history-panel {
  padding: 18px;
}

.document-detail .gc-history-panel .gc-panel-heading {
  margin-bottom: 16px;
}

.document-detail .gc-table-scroll {
  width: 100%;
  overflow-x: auto;
  background: #ffffff;
}

.document-detail .gc-table {
  display: table;
  min-width: 560px;
  width: 100%;
  border-collapse: collapse;
  background: #ffffff;
}

.document-detail .gc-history-panel .gc-table {
  display: table;
}

.document-detail .gc-history-panel .gc-table thead {
  display: table-header-group;
}

.document-detail .gc-history-panel .gc-table tbody {
  display: table-row-group;
}

.document-detail .gc-history-panel .gc-table tr {
  display: table-row;
  border: 0;
  background: transparent;
  padding: 0;
}

.document-detail .gc-history-panel .gc-table th,
.document-detail .gc-history-panel .gc-table td {
  display: table-cell;
}

.document-detail .gc-history-panel .gc-table td::before {
  content: none;
}

.document-detail .gc-table th,
.document-detail .gc-table td {
  border-bottom: 1px solid #edf1f5;
  padding: 14px 0;
  color: #111827;
  font-size: 12px;
  line-height: 18px;
  vertical-align: top;
}

.document-detail .gc-table th {
  height: 36px;
  padding-top: 0;
  color: #5b6472;
  font-weight: 500;
  letter-spacing: 0;
  text-transform: none;
}

.document-detail .gc-table th:nth-child(1),
.document-detail .gc-table td:nth-child(1) {
  width: 35%;
  padding-right: 12px;
}

.document-detail .gc-table th:nth-child(2),
.document-detail .gc-table td:nth-child(2) {
  width: 30%;
  padding-right: 12px;
}

.document-detail .gc-table th:nth-child(3),
.document-detail .gc-table td:nth-child(3) {
  width: 20%;
  padding-right: 12px;
}

.document-detail .gc-table th:nth-child(4),
.document-detail .gc-table td:nth-child(4) {
  width: 15%;
  text-align: right;
}

.document-detail .gc-table td strong,
.document-detail .gc-table td small,
.document-detail .gc-table td span {
  display: block;
}

.document-detail .gc-table td strong {
  color: #5b6472;
  font-weight: 500;
}

.document-detail .gc-table td small {
  color: #5b6472;
}

.document-detail .gc-source-trace {
  max-width: 178px;
  overflow: hidden;
  margin-top: 4px;
  color: #8a93a3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-detail .gc-run-status {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  border: 0;
  border-radius: 6px;
  background: #f2f4f7;
  color: #344054;
  padding: 5px 9px;
  font-size: 12px;
  font-weight: 750;
  line-height: 18px;
  text-transform: capitalize;
}

.document-detail .gc-run-status.is-good {
  background: #eaf8f2;
  color: #075e45;
}

.document-detail .gc-run-status.is-info {
  background: #eaf3fb;
  color: #1d70b8;
}

.document-detail .gc-run-status.is-bad {
  background: #fcecee;
  color: #c92036;
}

.document-detail .gc-verdict-line {
  margin-top: 8px;
  color: #344054;
  font-size: 12px;
  line-height: 18px;
}

.document-detail .gc-verdict-line.is-good {
  color: #087d5f;
}

.document-detail .gc-verdict-line.is-warn {
  color: #8a5d00;
}

.document-detail .gc-verdict-line.is-bad {
  color: #c92036;
}

.document-detail .gc-error-text {
  display: -webkit-box;
  max-width: 100%;
  margin-top: 8px;
  overflow: hidden;
  color: #c92036;
  font-size: 12px;
  line-height: 18px;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.document-detail .gc-open-cell {
  text-align: right;
}

.document-detail .gc-compact-link {
  min-height: 44px;
  padding: 0 16px;
}

.document-detail .gc-model-popover {
  position: absolute;
  top: 50px;
  right: 24px;
  z-index: 20;
  display: grid;
  width: 214px;
  gap: 10px;
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 16px 42px rgba(17, 24, 39, 0.12);
  padding: 14px;
}

.document-detail .gc-model-popover label,
.document-detail .gc-popover-field {
  display: grid;
  gap: 6px;
  color: #111827;
  font-size: 12px;
  font-weight: 750;
  line-height: 18px;
}

.document-detail .gc-model-popover select,
.document-detail .gc-model-popover input {
  min-height: 44px;
  border-color: #d9e0ea;
  background: #ffffff;
  color: #111827;
  padding: 0 10px;
  font-size: 12px;
}

.document-detail .gc-language-toggle {
  display: grid;
  min-height: 48px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px;
  border: 1px solid #d9e0ea;
  border-radius: 6px;
  background: #ffffff;
  padding: 2px;
}

.document-detail .gc-language-option {
  min-height: 44px;
  min-width: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #344054;
  cursor: pointer;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0;
}

.document-detail .gc-language-option.is-active,
.document-detail .gc-language-option[aria-pressed="true"] {
  background: #eaf8f2;
  color: #075e45;
}

.document-detail .gc-popover-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
}

.document-detail .gc-popover-actions .gc-ghost,
.document-detail .gc-popover-actions .gc-primary {
  min-height: 44px;
  padding: 0 12px;
  font-size: 12px;
}

.document-detail .gc-alert {
  margin-bottom: 16px;
  border: 1px solid #f2d7d9;
  border-radius: 8px;
  background: #fcecee;
  color: #a5122a;
  padding: 14px 16px;
}

.document-detail .gc-empty,
.document-detail .gc-loading {
  display: grid;
  min-height: 180px;
  place-items: center;
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #fbfcfd;
  color: #5b6472;
  padding: 24px;
  text-align: center;
}

.document-detail .gc-empty.compact {
  min-height: 88px;
}

@media (max-width: 1280px) {
  .document-detail .gc-document-hero {
    flex-direction: column;
  }

  .document-detail .gc-action-stack {
    width: 100%;
    justify-items: start;
  }

  .document-detail .gc-top-actions {
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .document-detail .gc-model-popover {
    right: auto;
    left: 0;
  }
}

@media (max-width: 1100px) {
  .document-detail .gc-detail-columns {
    grid-template-columns: 1fr;
  }

  .document-detail .gc-text-panel,
  .document-detail .gc-history-panel {
    min-height: 0;
  }
}

@media (max-width: 720px) {
  .document-detail {
    padding: 22px 12px 36px;
  }

  .document-detail h1 {
    font-size: 24px;
    line-height: 31px;
  }

  .document-detail .gc-title-edit-form {
    flex-wrap: wrap;
  }

  .document-detail .gc-title-edit-form input {
    flex: 1 0 100%;
    font-size: 22px;
    line-height: 29px;
  }

  .document-detail .gc-stepper {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .document-detail .gc-step {
    width: auto;
  }

  .document-detail .gc-top-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .document-detail .gc-top-actions .gc-primary {
    grid-column: 1 / -1;
  }

  .document-detail .gc-model-popover {
    position: static;
    width: min(100%, 320px);
  }

  .document-detail .gc-panel {
    padding: 18px;
  }
}

@media (max-width: 460px) {
  .document-detail .gc-stepper,
  .document-detail .gc-top-actions {
    grid-template-columns: 1fr;
  }

  .document-detail .gc-panel-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
`;
