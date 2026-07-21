"use client";

import Link from "next/link";
import { DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  getProviderDefaultModel,
  listProviderModels,
  type ProviderModelOptions,
} from "@/lib/api/provider-settings";
import {
  USER_SELECTABLE_DOCUMENT_TYPES,
  createAnalysis,
  deleteDocument,
  getDocument,
  listDocuments,
  listAnalyses,
  uploadDocument,
  type AnalysisRecord,
  type DocumentRecord,
  type DocumentType,
  type OutputLanguage,
  type ParseStatus,
  type Provider,
} from "@/lib/api/documents";
import { formatDate } from "@/lib/format";
import { appPath } from "@/lib/routing";
import { formatDocumentTypeLabel, getDocumentParsePresentation } from "./documentsDisplay";

type ParseFilter = "all" | ParseStatus;

const supportedExtensions = [".docx", ".pdf", ".md", ".txt"];
type UploadSlot = "primary" | "finSummary";
type UploadStep = "uploading" | "parsing" | "starting_analysis";

const parsePollIntervalMs = 3000;
const parsePollTimeoutMs = 5 * 60 * 1000;
const defaultOutputLanguage: OutputLanguage = "en";

const parseFilters: { label: string; value: ParseFilter }[] = [
  { label: "All", value: "all" },
  { label: "Ready", value: "completed" },
  { label: "Parsing", value: "running" },
  { label: "Queued", value: "queued" },
  { label: "Failed", value: "failed" },
];

