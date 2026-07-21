"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { listAdminDocuments, type AdminDocument } from "@/lib/api/admin";
import { USER_SELECTABLE_DOCUMENT_TYPES, deleteDocument, type DocumentType } from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

export default function AdminDocumentsPage() {
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [ownerId, setOwnerId] = useState("");
  const [documentType, setDocumentType] = useState<DocumentType | "">("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState("");

  async function refresh() {
    const response = await listAdminDocuments({ owner_id: ownerId, document_type: documentType });
    setDocuments(response.documents);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load admin documents"))
      .finally(() => setLoading(false));
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
        <div className="toolbar">
          <div>
            <h1>Admin Documents</h1>
            <p className="muted">All uploaded documents with owner, parse, and lifecycle metadata.</p>
          </div>
          <span className="badge info">{documents.length} documents</span>
        </div>
        <form className="panel stack" onSubmit={submit}>
          <h2>Filters</h2>
          <div className="form-grid">
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
          </div>
        </form>
        {error ? <section className="panel error">{error}</section> : null}
        <section className="panel stack">
          <h2>Documents</h2>
          {loading ? <div className="muted">Loading documents...</div> : null}
          {!loading && documents.length === 0 ? <div className="muted">No documents match the current filters.</div> : null}
          {!loading && documents.length > 0 ? (
            <div className="table-wrap">
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
                      <td>
                        <strong>{item.title}</strong>
                        <div className="muted small">{item.original_filename}</div>
                      </td>
                      <td>{item.owner_login}</td>
                      <td>{formatLabel(item.manual_document_type ?? item.detected_document_type)}</td>
                      <td>
                        <StatusBadge status={item.parse_status} />
                      </td>
                      <td>
                        <StatusBadge status={item.status} />
                      </td>
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
            </div>
          ) : null}
        </section>
      </main>
    </AppShell>
  );
}
