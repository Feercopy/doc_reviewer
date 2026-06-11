"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { MarkdownPreview } from "@/components/MarkdownPreview";
import { resolveApiBaseUrl } from "@/lib/api/client";
import {
  getProviderDefaultModel,
  listProviderKeys,
  type ProviderKeyRecord,
} from "@/lib/api/provider-settings";
import {
  createAnalysis,
  deleteDocument,
  getDocument,
  getParsedText,
  listAnalyses,
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
  const hasCompletedAnalysis = analyses.some((analysis) => analysis.status === "completed");
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
      note: formatLabel(document.parse_status),
      state: parseDone ? "done" : parseFailed ? "blocked" : "active",
    },
    {
      label: "Ready",
      note: parseDone ? formatLabel(document.manual_document_type ?? document.detected_document_type) : "Waiting on parser",
      state: parseDone ? "done" : "idle",
    },
    {
      label: "Analysis complete",
      note: hasCompletedAnalysis ? "Completed run available" : hasRunningAnalysis ? "Run in progress" : "No completed run",
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
  const [providerKeys, setProviderKeys] = useState<ProviderKeyRecord[]>([]);
  const [provider, setProvider] = useState<Provider>("openai_compatible");
  const [model, setModel] = useState("");
  const [modelEdited, setModelEdited] = useState(false);
  const [outputLanguage, setOutputLanguage] = useState<OutputLanguage>("en");
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [draftProvider, setDraftProvider] = useState<Provider>("openai_compatible");
  const [draftModel, setDraftModel] = useState("");
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

    listProviderKeys()
      .then((response) => {
        if (!ignore) {
          setProviderKeys(response.provider_keys);
        }
      })
      .catch(() => setProviderKeys([]));

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (modelEdited) {
      return;
    }
    const defaultModel = getProviderDefaultModel(providerKeys, provider);
    if (defaultModel) {
      setModel(defaultModel);
    }
  }, [modelEdited, provider, providerKeys]);

  const savedProviderKeys = useMemo(() => providerKeys.filter((item) => item.has_key), [providerKeys]);
  const providerKeyOptions = savedProviderKeys.length > 0 ? savedProviderKeys : providerKeys;
  const selectedProviderKey = useMemo(
    () => providerKeys.find((item) => item.provider === provider) ?? null,
    [provider, providerKeys],
  );
  const selectedDraftProviderKey = useMemo(
    () => providerKeys.find((item) => item.provider === draftProvider) ?? null,
    [draftProvider, providerKeys],
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
    if (savedProviderKeys.length === 0 || savedProviderKeys.some((item) => item.provider === provider)) {
      return;
    }

    const nextProvider = savedProviderKeys[0].provider;
    setProvider(nextProvider);
    setModelEdited(false);
    setModel(getProviderDefaultModel(providerKeys, nextProvider));
  }, [provider, providerKeys, savedProviderKeys]);

  function openModelDialog() {
    setDraftProvider(provider);
    setDraftModel(model);
    setModelDialogOpen(true);
  }

  function changeDraftProvider(nextProvider: Provider) {
    setDraftProvider(nextProvider);
    setDraftModel(getProviderDefaultModel(providerKeys, nextProvider));
  }

  function changeDraftModel(nextModel: string) {
    setDraftModel(nextModel);
  }

  function saveModelSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextModel = draftModel.trim();
    if (!nextModel || !selectedDraftProviderKey?.has_key) {
      return;
    }

    setProvider(draftProvider);
    setModel(nextModel);
    setModelEdited(nextModel !== getProviderDefaultModel(providerKeys, draftProvider));
    setModelDialogOpen(false);
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
      <main className="gc-dark-page document-workflow">
        <style>{`${detailStyles}\n${paperDetailOverrides}`}</style>
        {document ? (
          <>
            <section className="gc-hero">
              <div className="gc-hero__content">
                <p className="gc-eyebrow">Document workflow</p>
                <div className="gc-hero__title-row">
                  <div className="gc-hero__title-copy">
                    <h1>{document.title}</h1>
                    <p className="gc-muted">
                      {document.original_filename} · {formatDate(document.created_at)}
                    </p>
                  </div>
                  <div className="gc-stepper" aria-label="Document workflow status">
                    {workflowSteps.map((step, index) => (
                      <div className={`gc-step is-${step.state}`} key={step.label}>
                        <span>{index + 1}</span>
                        <div>
                          <strong>{step.label}</strong>
                          <small>{step.note}</small>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            {error ? <section className="gc-alert">{error}</section> : null}

            <div className="gc-detail-grid">
              <div className="gc-left-column">
                <section className="gc-panel gc-text-panel">
                  <div className="gc-panel-heading">
                    <div>
                      <h2>Parsed text</h2>
                      <p>{parsedText ? `${parsedText.length.toLocaleString()} characters extracted` : "Text appears after parsing completes."}</p>
                    </div>
                    <div className="gc-action-row gc-document-actions" aria-label="Document actions">
                      <a className="gc-ghost" href={`${resolveApiBaseUrl()}/documents/${document.id}/raw`}>
                        Download raw
                      </a>
                      <button className="gc-ghost" disabled={pending} type="button" onClick={reparse}>
                        Reparse
                      </button>
                      <button className="gc-danger" disabled={pending} type="button" onClick={removeDocument}>
                        Delete
                      </button>
                    </div>
                  </div>

                  {parsedText ? (
                    <MarkdownPreview markdown={parsedText} className="gc-markdown-preview--full" />
                  ) : (
                    <div className="gc-empty">Parsed text is not available yet.</div>
                  )}
                </section>
              </div>

              <aside className="gc-right-column">
                <section className="gc-panel gc-history-panel">
                  <div className="gc-panel-heading">
                    <div>
                      <h2>Analysis history</h2>
                      <p>{analyses.length ? `${analyses.length} run${analyses.length === 1 ? "" : "s"}` : "No runs yet."}</p>
                    </div>
                  </div>

                  <div className="gc-history-actions" aria-label="Analysis actions">
                    <button className="gc-ghost" disabled={pending} type="button" onClick={openModelDialog}>
                      Model
                    </button>
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
                    <button
                      className="gc-primary"
                      disabled={pending || document.parse_status !== "completed" || !model.trim() || !selectedProviderKey?.has_key}
                      type="button"
                      onClick={launchAnalysis}
                    >
                      {pending ? "Starting..." : "Start new analysis"}
                    </button>
                  </div>

                  {analyses.length > 0 ? (
                    <div className="gc-table-scroll">
                      <table className="gc-table">
                        <thead>
                          <tr>
                            <th>Status</th>
                            <th>Provider</th>
                            <th>Verdict</th>
                            <th>Skill snapshot</th>
                            <th>Created</th>
                            <th>Open</th>
                          </tr>
                        </thead>
                        <tbody>
                          {analyses.map((analysis) => (
                            <tr key={analysis.id}>
                              <td>
                                <span className={`gc-run-status is-${getAnalysisTone(analysis.status)}`}>
                                  {formatLabel(analysis.status)}
                                </span>
                                {analysis.error_message ? (
                                  <div className="gc-error-text" title={analysis.error_message}>
                                    {formatAnalysisError(analysis.error_message)}
                                  </div>
                                ) : null}
                              </td>
                              <td>
                                <strong>{formatLabel(analysis.provider)}</strong>
                                <small>{analysis.model}</small>
                              </td>
                              <td>{formatLabel(analysis.verdict)}</td>
                              <td>
                                <span className="gc-source-trace">{getSourceTraceLabel(analysis)}</span>
                              </td>
                              <td>{formatDate(analysis.created_at)}</td>
                              <td>
                                <Link className="gc-compact-link" href={`/analyses/${analysis.id}`}>
                                  Open
                                </Link>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="gc-empty compact">Analysis history appears here after the first run.</div>
                  )}
                </section>
              </aside>
            </div>

            {modelDialogOpen ? (
              <div
                className="gc-modal-backdrop"
                onMouseDown={(event) => {
                  if (event.currentTarget === event.target) {
                    setModelDialogOpen(false);
                  }
                }}
              >
                <form
                  aria-labelledby="gc-model-dialog-title"
                  aria-modal="true"
                  className="gc-model-modal"
                  role="dialog"
                  onSubmit={saveModelSettings}
                >
                  <div className="gc-model-modal-header">
                    <h2 id="gc-model-dialog-title">Model</h2>
                    <button className="gc-icon-button" type="button" aria-label="Close" onClick={() => setModelDialogOpen(false)}>
                      x
                    </button>
                  </div>

                  <div className="gc-field-stack">
                    <label>
                      <span>Saved key</span>
                      <select
                        disabled={providerKeyOptions.length === 0}
                        value={draftProvider}
                        onChange={(event) => changeDraftProvider(event.target.value as Provider)}
                      >
                        {providerKeyOptions.length > 0 ? (
                          providerKeyOptions.map((item) => (
                            <option key={item.provider} value={item.provider}>
                              {providerLabels[item.provider]}
                              {item.api_key_fingerprint ? ` · ${item.api_key_fingerprint}` : ""}
                            </option>
                          ))
                        ) : (
                          <option value={draftProvider}>No saved keys</option>
                        )}
                      </select>
                    </label>

                    <label>
                      <span>Model</span>
                      <input value={draftModel} onChange={(event) => changeDraftModel(event.target.value)} />
                    </label>
                  </div>

                  {!selectedDraftProviderKey?.has_key ? (
                    <div className="gc-provider-note is-warning">
                      <strong>No saved key</strong>
                      <span>Add a provider key in Settings before starting analysis.</span>
                    </div>
                  ) : null}

                  <div className="gc-modal-actions">
                    <button className="gc-primary" disabled={!draftModel.trim() || !selectedDraftProviderKey?.has_key} type="submit">
                      Save
                    </button>
                  </div>
                </form>
              </div>
            ) : null}
          </>
        ) : (
          <section className="gc-panel gc-loading">Loading document...</section>
        )}
      </main>
    </AppShell>
  );
}

const detailStyles = `
.shell:has(.gc-dark-page) {
  background: #070a12;
}

.shell:has(.gc-dark-page) .topbar {
  border-bottom-color: rgba(148, 163, 184, 0.16);
  background: #090d16;
  color: #f8fafc;
}

.shell:has(.gc-dark-page) .nav {
  color: #a8b3c7;
}

.shell:has(.gc-dark-page) .brand {
  color: #f8fafc;
}

.shell:has(.gc-dark-page) .topbar button.secondary {
  border-color: rgba(148, 163, 184, 0.22);
  background: #111827;
  color: #f8fafc;
}

.gc-dark-page {
  width: min(1680px, 100%);
  min-height: calc(100vh - 69px);
  margin: 0 auto;
  padding: 32px 24px 48px;
  color: #eef2ff;
}

.gc-hero,
.gc-action-row {
  display: flex;
}

.gc-hero {
  align-items: flex-start;
  justify-content: flex-start;
  gap: 24px;
  margin-bottom: 18px;
}

.gc-hero__content {
  display: grid;
  width: 100%;
  min-width: 0;
}

.gc-hero__title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  min-width: 0;
}

.gc-hero__title-copy {
  min-width: 0;
}

.gc-hero h1 {
  max-width: 980px;
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 38px;
  line-height: 1.08;
  letter-spacing: 0;
}

.gc-eyebrow {
  margin: 0 0 8px;
  color: #7dd3fc;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.gc-muted,
.gc-panel-heading p,
.gc-provider-note span,
.gc-table small,
.gc-note {
  color: #94a3b8;
}

.gc-muted {
  margin: 8px 0 0;
}

.gc-action-row {
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.gc-primary,
.gc-ghost,
.gc-danger,
.gc-compact-link {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-weight: 800;
  letter-spacing: 0;
  white-space: nowrap;
}

.gc-primary:disabled,
.gc-ghost:disabled,
.gc-danger:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.gc-primary {
  border: 1px solid #22d3ee;
  background: #06b6d4;
  color: #07111f;
  padding: 0 16px;
}

.gc-ghost {
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.88);
  color: #dbeafe;
  padding: 0 14px;
}

.gc-danger {
  border: 1px solid rgba(248, 113, 113, 0.34);
  background: rgba(127, 29, 29, 0.18);
  color: #fecaca;
  padding: 0 14px;
}

.gc-stepper {
  display: flex;
  width: auto;
  flex: 0 1 760px;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 0;
}

.gc-step {
  display: flex;
  min-height: 42px;
  flex: 0 1 178px;
  max-width: 188px;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: #0d1424;
  padding: 7px 9px;
}

.gc-step span {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 900;
}

.gc-step div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.gc-step strong {
  overflow: hidden;
  color: #f8fafc;
  font-size: 12px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-step small {
  overflow: hidden;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-step.is-done {
  border-color: rgba(34, 197, 94, 0.28);
}

.gc-step.is-done span {
  border-color: rgba(34, 197, 94, 0.42);
  background: rgba(20, 83, 45, 0.34);
  color: #86efac;
}

.gc-step.is-active {
  border-color: rgba(56, 189, 248, 0.34);
}

.gc-step.is-active span {
  border-color: rgba(56, 189, 248, 0.48);
  background: rgba(12, 74, 110, 0.38);
  color: #7dd3fc;
}

.gc-step.is-blocked {
  border-color: rgba(248, 113, 113, 0.36);
}

.gc-step.is-blocked span {
  border-color: rgba(248, 113, 113, 0.48);
  background: rgba(127, 29, 29, 0.34);
  color: #fecaca;
}

.gc-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 400px);
  gap: 16px;
  align-items: start;
}

.gc-left-column,
.gc-right-column {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.gc-panel {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: #0d1424;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.24);
  padding: 16px;
}

.gc-text-panel {
  min-width: 0;
}

.gc-text-panel .gc-markdown-preview--full {
  overflow-x: auto;
  overflow-y: visible;
}

.gc-panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.gc-panel-heading h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 16px;
  letter-spacing: 0;
}

.gc-panel-heading p {
  margin: 5px 0 0;
  font-size: 13px;
}

.gc-dark-page .badge {
  border: 1px solid rgba(148, 163, 184, 0.24);
  background: rgba(15, 23, 42, 0.96);
  color: #cbd5e1;
}

.gc-dark-page .badge.ok {
  border-color: rgba(34, 197, 94, 0.38);
  background: rgba(20, 83, 45, 0.36);
  color: #86efac;
}

.gc-dark-page .badge.info {
  border-color: rgba(56, 189, 248, 0.38);
  background: rgba(12, 74, 110, 0.36);
  color: #7dd3fc;
}

.gc-dark-page .badge.danger {
  border-color: rgba(248, 113, 113, 0.42);
  background: rgba(127, 29, 29, 0.32);
  color: #fca5a5;
}

.gc-field-stack span {
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-dark-page input,
.gc-dark-page select {
  border-color: rgba(148, 163, 184, 0.22);
  background: #090d16;
  color: #eef2ff;
}

.gc-dark-page input::placeholder {
  color: #64748b;
}

.gc-note {
  margin-top: 12px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.52);
  padding: 12px;
  line-height: 1.5;
}

.gc-alert {
  margin-bottom: 16px;
  border: 1px solid rgba(248, 113, 113, 0.34);
  border-radius: 8px;
  background: rgba(127, 29, 29, 0.28);
  color: #fecaca;
  padding: 14px 16px;
}

.gc-alert.compact {
  margin: 12px 0 0;
}

.gc-action-row {
  margin-top: 14px;
}

.gc-document-actions {
  flex: 0 0 auto;
  margin-top: 0;
  justify-content: flex-end;
}

.gc-field-stack label {
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-field-stack {
  display: grid;
  gap: 14px;
}

.gc-provider-note {
  display: grid;
  gap: 4px;
  margin-top: 14px;
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  background: rgba(12, 74, 110, 0.2);
  padding: 12px;
}

.gc-provider-note strong {
  color: #e0f2fe;
}

.gc-provider-note span {
  line-height: 1.4;
}

.gc-provider-note.is-warning {
  border-color: rgba(250, 204, 21, 0.32);
  background: rgba(113, 63, 18, 0.18);
}

.gc-provider-note.is-warning strong {
  color: #fde68a;
}

.gc-history-actions {
  display: grid;
  grid-template-columns: minmax(76px, 0.65fr) minmax(90px, auto) minmax(138px, 1.35fr);
  align-items: stretch;
  gap: 10px;
  margin-bottom: 12px;
  border: 1px solid rgba(34, 211, 238, 0.18);
  border-radius: 8px;
  background: rgba(8, 145, 178, 0.12);
  padding: 12px;
}

.gc-history-actions .gc-ghost,
.gc-history-actions .gc-primary {
  width: 100%;
  min-width: 0;
  padding-inline: 12px;
}

.gc-language-toggle {
  display: grid;
  min-width: 90px;
  min-height: 40px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.88);
  padding: 2px;
}

.gc-language-option {
  min-width: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0;
}

.gc-language-option.is-active {
  background: #22d3ee;
  color: #07111f;
}

.gc-language-option:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.gc-table-scroll {
  width: 100%;
  overflow-x: auto;
}

.gc-table {
  min-width: 820px;
}

.gc-history-panel .gc-table {
  display: block;
  min-width: 0;
  width: 100%;
}

.gc-history-panel .gc-table thead {
  display: none;
}

.gc-history-panel .gc-table tbody {
  display: grid;
  gap: 10px;
}

.gc-history-panel .gc-table tr {
  display: grid;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.56);
  padding: 12px;
}

.gc-history-panel .gc-table td {
  display: grid;
  gap: 4px;
  min-width: 0;
  border-bottom: 0;
  padding: 0;
}

.gc-history-panel .gc-table td::before {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 850;
  text-transform: uppercase;
}

.gc-history-panel .gc-table td:nth-child(1)::before {
  content: "Status";
}

.gc-history-panel .gc-table td:nth-child(2)::before {
  content: "Provider";
}

.gc-history-panel .gc-table td:nth-child(3)::before {
  content: "Verdict";
}

.gc-history-panel .gc-table td:nth-child(4)::before {
  content: "Skill snapshot";
}

.gc-history-panel .gc-table td:nth-child(5)::before {
  content: "Created";
}

.gc-history-panel .gc-table td:nth-child(6)::before {
  content: "Open";
}

.gc-table th,
.gc-table td {
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  padding: 11px 10px;
}

.gc-table th {
  color: #94a3b8;
  font-size: 11px;
  letter-spacing: 0;
}

.gc-table td strong,
.gc-table td small {
  display: block;
}

.gc-run-status,
.gc-source-trace {
  display: inline-flex;
  min-height: 26px;
  align-items: center;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.74);
  color: #cbd5e1;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-run-status.is-good {
  border-color: rgba(34, 197, 94, 0.36);
  color: #bbf7d0;
}

.gc-run-status.is-info {
  border-color: rgba(56, 189, 248, 0.36);
  color: #bae6fd;
}

.gc-run-status.is-bad {
  border-color: rgba(248, 113, 113, 0.42);
  color: #fecaca;
}

.gc-source-trace {
  max-width: 100%;
  overflow: hidden;
  color: #bae6fd;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-error-text {
  display: -webkit-box;
  max-width: 100%;
  margin-top: 8px;
  overflow: hidden;
  color: #fca5a5;
  font-size: 12px;
  line-height: 1.4;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.gc-compact-link {
  min-height: 34px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.92);
  color: #dbeafe;
  padding: 0 10px;
  font-size: 12px;
}

.gc-empty,
.gc-loading {
  display: grid;
  place-items: center;
  min-height: 180px;
  color: #94a3b8;
  text-align: center;
}

.gc-empty.compact {
  min-height: 88px;
}

.gc-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  align-items: start;
  justify-items: center;
  background: rgba(3, 7, 18, 0.62);
  padding: 112px 16px 24px;
}

.gc-model-modal {
  width: min(420px, 100%);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: #0d1424;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.46);
  padding: 16px;
}

.gc-model-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.gc-model-modal-header h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 16px;
  letter-spacing: 0;
}

.gc-icon-button {
  display: inline-grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.82);
  color: #dbeafe;
  cursor: pointer;
  font-size: 15px;
  font-weight: 900;
}

.gc-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

@media (max-width: 1100px) {
  .gc-detail-grid {
    grid-template-columns: 1fr;
  }

  .gc-hero__title-row {
    flex-direction: column;
    justify-content: flex-start;
  }

  .gc-stepper {
    width: min(100%, 940px);
    flex: none;
    justify-content: flex-start;
  }

  .gc-step {
    flex: 1 1 190px;
    max-width: none;
  }

  .gc-right-column {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .gc-right-column {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .gc-dark-page {
    padding: 22px 10px 36px;
  }

  .gc-hero {
    align-items: stretch;
    flex-direction: column;
  }

  .gc-hero h1 {
    font-size: 30px;
  }

  .gc-stepper {
    width: 100%;
  }

  .gc-step {
    flex-basis: calc(50% - 4px);
  }

  .gc-panel-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .gc-document-actions {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
  }

  .gc-document-actions .gc-ghost,
  .gc-document-actions .gc-danger {
    min-width: 0;
    padding-inline: 10px;
  }
}

@media (max-width: 460px) {
  .gc-step small {
    display: none;
  }

  .gc-history-actions {
    grid-template-columns: minmax(0, 1fr) minmax(90px, auto);
  }

  .gc-history-actions .gc-primary {
    grid-column: 1 / -1;
  }

  .gc-document-actions {
    grid-template-columns: 1fr;
  }
}
`;

const paperDetailOverrides = `
.shell:has(.gc-dark-page) {
  background: #f7f9fb;
}

.gc-dark-page {
  width: min(1536px, 100%);
  min-height: calc(100vh - 64px);
  padding: 28px 36px 48px;
  color: #111827;
}

.gc-hero h1 {
  color: #111827;
  font-size: 28px;
  font-weight: 760;
  line-height: 36px;
}

.gc-eyebrow {
  color: #5b6472;
}

.gc-muted,
.gc-panel-heading p,
.gc-provider-note span,
.gc-table small,
.gc-note,
.gc-step small {
  color: #5b6472;
}

.gc-stepper {
  flex: 0 1 680px;
  gap: 10px;
}

.gc-step {
  min-height: 50px;
  border: 1px solid #e5eaf0;
  background: #ffffff;
  color: #111827;
}

.gc-step span {
  border-color: transparent;
  background: transparent;
  color: #0e9f6e;
}

.gc-step strong {
  color: #111827;
}

.gc-step.is-done {
  border-color: #e5eaf0;
}

.gc-step.is-done span {
  border-color: transparent;
  background: transparent;
  color: #0e9f6e;
}

.gc-step.is-active {
  border-color: #1d70b8;
}

.gc-step.is-active span {
  border-color: transparent;
  background: transparent;
  color: #1d70b8;
}

.gc-step.is-blocked {
  border-color: #f2d7d9;
}

.gc-step.is-blocked span {
  border-color: transparent;
  background: transparent;
  color: #c92036;
}

.gc-detail-grid {
  gap: 12px;
}

.gc-panel,
.gc-model-modal,
.gc-provider-note,
.gc-run-status,
.gc-source-trace {
  border-color: #e5eaf0;
  background: #ffffff;
  box-shadow: none;
}

.gc-text-panel {
  min-height: 728px;
}

.gc-panel-heading h2,
.gc-table th,
.gc-table td,
.gc-markdown-preview--full,
.gc-model-modal h2 {
  color: #111827;
}

.gc-primary {
  border-color: #0e9f6e;
  background: #0e9f6e;
  color: #ffffff;
}

.gc-primary:hover:not(:disabled) {
  border-color: #087d5f;
  background: #087d5f;
}

.gc-ghost,
.gc-compact-link,
.gc-icon-button {
  border-color: #d9e0ea;
  background: #ffffff;
  color: #111827;
}

.gc-ghost:hover,
.gc-compact-link:hover,
.gc-icon-button:hover {
  border-color: #0e9f6e;
  color: #075e45;
}

.gc-danger {
  border-color: #f2d7d9;
  background: #ffffff;
  color: #c92036;
}

.gc-danger:hover:not(:disabled) {
  background: #fcecee;
}

.gc-dark-page input,
.gc-dark-page select,
.gc-dark-page textarea {
  border-color: #d9e0ea;
  background: #ffffff;
  color: #111827;
}

.gc-dark-page input::placeholder,
.gc-dark-page textarea::placeholder {
  color: #8a93a3;
}

.gc-table-scroll,
.gc-table {
  background: #ffffff;
}

.gc-table th,
.gc-table td {
  border-bottom-color: #edf1f5;
}

.gc-table thead {
  background: #fbfcfd;
}

.gc-table tbody tr:hover td {
  background: #fbfcfd;
}

.gc-history-panel .gc-table tr {
  border-color: #e5eaf0;
  background: #ffffff;
}

.gc-history-panel .gc-table td::before {
  color: #5b6472;
}

.gc-run-status {
  border-color: transparent;
  background: #f2f4f7;
  color: #344054;
}

.gc-run-status.is-good {
  background: #eaf8f2;
  color: #075e45;
}

.gc-run-status.is-info {
  background: #eaf3fb;
  color: #1d70b8;
}

.gc-run-status.is-bad,
.gc-error-text {
  color: #c92036;
}

.gc-run-status.is-bad {
  background: #fcecee;
}

.gc-language-toggle,
.gc-language-option {
  border-color: #d9e0ea;
  background: #ffffff;
  color: #344054;
}

.gc-language-option.is-active,
.gc-language-option[aria-pressed="true"] {
  background: #eaf8f2;
  color: #075e45;
}

.gc-provider-note.is-warning {
  border-color: #f4d98d;
  background: #fff7df;
}

.gc-provider-note.is-warning strong,
.gc-provider-note.is-warning span {
  color: #7a4300;
}

.gc-modal-backdrop {
  background: rgba(17, 24, 39, 0.28);
}

.gc-model-modal {
  box-shadow: 0 16px 42px rgba(17, 24, 39, 0.12);
}

.gc-alert {
  border: 1px solid #f2d7d9;
  background: #fcecee;
  color: #a5122a;
}

.gc-empty {
  border-color: #e5eaf0;
  background: #fbfcfd;
  color: #5b6472;
}

.gc-dark-page .badge {
  border-color: transparent;
  background: #f2f4f7;
  color: #344054;
}

.gc-dark-page .badge.ok {
  background: #eaf8f2;
  color: #075e45;
}

.gc-dark-page .badge.info {
  background: #eaf3fb;
  color: #1d70b8;
}

.gc-dark-page .badge.danger {
  background: #fcecee;
  color: #a5122a;
}

@media (max-width: 720px) {
  .gc-dark-page {
    padding: 22px 12px 36px;
  }
}
`;
