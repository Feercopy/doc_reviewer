"use client";

import Link from "next/link";
import { DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  USER_SELECTABLE_DOCUMENT_TYPES,
  deleteDocument,
  listDocuments,
  uploadDocument,
  type DocumentRecord,
  type DocumentType,
  type ParseStatus,
} from "@/lib/api/documents";
import { formatDate } from "@/lib/format";
import { appPath } from "@/lib/routing";
import { formatDocumentTypeLabel, getDocumentFileKind, getDocumentParsePresentation } from "./documentsDisplay";

type ParseFilter = "all" | ParseStatus;

const supportedExtensions = [".docx", ".pdf", ".md", ".txt"];

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

function hasSupportedExtension(file: File): boolean {
  const name = file.name.toLowerCase();
  return supportedExtensions.some((extension) => name.endsWith(extension));
}

function getDocumentSignal(document: DocumentRecord): { label: string; tone: "good" | "info" | "warn" | "bad" } {
  if (document.parse_status === "completed") {
    return { label: "Ready for analysis", tone: "good" };
  }
  if (document.parse_status === "failed") {
    return { label: "Parser failed", tone: "bad" };
  }
  if (document.parse_status === "running") {
    return { label: "Parsing", tone: "info" };
  }
  return { label: "Queued", tone: "warn" };
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
  const [file, setFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [pendingUpload, setPendingUpload] = useState(false);
  const [draggingUpload, setDraggingUpload] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function refresh() {
    const response = await listDocuments();
    setDocuments(response.documents);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load documents"))
      .finally(() => setLoading(false));
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
    if (!file) {
      return "";
    }
    return file.name.replace(/\.[^.]+$/, "");
  }, [file]);

  function chooseFile(nextFile: File | null) {
    setUploadError("");
    if (!nextFile) {
      setFile(null);
      return;
    }
    if (!hasSupportedExtension(nextFile)) {
      setFile(null);
      setUploadError("Unsupported file type. Use .docx, .pdf, .md, or .txt.");
      return;
    }
    setFile(nextFile);
  }

  function handleUploadDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDraggingUpload(true);
  }

  function handleUploadDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDraggingUpload(false);
  }

  function handleUploadDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDraggingUpload(false);
    chooseFile(event.dataTransfer.files[0] ?? null);
  }

  async function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setUploadError("Choose a document file");
      return;
    }
    setPendingUpload(true);
    setUploadError("");

    const form = new FormData();
    form.set("file", file);
    if (title.trim()) {
      form.set("title", title.trim());
    }
    if (manualType) {
      form.set("manual_document_type", manualType);
    }

    try {
      const document = await uploadDocument(form);
      window.location.href = appPath(`/documents/${document.id}`);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setPendingUpload(false);
    }
  }

  const filteredDocuments = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return documents.filter((document) => {
      const matchesFilter = parseFilter === "all" || document.parse_status === parseFilter;
      const matchesQuery =
        !normalizedQuery ||
        [document.title, document.original_filename, getEffectiveType(document), document.parse_error ?? ""]
          .join(" ")
          .toLowerCase()
          .includes(normalizedQuery);

      return matchesFilter && matchesQuery;
    });
  }, [documents, parseFilter, query]);

  const shownStart = filteredDocuments.length > 0 ? 1 : 0;
  const shownEnd = filteredDocuments.length;

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
            <div
              className={`gc-dropzone${draggingUpload ? " is-dragging" : ""}${file ? " has-file" : ""}`}
              role="button"
              tabIndex={0}
              onClick={() => fileInputRef.current?.click()}
              onDragLeave={handleUploadDragLeave}
              onDragOver={handleUploadDragOver}
              onDrop={handleUploadDrop}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
            >
              <input
                aria-label="File"
                accept=".docx,.pdf,.md,.txt"
                ref={fileInputRef}
                type="file"
                onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
              />
              <div className="gc-upload-mark" aria-hidden="true">
                <span />
              </div>
              <div className="gc-drop-copy">
                <strong>{file ? "File selected" : "Drag and drop files here"}</strong>
                <p>{file ? "Review details before uploading." : "or click to browse"}</p>
              </div>
              <div className="gc-format-row" aria-label="Supported formats">
                <span>Supported formats: {supportedExtensions.join(", ")}</span>
                <span>Max file size: 100 MB</span>
              </div>
            </div>

            <div className="gc-upload-details">
              {file ? (
                <div className="gc-selected-file">
                  <div>
                    <strong>{file.name}</strong>
                    <span>{formatBytes(file.size)}</span>
                  </div>
                  <button
                    className="gc-compact-danger"
                    disabled={pendingUpload}
                    type="button"
                    onClick={() => {
                      setFile(null);
                      if (fileInputRef.current) {
                        fileInputRef.current.value = "";
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

                  <button className="gc-primary gc-submit" disabled={pendingUpload || !file} type="submit">
                    {pendingUpload ? "Uploading..." : "Upload document"}
                  </button>
                </div>
              </div>

              {uploadError ? <div className="gc-alert inline">{uploadError}</div> : null}

              {pendingUpload ? (
                <div className="gc-upload-progress" aria-live="polite">
                  <span />
                  <div>
                    <strong>Uploading</strong>
                    <small>The document detail page opens after the upload finishes.</small>
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
          {!loading && documents.length > 0 && filteredDocuments.length === 0 ? (
            <div className="gc-empty">No documents match the current filters.</div>
          ) : null}

          {filteredDocuments.length > 0 ? (
            <div className="gc-table-scroll">
              <table className="gc-table">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Type</th>
                    <th>Parse</th>
                    <th>Readiness</th>
                    <th>Uploaded</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDocuments.map((document) => {
                    const signal = getDocumentSignal(document);
                    const fileKind = getDocumentFileKind(document.original_filename);
                    const parseState = getDocumentParsePresentation(document.parse_status);

                    return (
                      <tr key={document.id}>
                        <td>
                          <div className="gc-document-cell">
                            <span className={`gc-file-kind is-${fileKind.tone}`} aria-hidden="true">
                              {fileKind.label}
                            </span>
                            <div className="gc-title-cell">
                              <strong>{document.title}</strong>
                              <span>{document.original_filename}</span>
                              <small>{formatBytes(document.file_size_bytes)}</small>
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
                          <span className={`gc-signal is-${signal.tone}`}>{signal.label}</span>
                        </td>
                        <td>
                          <span className="gc-date">{formatDate(document.created_at)}</span>
                        </td>
                        <td>
                          <div className="gc-action-row">
                            <Link className="gc-compact-link" href={`/documents/${document.id}`}>
                              Open
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
                  Showing {shownStart} to {shownEnd} of {documents.length} documents
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
  grid-template-columns: minmax(340px, 0.9fr) minmax(320px, 1fr);
  gap: 36px;
  align-items: center;
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

.gc-file-kind {
  display: inline-flex;
  width: 26px;
  height: 32px;
  flex: 0 0 26px;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: #ffffff;
  font-size: 10px;
  font-weight: 850;
  line-height: 1;
}

.gc-file-kind.is-word {
  background: #2f7dd1;
}

.gc-file-kind.is-pdf {
  background: #d82436;
}

.gc-file-kind.is-markdown,
.gc-file-kind.is-generic {
  background: #6b7280;
}

.gc-file-kind.is-text {
  background: #4b5563;
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
    content: "Readiness";
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
