"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { listAdminDocuments, type AdminDocument } from "@/lib/api/admin";
import { USER_SELECTABLE_DOCUMENT_TYPES, deleteDocument, type DocumentType } from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

export default function AdminDocumentsPage() {
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [ownerId, setOwnerId] = useState("");
  const [documentType, setDocumentType] = useState<DocumentType | "">("");
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState("");

  async function refresh() {
    const response = await listAdminDocuments({ owner_id: ownerId, document_type: documentType });
    setDocuments(response.documents);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin documents"));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin documents"));
  }

  async function handleDelete(document: AdminDocument) {
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

  return (
    <AppShell>
      <main className="main stack">
        <AdminTabs />
        <div>
          <h1>Admin Documents</h1>
          <p className="muted">All uploaded documents with owner and parse metadata.</p>
        </div>
        <form className="panel form-grid" onSubmit={submit}>
          <label>
            Owner ID
            <input value={ownerId} onChange={(event) => setOwnerId(event.target.value)} />
          </label>
          <label>
            Type
            <select value={documentType} onChange={(event) => setDocumentType(event.target.value as DocumentType | "")}>
              {["", ...USER_SELECTABLE_DOCUMENT_TYPES].map((item) => (
                <option key={item || "all"} value={item}>
                  {item ? formatLabel(item) : "All"}
                </option>
              ))}
            </select>
          </label>
          <label>
            &nbsp;
            <button type="submit">Apply filters</button>
          </label>
        </form>
        {error ? <div className="error">{error}</div> : null}
        <section className="panel table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Owner</th>
                <th>Type</th>
                <th>Parse</th>
                <th>Status</th>
                <th>Uploaded</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((item) => (
                <tr key={item.id}>
                  <td>{item.title}</td>
                  <td>{item.owner_login}</td>
                  <td>{formatLabel(item.manual_document_type ?? item.detected_document_type)}</td>
                  <td>{formatLabel(item.parse_status)}</td>
                  <td>{formatLabel(item.status)}</td>
                  <td>{formatDate(item.created_at)}</td>
                  <td className="button-row">
                    <Link className="secondary-link" href={`/documents/${item.id}`}>
                      Open
                    </Link>
                    <button
                      className="danger"
                      disabled={deletingId === item.id}
                      type="button"
                      onClick={() => handleDelete(item)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>
    </AppShell>
  );
}
