"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { resolveApiBaseUrl } from "@/lib/api/client";
import {
  getProviderDefaultModel,
  listProviderKeys,
  type ProviderKeyRecord,
} from "@/lib/api/provider-settings";
import {
  USER_SELECTABLE_DOCUMENT_TYPES,
  createAnalysis,
  deleteDocument,
  getDocument,
  getParsedText,
  listAnalyses,
  patchDocumentType,
  reparseDocument,
  type AnalysisRecord,
  type DocumentRecord,
  type DocumentType,
  type Provider,
  type RunStatus,
} from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

type WorkflowStep = {
  label: string;
  note: string;
  state: "done" | "active" | "blocked" | "idle";
};

type ParsedSection = {
  id: string;
  label: string;
  line: number;
};

const providerLabels: Record<Provider, string> = {
  openai_compatible: "OpenAI compatible",
  anthropic_compatible: "Anthropic compatible",
  hermes: "Hermes",
};

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

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

function extractSections(text: string): ParsedSection[] {
  if (!text) {
    return [];
  }

  return text
    .split(/\r?\n/)
    .map((line, index) => ({ line: line.trim(), index }))
    .filter(({ line }) => {
      if (!line) {
        return false;
      }
      return /^#{1,4}\s+\S/.test(line) || (/^[A-Z0-9][A-Z0-9\s:.-]{6,80}$/.test(line) && line.length <= 90);
    })
    .slice(0, 8)
    .map(({ line, index }) => ({
      id: `${index}-${line.slice(0, 20)}`,
      label: line.replace(/^#{1,4}\s+/, ""),
      line: index + 1,
    }));
}

function countMatches(text: string, query: string): number {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return 0;
  }
  return text.toLowerCase().split(normalizedQuery).length - 1;
}

