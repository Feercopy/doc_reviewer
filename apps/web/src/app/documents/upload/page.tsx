"use client";

import { DragEvent, FormEvent, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { USER_SELECTABLE_DOCUMENT_TYPES, uploadDocument, type DocumentType } from "@/lib/api/documents";
import { formatLabel } from "@/lib/format";

const supportedExtensions = [".docx", ".pdf", ".md", ".txt"];

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

export default function UploadPage() {
  const [title, setTitle] = useState("");
  const [manualType, setManualType] = useState<DocumentType | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const inferredTitle = useMemo(() => {
    if (!file) {
      return "";
    }
    return file.name.replace(/\.[^.]+$/, "");
  }, [file]);

  function chooseFile(nextFile: File | null) {
    setError("");
    if (!nextFile) {
      setFile(null);
      return;
    }
    if (!hasSupportedExtension(nextFile)) {
      setFile(null);
      setError("Unsupported file type. Use .docx, .pdf, .md, or .txt.");
      return;
    }
    setFile(nextFile);
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files[0] ?? null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Choose a document file");
      return;
    }
    setPending(true);
    setError("");
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
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell>
      <main className="gc-dark-page upload-workbench">
        <style>{uploadStyles}</style>
        <section className="gc-upload-hero">
          <div>
            <p className="gc-eyebrow">New evidence</p>
            <h1>Upload document</h1>
            <p className="gc-muted">Start with the source file. Parsing and type detection run after upload.</p>
          </div>
        </section>

        <form className="gc-upload-layout" onSubmit={submit}>
          <section className="gc-drop-panel">
            <div
              className={`gc-dropzone${dragging ? " is-dragging" : ""}${file ? " has-file" : ""}`}
              role="button"
              tabIndex={0}
              onClick={() => fileInputRef.current?.click()}
              onDragLeave={handleDragLeave}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
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

            {file ? (
              <div className="gc-selected-file">
                <div>
                  <strong>{file.name}</strong>
                  <span>{formatBytes(file.size)}</span>
                </div>
                <button
                  className="gc-compact-danger"
                  disabled={pending}
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

            <div className="gc-support-panel">
              <h2>Supported inputs</h2>
              <ul>
                <li>Word documents for defense decks exported as text-bearing .docx files.</li>
                <li>PDF files with selectable text.</li>
                <li>Markdown or plain text notes for fast benchmark checks.</li>
              </ul>
            </div>
          </section>

          <section className="gc-form-panel">
            <div className="gc-panel-heading">
              <div>
                <h2>Document metadata</h2>
                <p>Title and type can be corrected later from the detail screen.</p>
              </div>
            </div>

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

            {error ? <div className="gc-alert">{error}</div> : null}

            {pending ? (
              <div className="gc-upload-progress" aria-live="polite">
                <span />
                <div>
                  <strong>Uploading</strong>
                  <small>The document detail page opens after the upload finishes.</small>
                </div>
              </div>
            ) : null}

            <button className="gc-primary gc-submit" disabled={pending || !file} type="submit">
              {pending ? "Uploading..." : "Upload document"}
            </button>
          </section>
        </form>
      </main>
    </AppShell>
  );
}

const uploadStyles = `
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
  width: min(1180px, 100%);
  min-height: calc(100vh - 69px);
  margin: 0 auto;
  padding: 32px 24px 48px;
  color: #eef2ff;
}

.gc-upload-hero {
  margin-bottom: 24px;
}

.gc-upload-hero h1 {
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
.gc-selected-file span,
.gc-upload-progress small,
.gc-support-panel li,
.gc-drop-copy p {
  color: #94a3b8;
}

.gc-muted {
  margin: 8px 0 0;
}

.gc-upload-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: 16px;
  align-items: start;
}

.gc-drop-panel,
.gc-form-panel,
.gc-support-panel,
.gc-selected-file {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: #0d1424;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.24);
}

.gc-drop-panel,
.gc-form-panel {
  padding: 16px;
}

.gc-dropzone {
  display: grid;
  min-height: 360px;
  place-items: center;
  gap: 18px;
  border: 1px dashed rgba(125, 211, 252, 0.38);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(8, 145, 178, 0.12), rgba(15, 23, 42, 0.26)),
    #090d16;
  color: #f8fafc;
  cursor: pointer;
  padding: 28px;
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
  width: 86px;
  height: 86px;
  place-items: center;
  border: 1px solid rgba(125, 211, 252, 0.36);
  border-radius: 8px;
  background: rgba(14, 116, 144, 0.18);
}

.gc-upload-mark span {
  position: relative;
  width: 34px;
  height: 42px;
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
  top: 10px;
  left: 8px;
  width: 14px;
  height: 2px;
}

.gc-upload-mark span::after {
  top: 18px;
  left: 8px;
  width: 18px;
  height: 2px;
}

.gc-drop-copy {
  display: grid;
  gap: 8px;
}

.gc-drop-copy strong {
  font-size: 24px;
  line-height: 1.2;
}

.gc-drop-copy p {
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

.gc-selected-file {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 12px;
  padding: 14px;
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

.gc-support-panel {
  margin-top: 12px;
  padding: 16px;
}

.gc-support-panel h2,
.gc-panel-heading h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 16px;
  letter-spacing: 0;
}

.gc-support-panel ul {
  display: grid;
  gap: 8px;
  margin: 12px 0 0;
  padding-left: 18px;
}

.gc-support-panel li {
  line-height: 1.5;
}

.gc-panel-heading {
  margin-bottom: 16px;
}

.gc-panel-heading p {
  margin: 5px 0 0;
  font-size: 13px;
}

.gc-field-stack {
  display: grid;
  gap: 14px;
}

.gc-field-stack label {
  color: #cbd5e1;
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

.gc-alert {
  margin-top: 16px;
  border: 1px solid rgba(248, 113, 113, 0.34);
  border-radius: 8px;
  background: rgba(127, 29, 29, 0.28);
  color: #fecaca;
  padding: 14px 16px;
}

.gc-primary,
.gc-compact-danger {
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

.gc-submit {
  width: 100%;
  margin-top: 18px;
}

.gc-primary:disabled {
  opacity: 0.48;
}

.gc-compact-danger {
  min-height: 34px;
  border: 1px solid rgba(248, 113, 113, 0.34);
  background: rgba(15, 23, 42, 0.92);
  color: #fecaca;
  padding: 0 10px;
  font-size: 12px;
}

.gc-upload-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
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

@media (max-width: 860px) {
  .gc-upload-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .gc-dark-page {
    padding: 22px 10px 36px;
  }

  .gc-upload-hero h1 {
    font-size: 32px;
  }

  .gc-dropzone {
    min-height: 280px;
    padding: 20px;
  }

  .gc-selected-file {
    align-items: stretch;
    flex-direction: column;
  }
}
`;
