"use client";

import { FormEvent, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { USER_SELECTABLE_DOCUMENT_TYPES, uploadDocument, type DocumentType } from "@/lib/api/documents";

export default function UploadPage() {
  const [title, setTitle] = useState("");
  const [manualType, setManualType] = useState<DocumentType | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

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
      <main className="main stack">
        <div>
          <h1>Upload</h1>
          <p className="muted">Supported formats: .docx, .pdf, .md, .txt</p>
        </div>
        <form className="panel stack" onSubmit={submit}>
          <div className="form-grid">
            <label>
              Title
              <input value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label>
              Manual type
              <select value={manualType} onChange={(event) => setManualType(event.target.value as DocumentType | "")}>
                <option value="">Auto detect</option>
                {USER_SELECTABLE_DOCUMENT_TYPES.map((item) => (
                  <option key={item} value={item}>
                    {item.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              File
              <input
                accept=".docx,.pdf,.md,.txt"
                type="file"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
          </div>
          {file ? <div className="muted">Selected: {file.name}</div> : null}
          {error ? <div className="error">{error}</div> : null}
          <div>
            <button disabled={pending || !file} type="submit">
              Upload document
            </button>
          </div>
        </form>
      </main>
    </AppShell>
  );
}