function getPreviewText(text: string, query: string): string {
  const trimmedQuery = query.trim().toLowerCase();
  if (!text) {
    return "";
  }
  if (!trimmedQuery) {
    return text;
  }

  const index = text.toLowerCase().indexOf(trimmedQuery);
  if (index === -1) {
    return "";
  }

  const start = Math.max(0, index - 1200);
  const end = Math.min(text.length, index + trimmedQuery.length + 2400);
  const prefix = start > 0 ? "...\n" : "";
  const suffix = end < text.length ? "\n..." : "";
  return `${prefix}${text.slice(start, end)}${suffix}`;
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

export default function DocumentDetailPage() {
  const params = useParams<{ documentId: string }>();
  const documentId = params.documentId;
  const [document, setDocument] = useState<DocumentRecord | null>(null);
  const [parsedText, setParsedText] = useState("");
  const [analyses, setAnalyses] = useState<AnalysisRecord[]>([]);
  const [manualType, setManualType] = useState<DocumentType | "">("");
  const [providerKeys, setProviderKeys] = useState<ProviderKeyRecord[]>([]);
  const [provider, setProvider] = useState<Provider>("openai_compatible");
  const [model, setModel] = useState("");
  const [modelEdited, setModelEdited] = useState(false);
  const [textQuery, setTextQuery] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    const nextDocument = await getDocument(documentId);
    setDocument(nextDocument);
    setManualType(nextDocument.manual_document_type ?? "");
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

  const selectedProviderKey = useMemo(
    () => providerKeys.find((item) => item.provider === provider) ?? null,
    [provider, providerKeys],
  );
  const providerDefaultModel = useMemo(() => getProviderDefaultModel(providerKeys, provider), [provider, providerKeys]);
  const workflowSteps = useMemo(() => (document ? buildWorkflowSteps(document, analyses) : []), [analyses, document]);
  const parsedSections = useMemo(() => extractSections(parsedText), [parsedText]);
  const searchMatchCount = useMemo(() => countMatches(parsedText, textQuery), [parsedText, textQuery]);
  const previewText = useMemo(() => getPreviewText(parsedText, textQuery), [parsedText, textQuery]);
  const latestAnalysis = analyses[0] ?? null;

  function changeProvider(nextProvider: Provider) {
    setProvider(nextProvider);
    setModelEdited(false);
    setModel(getProviderDefaultModel(providerKeys, nextProvider));
  }

  function changeModel(nextModel: string) {
    setModel(nextModel);
    setModelEdited(true);
  }

  async function saveType() {
    setPending(true);
    setError("");
    try {
      const updated = await patchDocumentType(documentId, manualType || null);
      setDocument(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update document type");
    } finally {
      setPending(false);
    }
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

  async function launchAnalysis(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const analysis = await createAnalysis(documentId, {
        provider,
        model,
        document_type_override: manualType || document?.manual_document_type || document?.detected_document_type,
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
        <style>{detailStyles}</style>
        {document ? (
          <>
            <section className="gc-hero">
              <div>
                <p className="gc-eyebrow">Document workflow</p>
                <h1>{document.title}</h1>
                <p className="gc-muted">
                  {document.original_filename} · {formatDate(document.created_at)}
                </p>
              </div>
              <div className="gc-hero-actions">
                <a className="gc-ghost" href={`${resolveApiBaseUrl()}/documents/${document.id}/raw`}>
                  Raw
                </a>
                <button className="gc-ghost" disabled={pending} type="button" onClick={reparse}>
                  Reparse
                </button>
                <button className="gc-danger" disabled={pending} type="button" onClick={removeDocument}>
                  Delete
                </button>
              </div>
            </section>

            <section className="gc-stepper" aria-label="Document workflow status">
              {workflowSteps.map((step, index) => (
                <div className={`gc-step is-${step.state}`} key={step.label}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{step.label}</strong>
                    <small>{step.note}</small>
                  </div>
                </div>
              ))}
            </section>

            {error ? <section className="gc-alert">{error}</section> : null}

            <div className="gc-detail-grid">
              <div className="gc-left-column">
                <section className="gc-panel">
                  <div className="gc-panel-heading">
                    <div>
                      <h2>Document metadata</h2>
                      <p>Parser state and document type controls.</p>
                    </div>
                    <StatusBadge status={document.parse_status} />
                  </div>

                  <div className="gc-meta-grid">
                    <div>
                      <span>Detected type</span>
                      <strong>{formatLabel(document.detected_document_type)}</strong>
                      {document.document_type_confidence ? <small>confidence {document.document_type_confidence}</small> : null}
                    </div>
                    <div>
                      <span>Manual type</span>
                      <select value={manualType} onChange={(event) => setManualType(event.target.value as DocumentType | "")}>
                        {["", ...USER_SELECTABLE_DOCUMENT_TYPES].map((item) => (
                          <option key={item || "auto"} value={item}>
                            {item ? formatLabel(item) : "Auto"}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <span>File size</span>
                      <strong>{formatBytes(document.file_size_bytes)}</strong>
                      <small>{document.mime_type}</small>
                    </div>
                    <div>
                      <span>Last updated</span>
                      <strong>{formatDate(document.updated_at)}</strong>
                    </div>
                  </div>

                  {document.document_type_explanation ? (
                    <div className="gc-note">{document.document_type_explanation}</div>
                  ) : null}
                  {document.parse_error ? <div className="gc-alert compact">{document.parse_error}</div> : null}

                  <div className="gc-action-row">
                    <button className="gc-primary" disabled={pending} type="button" onClick={saveType}>
                      Save type
                    </button>
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
                </section>

                <section className="gc-panel gc-text-panel">
                  <div className="gc-panel-heading">
                    <div>
                      <h2>Parsed text</h2>
                      <p>{parsedText ? `${parsedText.length.toLocaleString()} characters extracted` : "Text appears after parsing completes."}</p>
                    </div>
                  </div>

                  {parsedText ? (
                    <>
                      <div className="gc-text-tools">
                        <label>
                          <span>Search parsed text</span>
                          <input
                            placeholder="Evidence, metric, risk, section"
                            value={textQuery}
                            onChange={(event) => setTextQuery(event.target.value)}
                          />
                        </label>
                        <div className="gc-search-count">
                          {textQuery.trim()
                            ? `${searchMatchCount} match${searchMatchCount === 1 ? "" : "es"}`
                            : "Full parsed text"}
                        </div>
                      </div>

                      {parsedSections.length > 0 ? (
                        <div className="gc-section-list" aria-label="Detected text sections">
                          {parsedSections.map((section) => (
                            <span key={section.id}>
                              L{section.line} · {section.label}
                            </span>
                          ))}
                        </div>
                      ) : null}

                      {previewText ? (
                        <pre className="gc-text-preview">{previewText}</pre>
                      ) : (
                        <div className="gc-empty compact">No parsed text match for the current search.</div>
                      )}
                    </>
                  ) : (
                    <div className="gc-empty">Parsed text is not available yet.</div>
                  )}
                </section>
              </div>

              <aside className="gc-right-column">
                <form className="gc-panel gc-launch-panel" onSubmit={launchAnalysis}>
                  <div className="gc-panel-heading">
                    <div>
                      <h2>Launch analysis</h2>
                      <p>Runs against the parsed text and selected type.</p>
                    </div>
                  </div>

                  <div className="gc-field-stack">
                    <label>
                      <span>Provider</span>
                      <select value={provider} onChange={(event) => changeProvider(event.target.value as Provider)}>
                        <option value="openai_compatible">OpenAI compatible</option>
                        <option value="anthropic_compatible">Anthropic compatible</option>
                        <option value="hermes">Hermes</option>
                      </select>
                    </label>

                    <label>
                      <span>Model</span>
                      <input value={model} onChange={(event) => changeModel(event.target.value)} />
                    </label>
                  </div>

                  <div className="gc-provider-note">
                    <strong>{providerLabels[provider]}</strong>
                    {providerDefaultModel ? (
                      <span>
                        Saved default: {providerDefaultModel}
                        {model === providerDefaultModel && !modelEdited ? " (applied)" : " (overridden)"}
                      </span>
                    ) : selectedProviderKey?.has_key ? (
                      <span>No saved default model returned for this provider.</span>
                    ) : (
                      <span>No saved provider key loaded for this provider.</span>
                    )}
                  </div>

                  <details className="gc-advanced">
                    <summary>Advanced options</summary>
                    <div className="gc-advanced-grid">
                      <label>
                        <span>Temperature</span>
                        <input disabled value="Backend default" readOnly />
                      </label>
                      <label>
                        <span>Output budget</span>
                        <input disabled value="Backend default" readOnly />
                      </label>
                    </div>
                  </details>

                  <button className="gc-primary gc-submit" disabled={pending || document.parse_status !== "completed" || !model} type="submit">
                    {pending ? "Starting..." : "Start analysis"}
                  </button>
                </form>

                <section className="gc-panel gc-history-panel">
                  <div className="gc-panel-heading">
                    <div>
                      <h2>Analysis history</h2>
                      <p>{analyses.length ? `${analyses.length} run${analyses.length === 1 ? "" : "s"}` : "No runs yet."}</p>
                    </div>
                  </div>

                  {latestAnalysis ? (
                    <div className="gc-latest-run">
                      <span>Latest</span>
                      <strong>{formatLabel(latestAnalysis.verdict) || "No verdict"}</strong>
                      <small>
                        {formatLabel(latestAnalysis.status)} · {latestAnalysis.provider} · {latestAnalysis.model}
                      </small>
                    </div>
                  ) : null}

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
                                {analysis.error_message ? <div className="gc-error-text">{analysis.error_message}</div> : null}
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
  width: min(1440px, 100%);
  min-height: calc(100vh - 69px);
  margin: 0 auto;
  padding: 32px 24px 48px;
  color: #eef2ff;
}

.gc-hero,
.gc-hero-actions,
.gc-stepper,
.gc-action-row,
.gc-text-tools,
.gc-detail-grid,
.gc-meta-grid,
.gc-advanced-grid {
  display: flex;
}

.gc-hero {
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
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
.gc-meta-grid span,
.gc-meta-grid small,
.gc-provider-note span,
.gc-latest-run small,
.gc-table small,
.gc-note,
.gc-section-list span,
.gc-search-count {
  color: #94a3b8;
}

.gc-muted {
  margin: 8px 0 0;
}

.gc-hero-actions,
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
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.gc-step {
  display: flex;
  min-height: 86px;
  align-items: center;
  gap: 12px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: #0d1424;
  padding: 14px;
}

.gc-step span {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  color: #cbd5e1;
  font-size: 13px;
  font-weight: 900;
}

.gc-step div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.gc-step strong {
  color: #f8fafc;
}

.gc-step small {
  overflow: hidden;
  color: #94a3b8;
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
  grid-template-columns: minmax(0, 1fr) minmax(360px, 470px);
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

.gc-panel-heading {
  display: flex;
  align-items: center;
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

.gc-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.gc-meta-grid div {
  display: grid;
  gap: 6px;
  min-height: 92px;
  align-content: start;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.58);
  padding: 12px;
}

.gc-meta-grid span,
.gc-field-stack span,
.gc-advanced-grid span {
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-meta-grid strong {
  color: #f8fafc;
  line-height: 1.3;
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

.gc-text-tools {
  align-items: end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.gc-text-tools label,
.gc-field-stack label,
.gc-advanced-grid label {
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-text-tools label {
  width: min(420px, 100%);
}

.gc-search-count {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.58);
  padding: 0 12px;
  font-size: 13px;
}

.gc-section-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.gc-section-list span {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.58);
  padding: 6px 10px;
  font-size: 12px;
  line-height: 1.3;
}

.gc-text-preview {
  max-height: 620px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: #070a12;
  color: #dbeafe;
  padding: 14px;
  font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
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

.gc-advanced {
  margin-top: 14px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.5);
  padding: 12px;
}

.gc-advanced summary {
  color: #dbeafe;
  cursor: pointer;
  font-weight: 800;
}

.gc-advanced-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.gc-submit {
  width: 100%;
  margin-top: 16px;
}

.gc-latest-run {
  display: grid;
  gap: 5px;
  margin-bottom: 12px;
  border: 1px solid rgba(34, 211, 238, 0.22);
  border-radius: 8px;
  background: rgba(8, 145, 178, 0.16);
  padding: 12px;
}

.gc-latest-run span {
  color: #7dd3fc;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-latest-run strong {
  color: #f8fafc;
}

.gc-table-scroll {
  width: 100%;
  overflow-x: auto;
}

.gc-table {
  min-width: 820px;
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
  max-width: 220px;
  overflow: hidden;
  color: #bae6fd;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-error-text {
  max-width: 240px;
  margin-top: 8px;
  color: #fca5a5;
  font-size: 12px;
  line-height: 1.4;
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

@media (max-width: 1100px) {
  .gc-detail-grid,
  .gc-stepper {
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

  .gc-meta-grid,
  .gc-advanced-grid {
    grid-template-columns: 1fr;
  }

  .gc-text-tools {
    align-items: stretch;
    flex-direction: column;
  }
}
`;
