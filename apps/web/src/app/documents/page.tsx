"use client";

import Link from "next/link";
import { DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  USER_SELECTABLE_DOCUMENT_TYPES,
  deleteDocument,
  listDocuments,
  uploadDocument,
  type DocumentRecord,
  type DocumentType,
  type ParseStatus,
} from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

type ParseFilter = "all" | ParseStatus;

const supportedExtensions = [".docx", ".pdf", ".md", ".txt"];

const parseFilters: { label: string; value: ParseFilter }[] = [
  { label: "All", value: "all" },
  { label: "Ready", value: "completed" },
  { label: "Parsing", value: "running" },
  { label: "Queued", value: "queued" },
  { label: "Needs attention", value: "failed" },
];

function getEffectiveType(document: DocumentRecord): string {
  return formatLabel(document.manual_document_type ?? document.detected_document_type);
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
      window.location.href = `/documents/${document.id}`;
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

  const recentDocuments = useMemo(
    () =>
      [...documents]
        .sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())
        .slice(0, 5),
    [documents],
  );

  const unresolvedDocuments = useMemo(
    () => documents.filter((document) => document.parse_status !== "completed" || document.parse_error).slice(0, 5),
    [documents],
  );

  return (
    <AppShell>
      <main className="gc-dark-page documents-review">
        <style>{documentsStyles}</style>
        <section className="gc-hero">
          <div>
            <p className="gc-eyebrow">Review queue</p>
            <h1>Documents</h1>
            <p className="gc-muted">Uploaded defenses, parser state, and analysis readiness.</p>
          </div>
          <div className="gc-hero-actions">
            <button className="gc-ghost" disabled={loading} type="button" onClick={() => void refresh()}>
              Refresh
            </button>
            <button className="gc-primary" type="button" onClick={() => fileInputRef.current?.click()}>
              Upload
            </button>
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
                <strong>{file ? "File selected" : "Drop a document here"}</strong>
                <p>{file ? "Review details before uploading." : "Choose or drag a supported defense document."}</p>
              </div>
              <div className="gc-format-row" aria-label="Supported formats">
                {supportedExtensions.map((extension) => (
                  <span key={extension}>{extension}</span>
                ))}
              </div>
            </div>

            <div className="gc-upload-details">
              <div className="gc-upload-heading">
                <p className="gc-eyebrow">New evidence</p>
                <h2>Upload document</h2>
                <p>Parsing and type detection run after upload.</p>
              </div>

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
                <label>
                  <span>Title</span>
                  <input
                    placeholder={inferredTitle || "Optional display title"}
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </label>

                <label>
                  <span>Manual type</span>
                  <select value={manualType} onChange={(event) => setManualType(event.target.value as DocumentType | "")}>
                    <option value="">Auto detect</option>
                    {USER_SELECTABLE_DOCUMENT_TYPES.map((item) => (
                      <option key={item} value={item}>
                        {formatLabel(item)}
                      </option>
                    ))}
                  </select>
                </label>
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

              <button className="gc-primary gc-submit" disabled={pendingUpload || !file} type="submit">
                {pendingUpload ? "Uploading..." : "Upload document"}
              </button>
            </div>
          </form>
        </section>

        <section className="gc-controls" aria-label="Document filters">
          <label className="gc-search-label">
            <span>Search</span>
            <input
              aria-label="Search documents"
              placeholder="Title, filename, type, parser error"
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

        <div className="gc-review-grid">
          <section className="gc-panel gc-table-panel">
            <div className="gc-panel-heading">
              <div>
                <h2>Queue</h2>
                <p>{loading ? "Loading documents" : `${filteredDocuments.length} shown from ${documents.length}`}</p>
              </div>
            </div>

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

                      return (
                        <tr key={document.id}>
                          <td>
                            <div className="gc-title-cell">
                              <strong>{document.title}</strong>
                              <span>{document.original_filename}</span>
                              <small>{formatBytes(document.file_size_bytes)}</small>
                            </div>
                          </td>
                          <td>
                            <span className="gc-type-badge">{getEffectiveType(document)}</span>
                            {document.manual_document_type ? <div className="gc-subtle">manual override</div> : null}
                          </td>
                          <td>
                            <StatusBadge status={document.parse_status} />
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
              </div>
            ) : null}
          </section>

          <aside className="gc-side-panel" aria-label="Recent activity and unresolved parser work">
            <section className="gc-panel">
              <div className="gc-panel-heading">
                <div>
                  <h2>Recent activity</h2>
                  <p>Derived from document updates.</p>
                </div>
              </div>
              <div className="gc-activity-list">
                {recentDocuments.length === 0 ? <div className="gc-empty compact">No activity yet.</div> : null}
                {recentDocuments.map((document) => (
                  <Link className="gc-activity-item" href={`/documents/${document.id}`} key={document.id}>
                    <span>
                      <strong>{document.title}</strong>
                      <small>{formatDate(document.updated_at)}</small>
                    </span>
                    <StatusBadge status={document.parse_status} />
                  </Link>
                ))}
              </div>
            </section>

            <section className="gc-panel">
              <div className="gc-panel-heading">
                <div>
                  <h2>Unresolved</h2>
                  <p>Parser work still blocking analysis.</p>
                </div>
              </div>
              <div className="gc-activity-list">
                {unresolvedDocuments.length === 0 ? (
                  <div className="gc-empty compact">No parser blockers in the current queue.</div>
                ) : null}
                {unresolvedDocuments.map((document) => (
                  <Link className="gc-activity-item" href={`/documents/${document.id}`} key={document.id}>
                    <span>
                      <strong>{document.title}</strong>
                      <small>{document.parse_error ?? formatLabel(document.parse_status)}</small>
                    </span>
                    <StatusBadge status={document.parse_status} />
                  </Link>
                ))}
              </div>
            </section>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}