function getEffectiveType(document: DocumentRecord): string {
  return formatDocumentTypeLabel(document.manual_document_type ?? document.detected_document_type);
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function isWorkbookFile(filename: string): boolean {
  return filename.trim().toLowerCase().endsWith(".xlsx");
}

function getFinSummaryPresentation(document: DocumentRecord["linked_fin_summary_document"]): {
  label: string;
  tone: "good" | "info" | "warn" | "bad";
} | null {
  if (!document) {
    return null;
  }
  if (isWorkbookFile(document.original_filename)) {
    return { label: "Workbook attached", tone: "good" };
  }
  if (document.parse_status === "failed") {
    return { label: "Attachment parser failed", tone: "warn" };
  }
  return getDocumentParsePresentation(document.parse_status);
}

function isFullAnalysisComplete(analysis: AnalysisRecord): boolean {
  return (
    analysis.status === "completed" &&
    analysis.predicted_comment_run?.status === "completed" &&
    analysis.ic_review_run?.status === "completed"
  );
}

function isFullAnalysisFailed(analysis: AnalysisRecord): boolean {
  return (
    analysis.status === "failed" ||
    analysis.status === "cancelled" ||
    analysis.predicted_comment_run?.status === "failed" ||
    analysis.predicted_comment_run?.status === "cancelled" ||
    analysis.ic_review_run?.status === "failed" ||
    analysis.ic_review_run?.status === "cancelled"
  );
}

function getLatestCaseAnalysis(analyses: AnalysisRecord[]): AnalysisRecord | null {
  return (
    analyses
      .sort(
        (left, right) =>
          new Date(right.completed_at ?? right.created_at).getTime() -
          new Date(left.completed_at ?? left.created_at).getTime(),
      )[0] ?? null
  );
}

function getAnalysisStatusSignal(analysis: AnalysisRecord): { label: string; tone: "good" | "info" | "warn" | "bad" } {
  if (isFullAnalysisComplete(analysis)) {
    return { label: "Analysis complete", tone: "good" };
  }
  if (isFullAnalysisFailed(analysis)) {
    return { label: "Analysis failed", tone: "bad" };
  }
  if (analysis.status === "queued") {
    return { label: "Gate Challenger queued", tone: "warn" };
  }
  if (analysis.status === "running") {
    return { label: "Gate Challenger running", tone: "info" };
  }

  const predictedStatus = analysis.predicted_comment_run?.status;
  if (!predictedStatus) {
    return { label: "Devils Advocate queued", tone: "warn" };
  }
  if (predictedStatus !== "completed") {
    return { label: `Devils Advocate ${predictedStatus}`, tone: predictedStatus === "queued" ? "warn" : "info" };
  }

  const icStatus = analysis.ic_review_run?.status;
  if (!icStatus) {
    return { label: "IC Review queued", tone: "warn" };
  }
  if (icStatus !== "completed") {
    return { label: `IC Review ${icStatus}`, tone: icStatus === "queued" ? "warn" : "info" };
  }

  return { label: "Analysis running", tone: "info" };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function chooseAnalysisConfig(providerModels: ProviderModelOptions[]): { provider: Provider; model: string } | null {
  const configuredModels = providerModels.filter((item) => item.has_key);
  const preferred =
    configuredModels.find((item) => item.provider === "openai_compatible") ??
    configuredModels[0] ??
    null;

  if (!preferred) {
    return null;
  }

  const model = getProviderDefaultModel(providerModels, preferred.provider) || preferred.available_models[0] || "";
  if (!model) {
    return null;
  }

  return {
    provider: preferred.provider,
    model,
  };
}

function getUploadButtonLabel(step: UploadStep | null): string {
  if (step === "uploading") {
    return "Uploading...";
  }
  if (step === "parsing") {
    return "Parsing...";
  }
  if (step === "starting_analysis") {
    return "Starting analysis...";
  }
  return "Start Analysis";
}

function getUploadProgressCopy(step: UploadStep | null): { title: string; note: string } {
  if (step === "parsing") {
    return {
      title: "Parsing document",
      note: "Full analysis starts automatically as soon as the parser finishes.",
    };
  }
  if (step === "starting_analysis") {
    return {
      title: "Starting analysis",
      note: "Gate Challenger, Devils Advocate, and IC Review are being queued.",
    };
  }
  return {
    title: "Uploading",
    note: "Files are being stored before parsing starts.",
  };
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState("");
  const [query, setQuery] = useState("");
  const [parseFilter, setParseFilter] = useState<ParseFilter>("all");
  const [title, setTitle] = useState("");
  const [manualType, setManualType] = useState<DocumentType | "">("");
  const [primaryFile, setPrimaryFile] = useState<File | null>(null);
  const [finSummaryFile, setFinSummaryFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [pendingUpload, setPendingUpload] = useState(false);
  const [uploadStep, setUploadStep] = useState<UploadStep | null>(null);
  const [draggingUpload, setDraggingUpload] = useState<UploadSlot | null>(null);
  const [providerModels, setProviderModels] = useState<ProviderModelOptions[]>([]);
  const [caseAnalysesByDocumentId, setCaseAnalysesByDocumentId] = useState<Record<string, AnalysisRecord>>({});
  const primaryFileInputRef = useRef<HTMLInputElement | null>(null);
  const finSummaryFileInputRef = useRef<HTMLInputElement | null>(null);

  async function refresh() {
    const response = await listDocuments();
    setDocuments(response.documents);
    await refreshCaseAnalyses(response.documents);
  }

  async function refreshCaseAnalyses(nextDocuments: DocumentRecord[]) {
    const entries = await Promise.all(
      nextDocuments.map(async (document) => {
        try {
          const response = await listAnalyses(document.id);
          const latestAnalysis = getLatestCaseAnalysis(response.analyses);
          return latestAnalysis ? ([document.id, latestAnalysis] as const) : null;
        } catch {
          return null;
        }
      }),
    );

    setCaseAnalysesByDocumentId(Object.fromEntries(entries.filter((entry) => entry !== null)));
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load documents"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (documents.length === 0) {
      return;
    }
    const timer = window.setInterval(() => {
      refreshCaseAnalyses(documents).catch(() => undefined);
    }, 10000);
    return () => window.clearInterval(timer);
  }, [documents]);

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

  async function handleDelete(document: DocumentRecord) {
    if (!window.confirm(`Delete document "${document.title}"?`)) {
      return;
    }
    setDeletingId(document.id);
    setError("");
    try {
      await deleteDocument(document.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete document");
    } finally {
      setDeletingId("");
    }
  }

  const inferredTitle = useMemo(() => {
    if (!primaryFile) {
      return "";
    }
    return primaryFile.name.replace(/\.[^.]+$/, "");
  }, [primaryFile]);

  function chooseFile(slot: UploadSlot, nextFile: File | null) {
    setUploadError("");
    if (slot === "primary") {
      setPrimaryFile(nextFile);
      return;
    }
    setFinSummaryFile(nextFile);
  }

  function handleUploadDragOver(slot: UploadSlot, event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDraggingUpload(slot);
  }

  function handleUploadDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDraggingUpload(null);
  }

  function handleUploadDrop(slot: UploadSlot, event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDraggingUpload(null);
    chooseFile(slot, event.dataTransfer.files[0] ?? null);
  }

  async function waitForUploadedDocumentParse(documentId: string): Promise<DocumentRecord> {
    const startedAt = Date.now();

    while (Date.now() - startedAt < parsePollTimeoutMs) {
      const nextDocument = await getDocument(documentId);
      setDocuments((items) => {
        const existingIndex = items.findIndex((item) => item.id === nextDocument.id);
        if (existingIndex === -1) {
          return [nextDocument, ...items];
        }
        return items.map((item) => (item.id === nextDocument.id ? nextDocument : item));
      });

      if (nextDocument.parse_status === "completed") {
        return nextDocument;
      }
      if (nextDocument.parse_status === "failed") {
        throw new Error(nextDocument.parse_error || "Parser failed");
      }

      await sleep(parsePollIntervalMs);
    }

    throw new Error("Parsing did not finish within 5 minutes. Open the document to check parser status.");
  }

  async function getAnalysisConfig(): Promise<{ provider: Provider; model: string }> {
    const models = providerModels.length > 0 ? providerModels : (await listProviderModels()).provider_models;
    setProviderModels(models);
    const config = chooseAnalysisConfig(models);
    if (!config) {
      throw new Error("Configure a provider key and default model before starting analysis.");
    }
    return config;
  }

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!primaryFile) {
      setUploadError("Choose a defense document file");
      return;
    }
    setPendingUpload(true);
    setUploadStep("uploading");
    setUploadError("");

    const form = new FormData();
    form.set("file", primaryFile);
    if (finSummaryFile) {
      form.set("fin_summary_file", finSummaryFile);
    }
    if (title.trim()) {
      form.set("title", title.trim());
    }
    if (manualType) {
      form.set("manual_document_type", manualType);
    }

    try {
      const document = await uploadDocument(form);
      setDocuments((items) => [document, ...items.filter((item) => item.id !== document.id)]);
      setUploadStep("parsing");
      const parsedDocument = await waitForUploadedDocumentParse(document.id);
      setUploadStep("starting_analysis");
      const analysisConfig = await getAnalysisConfig();
      await createAnalysis(parsedDocument.id, {
        provider: analysisConfig.provider,
        model: analysisConfig.model,
        document_type_override: parsedDocument.manual_document_type ?? parsedDocument.detected_document_type,
        run_parameters: {
          output_language: defaultOutputLanguage,
        },
      });
      window.location.href = appPath(`/documents/${document.id}`);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Start analysis failed");
    } finally {
      setPendingUpload(false);
      setUploadStep(null);
    }
  }

  const caseDocuments = useMemo(
    () => documents.filter((document) => caseAnalysesByDocumentId[document.id]),
    [caseAnalysesByDocumentId, documents],
  );

  const filteredCases = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return caseDocuments.filter((document) => {
      const matchesFilter = parseFilter === "all" || document.parse_status === parseFilter;
      const matchesQuery =
        !normalizedQuery ||
        [
          document.title,
          document.original_filename,
          document.linked_fin_summary_document?.title ?? "",
          document.linked_fin_summary_document?.original_filename ?? "",
          getEffectiveType(document),
          document.parse_error ?? "",
        ]
          .join(" ")
          .toLowerCase()
          .includes(normalizedQuery);

      return matchesFilter && matchesQuery;
    });
  }, [caseDocuments, parseFilter, query]);

  const shownStart = filteredCases.length > 0 ? 1 : 0;
  const shownEnd = filteredCases.length;

  return (
    <AppShell>
      <main className="documents-review">
        <style>{documentsStyles}</style>
        <section className="gc-hero">
          <div>
            <h1>Documents</h1>
            <p className="gc-muted">Upload investment review and product defense documents.</p>
          </div>
        </section>

        {error ? <section className="gc-alert">{error}</section> : null}

        <section className="gc-upload-card" aria-label="Upload document">
          <form className="gc-upload-form" onSubmit={submitUpload}>
            <div className="gc-upload-zones" aria-label="Upload files">
              <div
                className={`gc-dropzone${draggingUpload === "primary" ? " is-dragging" : ""}${
                  primaryFile ? " has-file" : ""
                }`}
                role="button"
                tabIndex={0}
                onClick={() => primaryFileInputRef.current?.click()}
                onDragLeave={handleUploadDragLeave}
                onDragOver={(event) => handleUploadDragOver("primary", event)}
                onDrop={(event) => handleUploadDrop("primary", event)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    primaryFileInputRef.current?.click();
                  }
                }}
              >
                <input
                  aria-label="Документ для защиты"
                  ref={primaryFileInputRef}
                  type="file"
                  onChange={(event) => chooseFile("primary", event.target.files?.[0] ?? null)}
                />
                <div className="gc-upload-mark" aria-hidden="true">
                  <span />
                </div>
                <div className="gc-drop-copy">
                  <strong>Документ для защиты</strong>
                  <p>{primaryFile ? "File selected" : "Drag and drop or click to browse"}</p>
                </div>
                <div className="gc-format-row" aria-label="Accepted formats">
                  <span>Any file format</span>
                  <span>Parser optimized for {supportedExtensions.join(", ")}; max 25 MB</span>
                </div>
              </div>

              <div
                className={`gc-dropzone${draggingUpload === "finSummary" ? " is-dragging" : ""}${
                  finSummaryFile ? " has-file" : ""
                }`}
                role="button"
                tabIndex={0}
                onClick={() => finSummaryFileInputRef.current?.click()}
                onDragLeave={handleUploadDragLeave}
                onDragOver={(event) => handleUploadDragOver("finSummary", event)}
                onDrop={(event) => handleUploadDrop("finSummary", event)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    finSummaryFileInputRef.current?.click();
                  }
                }}
              >
                <input
                  aria-label="Fin Summary"
                  ref={finSummaryFileInputRef}
                  type="file"
                  onChange={(event) => chooseFile("finSummary", event.target.files?.[0] ?? null)}
                />
                <div className="gc-upload-mark" aria-hidden="true">
                  <span />
                </div>
                <div className="gc-drop-copy">
                  <strong>Fin Summary</strong>
                  <p>{finSummaryFile ? "File selected" : "Drag and drop or click to browse"}</p>
                </div>
                <div className="gc-format-row" aria-label="Accepted formats">
                  <span>Any file format</span>
                  <span>Optional attachment; max 25 MB</span>
                </div>
              </div>
            </div>

            <div className="gc-upload-details">
              {primaryFile ? (
                <div className="gc-selected-file">
                  <div>
                    <small>Документ для защиты</small>
                    <strong>{primaryFile.name}</strong>
                    <span>{formatBytes(primaryFile.size)}</span>
                  </div>
                  <button
                    className="gc-compact-danger"
                    disabled={pendingUpload}
                    type="button"
                    onClick={() => {
                      setPrimaryFile(null);
                      if (primaryFileInputRef.current) {
                        primaryFileInputRef.current.value = "";
                      }
                    }}
                  >
                    Remove
                  </button>
                </div>
              ) : null}

              {finSummaryFile ? (
                <div className="gc-selected-file">
                  <div>
                    <small>Fin Summary</small>
                    <strong>{finSummaryFile.name}</strong>
                    <span>{formatBytes(finSummaryFile.size)}</span>
                  </div>
                  <button
                    className="gc-compact-danger"
                    disabled={pendingUpload}
                    type="button"
                    onClick={() => {
                      setFinSummaryFile(null);
                      if (finSummaryFileInputRef.current) {
                        finSummaryFileInputRef.current.value = "";
                      }
                    }}
                  >
                    Remove
                  </button>
                </div>
              ) : null}

              <div className="gc-field-stack">
                <label className="gc-title-field">
                  <span>Title</span>
                  <input
                    placeholder={inferredTitle || "Optional display title"}
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </label>

                <div className="gc-upload-row">
                  <label>
                    <span>Document type</span>
                    <span className="gc-select-control">
                      <select
                        aria-label="Manual type"
                        className={manualType ? "" : "is-placeholder"}
                        value={manualType}
                        onChange={(event) => setManualType(event.target.value as DocumentType | "")}
                      >
                        <option value="">Select document type</option>
                        {USER_SELECTABLE_DOCUMENT_TYPES.map((item) => (
                          <option key={item} value={item}>
                            {formatDocumentTypeLabel(item)}
                          </option>
                        ))}
                      </select>
                    </span>
                  </label>

                  <button className="gc-primary gc-submit" disabled={pendingUpload || !primaryFile} type="submit">
                    {getUploadButtonLabel(uploadStep)}
                  </button>
                </div>
              </div>

              {uploadError ? <div className="gc-alert inline">{uploadError}</div> : null}

              {pendingUpload ? (
                <div className="gc-upload-progress" aria-live="polite">
                  <span />
                  <div>
                    <strong>{getUploadProgressCopy(uploadStep).title}</strong>
                    <small>{getUploadProgressCopy(uploadStep).note}</small>
                  </div>
                </div>
              ) : null}

            </div>
          </form>
        </section>

        <section className="gc-controls" aria-label="Document filters">
          <label className="gc-search-label">
            <span className="gc-sr-only">Search</span>
            <input
              aria-label="Search documents"
              placeholder="Search documents"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <div className="gc-filter-tabs" role="tablist" aria-label="Filter by parse status">
            {parseFilters.map((filter) => (
              <button
                aria-selected={parseFilter === filter.value}
                className={parseFilter === filter.value ? "is-active" : ""}
                key={filter.value}
                type="button"
                onClick={() => setParseFilter(filter.value)}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </section>

        <section className="gc-panel gc-table-panel">
          {loading ? <div className="gc-empty">Loading documents...</div> : null}
          {!loading && documents.length === 0 ? (
            <div className="gc-empty">
              <strong>No documents yet.</strong>
              <span>Use the upload panel above to add the first document.</span>
            </div>
          ) : null}
          {!loading && documents.length > 0 && caseDocuments.length === 0 ? (
            <div className="gc-empty">Cases appear here after analysis starts.</div>
          ) : null}
          {!loading && caseDocuments.length > 0 && filteredCases.length === 0 ? (
            <div className="gc-empty">No cases match the current filters.</div>
          ) : null}

          {filteredCases.length > 0 ? (
            <div className="gc-table-scroll">
              <table className="gc-table">
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Type</th>
                    <th>Parse</th>
                    <th>Analysis</th>
                    <th>Uploaded</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCases.map((document) => {
                    const parseState = getDocumentParsePresentation(document.parse_status);
                    const finSummary = document.linked_fin_summary_document;
                    const finSummaryParseState = getFinSummaryPresentation(finSummary);
                    const caseAnalysis = caseAnalysesByDocumentId[document.id];
                    const analysisSignal = getAnalysisStatusSignal(caseAnalysis);
                    const canOpenAnalysis = isFullAnalysisComplete(caseAnalysis);

                    return (
                      <tr key={document.id}>
                        <td>
                          <div className="gc-document-cell">
                            <div className="gc-title-cell">
                              <strong>{document.title}</strong>
                              <span>{document.original_filename}</span>
                              <small>{formatBytes(document.file_size_bytes)}</small>
                              {finSummary ? (
                                <div className="gc-linked-document">
                                  <span>Fin Summary</span>
                                  <strong>{finSummary.original_filename}</strong>
                                  {finSummaryParseState ? (
                                    <small className={`gc-linked-parse is-${finSummaryParseState.tone}`}>
                                      {finSummaryParseState.label}
                                    </small>
                                  ) : null}
                                </div>
                              ) : null}
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className="gc-type-text">{getEffectiveType(document)}</span>
                          {document.manual_document_type ? <div className="gc-subtle">manual override</div> : null}
                        </td>
                        <td>
                          <span className={`gc-parse-state is-${parseState.tone}`}>
                            <span aria-hidden="true" />
                            {parseState.label}
                          </span>
                          {document.parse_error ? <div className="gc-error-text">{document.parse_error}</div> : null}
                        </td>
                        <td>
                          <span className={`gc-signal is-${analysisSignal.tone}`}>{analysisSignal.label}</span>
                        </td>
                        <td>
                          <span className="gc-date">{formatDate(document.created_at)}</span>
                        </td>
                        <td>
                          <div className="gc-action-row">
                            {canOpenAnalysis ? (
                              <Link className="gc-compact-link" href={`/analyses/${caseAnalysis.id}`}>
                                Analysis results
                              </Link>
                            ) : (
                              <button className="gc-compact-link is-disabled" disabled type="button">
                                Analysis results
                              </button>
                            )}
                            <Link className="gc-compact-link" href={`/documents/${document.id}`} target="_blank" rel="noreferrer">
                              Open Case
                            </Link>
                            <button
                              className="gc-compact-danger"
                              disabled={deletingId === document.id}
                              type="button"
                              onClick={() => handleDelete(document)}
                            >
                              {deletingId === document.id ? "Deleting" : "Delete"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="gc-table-footer">
                <span>
                  Showing {shownStart} to {shownEnd} of {caseDocuments.length} cases
                </span>
              </div>
            </div>
          ) : null}
        </section>
      </main>
    </AppShell>
  );
}

const documentsStyles = `
.documents-review {
  width: min(1536px, 100%);
  min-height: calc(100vh - var(--app-header-height));
  margin: 0 auto;
  padding: 32px 36px 48px;
  color: #111827;
}

.gc-hero {
  display: flex;
  align-items: flex-start;
  margin-bottom: 22px;
}

.gc-hero h1 {
  margin: 0;
  color: #111827;
  font-size: 30px;
  font-weight: 800;
  line-height: 38px;
  letter-spacing: 0;
}

.gc-muted {
  margin: 8px 0 0;
  color: #5b6472;
  font-size: 14px;
  line-height: 22px;
}

.gc-upload-card,
.gc-panel {
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: none;
}

.gc-upload-card {
  margin-bottom: 22px;
  padding: 18px;
}

.gc-upload-form {
  display: grid;
  grid-template-columns: minmax(380px, 1fr) minmax(320px, 0.9fr);
  gap: 36px;
  align-items: center;
}

.gc-upload-zones {
  display: grid;
  min-width: 0;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.gc-dropzone {
  display: flex;
  min-height: 176px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 9px;
  border: 1px dashed #cad2dc;
  border-radius: 8px;
  background: #fbfcfd;
  color: #111827;
  cursor: pointer;
  padding: 18px;
  text-align: center;
  transition:
    background 160ms ease,
    border-color 160ms ease,
    transform 160ms ease;
}

.gc-dropzone:hover,
.gc-dropzone.is-dragging {
  border-color: #0e9f6e;
  background: #f8fffc;
}

.gc-dropzone.is-dragging {
  transform: translateY(-1px);
}

.gc-dropzone.has-file {
  border-style: solid;
  border-color: #0e9f6e;
}

.gc-dropzone input {
  display: none;
}

.gc-upload-mark {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border: 1px solid #d8dee7;
  border-radius: 12px;
  background: #ffffff;
}

.gc-upload-mark span {
  position: relative;
  width: 22px;
  height: 28px;
  border: 2px solid #111827;
  border-radius: 5px;
}

.gc-upload-mark span::before,
.gc-upload-mark span::after {
  position: absolute;
  left: 6px;
  height: 2px;
  background: #111827;
  content: "";
}

.gc-upload-mark span::before {
  top: 8px;
  width: 9px;
}

.gc-upload-mark span::after {
  top: 15px;
  width: 13px;
}

.gc-drop-copy {
  display: grid;
  gap: 5px;
}

.gc-drop-copy strong {
  color: #111827;
  font-size: 16px;
  font-weight: 800;
  line-height: 22px;
}

.gc-drop-copy p,
.gc-format-row,
.gc-selected-file span,
.gc-upload-progress small,
.gc-subtle,
.gc-date,
.gc-title-cell span,
.gc-title-cell small {
  color: #5b6472;
}

.gc-drop-copy p {
  margin: 0;
  font-size: 14px;
  line-height: 20px;
}

.gc-format-row {
  display: grid;
  gap: 2px;
  font-size: 12px;
  line-height: 18px;
}

.gc-upload-details {
  display: flex;
  min-width: 0;
  min-height: 150px;
  flex-direction: column;
  justify-content: center;
  gap: 14px;
}

.gc-selected-file {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #f7f9fb;
  padding: 10px 12px;
}

.gc-selected-file div,
.gc-field-stack {
  display: grid;
  min-width: 0;
  gap: 8px;
}

.gc-selected-file strong {
  overflow: hidden;
  color: #111827;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-selected-file small {
  color: #5b6472;
  font-size: 11px;
  font-weight: 800;
  line-height: 16px;
  text-transform: uppercase;
}

.gc-field-stack {
  gap: 18px;
}

.gc-field-stack label {
  color: #111827;
  font-size: 13px;
  font-weight: 700;
  line-height: 18px;
}

.gc-upload-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 184px;
  align-items: end;
  gap: 24px;
}

.documents-review input,
.documents-review select {
  min-height: 44px;
  border-color: #d9e0ea;
  background: #ffffff;
  color: #111827;
  font-size: 13px;
}

.documents-review input::placeholder {
  color: #8a93a3;
}

.gc-select-control {
  position: relative;
  display: block;
}

.gc-select-control::after {
  position: absolute;
  top: 50%;
  right: 14px;
  width: 7px;
  height: 7px;
  border-right: 1.5px solid #111827;
  border-bottom: 1.5px solid #111827;
  content: "";
  pointer-events: none;
  transform: translateY(-65%) rotate(45deg);
}

.gc-select-control select {
  appearance: none;
  padding-right: 40px;
}

.gc-select-control select.is-placeholder {
  color: #8a93a3;
  font-weight: 500;
}

.gc-primary,
.gc-compact-link,
.gc-compact-danger,
.gc-filter-tabs button {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 750;
  letter-spacing: 0;
  white-space: nowrap;
}

.gc-primary {
  border: 1px solid #0e9f6e;
  background: #0e9f6e;
  color: #ffffff;
  padding: 0 16px;
}

.gc-primary:hover:not(:disabled) {
  border-color: #087d5f;
  background: #087d5f;
  color: #ffffff;
}

.gc-primary:disabled {
  opacity: 0.48;
}

.gc-submit {
  width: 100%;
}

.gc-upload-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid #bfe5d6;
  border-radius: 8px;
  background: #eaf8f2;
  padding: 12px;
}

.gc-upload-progress span {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(14, 159, 110, 0.24);
  border-top-color: #0e9f6e;
  border-radius: 999px;
  animation: gc-spin 900ms linear infinite;
}

.gc-upload-progress div {
  display: grid;
  gap: 2px;
}

.gc-upload-progress strong {
  color: #075e45;
}

.gc-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 22px;
}

.gc-search-label {
  position: relative;
  flex: 1 1 auto;
  max-width: none;
}

.gc-search-label input {
  padding-left: 14px;
}

.gc-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.gc-filter-tabs {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  border: 1px solid #d9e0ea;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

.gc-filter-tabs button {
  min-width: 84px;
  border: 0;
  border-left: 1px solid #d9e0ea;
  border-radius: 0;
  background: #ffffff;
  color: #111827;
  padding: 0 18px;
}

.gc-filter-tabs button:first-child {
  min-width: 64px;
  border-left: 0;
}

.gc-filter-tabs button:hover {
  background: #fbfcfd;
  color: #075e45;
}

.gc-filter-tabs button.is-active,
.gc-filter-tabs button[aria-selected="true"] {
  box-shadow: inset 0 0 0 1px #0e9f6e;
  color: #075e45;
}

.gc-table-panel {
  min-width: 0;
  overflow: hidden;
  padding: 0;
}

.gc-table-scroll {
  width: 100%;
  overflow-x: auto;
}

.gc-table {
  min-width: 1060px;
  background: #ffffff;
}

.gc-table thead {
  background: #fbfcfd;
}

.gc-table th,
.gc-table td {
  border-bottom: 1px solid #edf1f5;
  padding: 13px 18px;
}

.gc-table th {
  color: #111827;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.gc-table td {
  color: #111827;
  font-size: 13px;
  line-height: 18px;
  vertical-align: middle;
}

.gc-table th:nth-child(1),
.gc-table td:nth-child(1) {
  width: 30%;
}

.gc-table th:nth-child(2),
.gc-table td:nth-child(2),
.gc-table th:nth-child(3),
.gc-table td:nth-child(3),
.gc-table th:nth-child(5),
.gc-table td:nth-child(5) {
  width: 14%;
}

.gc-table th:nth-child(4),
.gc-table td:nth-child(4) {
  width: 15%;
}

.gc-table th:nth-child(6),
.gc-table td:nth-child(6) {
  width: 13%;
}

.gc-table tbody tr:hover td {
  background: #fbfcfd;
}

.gc-document-cell,
.gc-action-row {
  display: flex;
  align-items: center;
}

.gc-document-cell {
  gap: 12px;
  min-width: 0;
}

.gc-title-cell {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.gc-title-cell strong {
  overflow-wrap: anywhere;
  color: #111827;
  font-size: 13px;
  font-weight: 750;
}

.gc-title-cell span,
.gc-title-cell small,
.gc-subtle {
  font-size: 12px;
  line-height: 18px;
}

.gc-type-text {
  color: #111827;
}

.gc-linked-document {
  display: flex;
  width: fit-content;
  max-width: 100%;
  align-items: center;
  gap: 6px;
  margin-top: 7px;
  border: 1px solid #e5eaf0;
  border-radius: 6px;
  background: #f7f9fb;
  padding: 5px 7px;
}

.gc-linked-document > span {
  color: #5b6472;
  font-size: 11px;
  font-weight: 800;
  line-height: 16px;
  text-transform: uppercase;
}

.gc-linked-document > strong {
  overflow: hidden;
  max-width: 220px;
  color: #111827;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-linked-parse {
  border-radius: 4px;
  background: #eef2f6;
  color: #344054;
  padding: 1px 6px;
  font-weight: 800;
  white-space: nowrap;
}

.gc-linked-parse.is-good {
  background: #eaf8f1;
  color: #075e45;
}

.gc-linked-parse.is-info {
  background: #eaf3fb;
  color: #1d70b8;
}

.gc-linked-parse.is-warn {
  background: #fff7df;
  color: #8a5d00;
}

.gc-linked-parse.is-bad {
  background: #fcecee;
  color: #c92036;
}

.gc-parse-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #344054;
}

.gc-parse-state > span {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border: 1px solid currentColor;
  border-radius: 999px;
  background: transparent;
}

.gc-parse-state.is-good {
  color: #087d5f;
}

.gc-parse-state.is-good > span {
  border-color: transparent;
  background: currentColor;
}

.gc-parse-state.is-info {
  color: #1d70b8;
}

.gc-parse-state.is-warn {
  color: #8a5d00;
}

.gc-parse-state.is-bad {
  color: #c92036;
}

.gc-parse-state.is-bad > span {
  border-radius: 2px;
  background: currentColor;
}

.gc-signal {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  border-radius: 6px;
  background: #f2f4f7;
  color: #344054;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 750;
  line-height: 18px;
  white-space: nowrap;
}

.gc-signal.is-good {
  background: #eaf8f1;
  color: #075e45;
}

.gc-signal.is-info {
  background: #eaf3fb;
  color: #1d70b8;
}

.gc-signal.is-warn {
  background: #fff7df;
  color: #8a5d00;
}

.gc-signal.is-bad {
  background: #fcecee;
  color: #c92036;
}

.gc-error-text {
  max-width: 260px;
  margin-top: 7px;
  color: #c92036;
  font-size: 12px;
  line-height: 18px;
}

.gc-action-row {
  justify-content: center;
  gap: 10px;
}

.gc-compact-link,
.gc-compact-danger {
  min-height: 44px;
  border: 1px solid #d9e0ea;
  background: #ffffff;
  color: #111827;
  padding: 0 18px;
}

.gc-compact-link:hover {
  border-color: #0e9f6e;
  color: #075e45;
}

.gc-compact-link:disabled,
.gc-compact-link.is-disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.gc-compact-danger {
  border-color: #f2d7d9;
  color: #c92036;
}

.gc-compact-danger:hover:not(:disabled) {
  border-color: #e7a8b4;
  background: #fcecee;
  color: #a5122a;
}

.gc-table-footer {
  display: flex;
  min-height: 56px;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid #edf1f5;
  color: #5b6472;
  padding: 0 18px;
  font-size: 12px;
  line-height: 18px;
}

.gc-empty {
  display: grid;
  min-height: 180px;
  place-items: center;
  gap: 10px;
  background: #fbfcfd;
  color: #5b6472;
  padding: 24px;
  text-align: center;
}

.gc-empty strong {
  color: #111827;
}

.gc-alert {
  margin-bottom: 16px;
  border: 1px solid #f2d7d9;
  border-radius: 8px;
  background: #fcecee;
  color: #a5122a;
  padding: 14px 16px;
}

.gc-alert.inline {
  margin: 0;
}

@keyframes gc-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .gc-upload-progress span {
    animation: none;
  }

  .gc-dropzone {
    transition: none;
  }
}

@media (max-width: 1100px) {
  .gc-table-scroll {
    overflow-x: visible;
  }

  .gc-table {
    display: block;
    min-width: 0;
    width: 100%;
    background: transparent;
  }

  .gc-table thead {
    display: none;
  }

  .gc-table tbody {
    display: grid;
    gap: 10px;
    padding: 10px;
  }

  .gc-table tr {
    display: grid;
    border: 1px solid #e5eaf0;
    border-radius: 8px;
    background: #ffffff;
    overflow: hidden;
  }

  .gc-table th,
  .gc-table td {
    border-bottom: 1px solid #edf1f5;
    padding: 11px 12px;
  }

  .gc-table th:nth-child(n),
  .gc-table td:nth-child(n) {
    width: auto;
  }

  .gc-table td {
    display: grid;
    grid-template-columns: minmax(90px, 0.36fr) minmax(0, 1fr);
    gap: 12px;
    align-items: start;
  }

  .gc-table td:last-child {
    border-bottom: 0;
  }

  .gc-table td::before {
    color: #5b6472;
    font-size: 11px;
    font-weight: 850;
    letter-spacing: 0;
    text-transform: uppercase;
  }

  .gc-table td:nth-child(1)::before {
    content: "Document";
  }

  .gc-table td:nth-child(2)::before {
    content: "Type";
  }

  .gc-table td:nth-child(3)::before {
    content: "Parse";
  }

  .gc-table td:nth-child(4)::before {
    content: "Analysis";
  }

  .gc-table td:nth-child(5)::before {
    content: "Uploaded";
  }

  .gc-table td:nth-child(6)::before {
    content: "Actions";
  }

  .gc-action-row {
    justify-content: flex-start;
  }
}

@media (max-width: 980px) {
  .gc-upload-form {
    grid-template-columns: 1fr;
    gap: 18px;
  }

  .gc-upload-details {
    min-height: 0;
  }

  .gc-controls,
  .gc-hero {
    align-items: stretch;
    flex-direction: column;
  }

  .gc-filter-tabs {
    align-self: flex-start;
    max-width: 100%;
    overflow-x: auto;
  }
}

@media (max-width: 760px) {
  .documents-review {
    padding: 22px 12px 36px;
  }

  .gc-upload-card {
    padding: 14px;
  }

  .gc-upload-row {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .gc-upload-zones {
    grid-template-columns: 1fr;
  }

  .gc-filter-tabs {
    flex-wrap: wrap;
    width: 100%;
    overflow: visible;
  }

  .gc-filter-tabs button {
    flex: 1 1 104px;
    min-width: 0;
  }
}

@media (max-width: 520px) {
  .gc-table td {
    grid-template-columns: 1fr;
    gap: 6px;
  }

  .gc-action-row {
    align-items: stretch;
    flex-wrap: wrap;
  }

  .gc-action-row > * {
    flex: 1 1 96px;
  }

  .gc-selected-file {
    align-items: stretch;
    flex-direction: column;
  }
}
`;