const documentsStyles = `
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
.gc-controls,
.gc-review-grid,
.gc-upload-form,
.gc-hero-actions,
.gc-action-row,
.gc-filter-tabs {
  display: flex;
}

.gc-hero {
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
}

.gc-hero h1 {
  margin: 0;
  font-size: 40px;
  line-height: 1.05;
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
.gc-subtle,
.gc-date,
.gc-title-cell span,
.gc-title-cell small,
.gc-activity-item small {
  color: #94a3b8;
}

.gc-muted {
  margin: 8px 0 0;
}

.gc-hero-actions,
.gc-action-row {
  align-items: center;
  gap: 10px;
}

.gc-primary,
.gc-ghost,
.gc-compact-link,
.gc-compact-danger,
.gc-filter-tabs button {
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

.gc-ghost,
.gc-filter-tabs button {
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.88);
  color: #dbeafe;
  padding: 0 14px;
}

.gc-ghost:hover,
.gc-compact-link:hover,
.gc-filter-tabs button:hover,
.gc-activity-item:hover {
  border-color: rgba(125, 211, 252, 0.54);
}

.gc-upload-card,
.gc-panel,
.gc-controls,
.gc-selected-file {
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: #0d1424;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.24);
}

.gc-upload-card {
  border-radius: 8px;
  margin-bottom: 14px;
  padding: 14px;
}

.gc-upload-form {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
  gap: 14px;
  align-items: stretch;
}

.gc-dropzone {
  display: grid;
  min-height: 220px;
  place-items: center;
  gap: 14px;
  border: 1px dashed rgba(125, 211, 252, 0.38);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(8, 145, 178, 0.12), rgba(15, 23, 42, 0.26)),
    #090d16;
  color: #f8fafc;
  cursor: pointer;
  padding: 20px;
  text-align: center;
  transition: border-color 180ms ease, background 180ms ease, transform 180ms ease;
}

.gc-dropzone:hover,
.gc-dropzone.is-dragging {
  border-color: rgba(34, 211, 238, 0.86);
  background:
    linear-gradient(180deg, rgba(8, 145, 178, 0.22), rgba(15, 23, 42, 0.42)),
    #090d16;
}

.gc-dropzone.is-dragging {
  transform: translateY(-2px);
}

.gc-dropzone.has-file {
  border-style: solid;
  border-color: rgba(34, 197, 94, 0.48);
}

.gc-dropzone input {
  display: none;
}

.gc-upload-mark {
  display: grid;
  width: 64px;
  height: 64px;
  place-items: center;
  border: 1px solid rgba(125, 211, 252, 0.36);
  border-radius: 8px;
  background: rgba(14, 116, 144, 0.18);
}

.gc-upload-mark span {
  position: relative;
  width: 27px;
  height: 34px;
  border: 2px solid #a5f3fc;
  border-radius: 5px;
}

.gc-upload-mark span::before,
.gc-upload-mark span::after {
  position: absolute;
  content: "";
  background: #a5f3fc;
}

.gc-upload-mark span::before {
  top: 9px;
  left: 7px;
  width: 11px;
  height: 2px;
}

.gc-upload-mark span::after {
  top: 16px;
  left: 7px;
  width: 15px;
  height: 2px;
}

.gc-drop-copy {
  display: grid;
  gap: 6px;
}

.gc-drop-copy strong {
  font-size: 22px;
  line-height: 1.2;
}

.gc-drop-copy p,
.gc-upload-heading p,
.gc-selected-file span,
.gc-upload-progress small {
  color: #94a3b8;
}

.gc-drop-copy p,
.gc-upload-heading p {
  margin: 0;
}

.gc-format-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.gc-format-row span {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.82);
  color: #cbd5e1;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-upload-details {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: space-between;
}

.gc-upload-heading {
  margin-bottom: 14px;
}

.gc-upload-heading h2 {
  margin: 0 0 6px;
  color: #f8fafc;
  font-size: 20px;
  letter-spacing: 0;
}

.gc-selected-file {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-radius: 8px;
  margin-bottom: 14px;
  padding: 12px;
}

.gc-selected-file div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.gc-selected-file strong {
  overflow: hidden;
  color: #f8fafc;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-field-stack {
  display: grid;
  gap: 12px;
}

.gc-field-stack label {
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-submit {
  width: 100%;
  margin-top: 16px;
}

.gc-primary:disabled {
  opacity: 0.48;
}

.gc-upload-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  border: 1px solid rgba(34, 211, 238, 0.26);
  border-radius: 8px;
  background: rgba(8, 145, 178, 0.14);
  padding: 12px;
}

.gc-upload-progress span {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(165, 243, 252, 0.32);
  border-top-color: #a5f3fc;
  border-radius: 999px;
  animation: gc-spin 900ms linear infinite;
}

.gc-upload-progress div {
  display: grid;
  gap: 2px;
}

.gc-upload-progress strong {
  color: #f8fafc;
}

.gc-controls {
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  border-radius: 8px;
  padding: 14px;
}

.gc-search-label {
  width: min(460px, 100%);
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.gc-search-label input,
.gc-dark-page select,
.gc-dark-page input {
  border-color: rgba(148, 163, 184, 0.22);
  background: #090d16;
  color: #eef2ff;
}

.gc-search-label input::placeholder {
  color: #64748b;
}

.gc-filter-tabs {
  flex-wrap: wrap;
  gap: 8px;
}

.gc-filter-tabs button {
  min-height: 36px;
  font-size: 13px;
}

.gc-filter-tabs button.is-active {
  border-color: rgba(34, 211, 238, 0.82);
  background: rgba(8, 145, 178, 0.24);
  color: #a5f3fc;
}

.gc-review-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
  gap: 16px;
  align-items: start;
}

.gc-panel {
  border-radius: 8px;
  padding: 16px;
}

.gc-table-panel {
  min-width: 0;
  padding: 0;
  overflow: hidden;
}

.gc-panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 16px 12px;
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

.gc-table-scroll {
  width: 100%;
  overflow-x: auto;
}

.gc-table {
  min-width: 920px;
}

.gc-table th,
.gc-table td {
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  padding: 13px 16px;
}

.gc-table th {
  color: #94a3b8;
  font-size: 11px;
  letter-spacing: 0;
}

.gc-table th:nth-child(2),
.gc-table td:nth-child(2) {
  width: 118px;
}

.gc-table th:nth-child(4),
.gc-table td:nth-child(4) {
  width: 156px;
}

.gc-table tbody tr:hover {
  background: rgba(15, 23, 42, 0.72);
}

.gc-title-cell {
  display: grid;
  gap: 4px;
  min-width: 240px;
}

.gc-title-cell strong,
.gc-activity-item strong {
  color: #f8fafc;
}

.gc-type-badge,
.gc-signal,
.gc-dark-page .badge {
  display: inline-flex;
  min-height: 26px;
  align-items: center;
  border-radius: 999px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.15;
  text-transform: uppercase;
  white-space: nowrap;
}

.gc-type-badge {
  border: 1px solid rgba(125, 211, 252, 0.32);
  background: rgba(14, 116, 144, 0.16);
  color: #bae6fd;
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

.gc-signal {
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(15, 23, 42, 0.8);
  color: #cbd5e1;
}

.gc-signal.is-good {
  border-color: rgba(34, 197, 94, 0.36);
  color: #bbf7d0;
}

.gc-signal.is-info {
  border-color: rgba(56, 189, 248, 0.36);
  color: #bae6fd;
}

.gc-signal.is-warn {
  border-color: rgba(245, 158, 11, 0.38);
  color: #fde68a;
}

.gc-signal.is-bad {
  border-color: rgba(248, 113, 113, 0.42);
  color: #fecaca;
}

.gc-error-text {
  max-width: 260px;
  margin-top: 8px;
  color: #fca5a5;
  font-size: 12px;
  line-height: 1.4;
}

.gc-compact-link,
.gc-compact-danger {
  min-height: 34px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.92);
  color: #dbeafe;
  padding: 0 10px;
  font-size: 12px;
}

.gc-compact-danger {
  border-color: rgba(248, 113, 113, 0.34);
  color: #fecaca;
}

.gc-side-panel {
  display: grid;
  gap: 16px;
}

.gc-side-panel .gc-panel {
  padding: 0;
}

.gc-activity-list {
  display: grid;
  gap: 8px;
  padding: 0 12px 12px;
}

.gc-activity-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.58);
  padding: 12px;
}

.gc-activity-item span {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.gc-activity-item strong,
.gc-activity-item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gc-empty {
  display: grid;
  gap: 14px;
  place-items: center;
  min-height: 180px;
  color: #94a3b8;
  padding: 24px;
  text-align: center;
}

.gc-empty.compact {
  min-height: 88px;
  padding: 16px;
}

.gc-alert {
  margin-bottom: 16px;
  border: 1px solid rgba(248, 113, 113, 0.34);
  border-radius: 8px;
  background: rgba(127, 29, 29, 0.28);
  color: #fecaca;
  padding: 14px 16px;
}

.gc-alert.inline {
  margin: 14px 0 0;
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

@media (max-width: 1620px) {
  .gc-review-grid {
    grid-template-columns: 1fr;
  }

  .gc-side-panel {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .gc-review-grid,
  .gc-upload-form {
    grid-template-columns: 1fr;
  }

  .gc-side-panel {
    grid-template-columns: 1fr;
  }

  .gc-controls,
  .gc-hero {
    align-items: stretch;
    flex-direction: column;
  }

  .gc-hero-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .gc-dark-page {
    padding: 22px 10px 36px;
  }

  .gc-hero h1 {
    font-size: 32px;
  }

  .gc-hero-actions,
  .gc-action-row {
    flex-wrap: wrap;
  }

  .gc-dropzone {
    min-height: 240px;
    padding: 18px;
  }

  .gc-selected-file {
    align-items: stretch;
    flex-direction: column;
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
  }

  .gc-table thead {
    display: none;
  }

  .gc-table tbody {
    display: grid;
    gap: 10px;
    padding: 0 10px 10px;
  }

  .gc-table tr {
    display: grid;
    gap: 0;
    border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 8px;
    background: rgba(15, 23, 42, 0.7);
    overflow: hidden;
  }

  .gc-table th,
  .gc-table td {
    border-bottom: 1px solid rgba(148, 163, 184, 0.12);
    padding: 11px 12px;
  }

  .gc-table th:nth-child(2),
  .gc-table td:nth-child(2),
  .gc-table th:nth-child(4),
  .gc-table td:nth-child(4) {
    width: auto;
  }

  .gc-table td {
    display: grid;
    grid-template-columns: minmax(90px, 0.38fr) minmax(0, 1fr);
    gap: 12px;
    align-items: start;
  }

  .gc-table td:last-child {
    border-bottom: 0;
  }

  .gc-table td::before {
    color: #94a3b8;
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

  .gc-title-cell {
    min-width: 0;
  }

  .gc-date,
  .gc-title-cell strong,
  .gc-title-cell span,
  .gc-title-cell small {
    overflow-wrap: anywhere;
    white-space: normal;
  }

  .gc-action-row {
    align-items: stretch;
  }

  .gc-action-row > * {
    flex: 1 1 96px;
  }
}
`;
