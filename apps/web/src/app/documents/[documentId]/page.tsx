"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { resolveApiBaseUrl } from "@/lib/api/client";
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
} from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

export default function DocumentDetailPage() {
  const params = useParams<{ documentId: string }>();
  const documentId = params.documentId;
  const [document, setDocument] = useState<DocumentRecord | null>(null);
  const [parsedText, setParsedText] = useState("");
  const [analyses, setAnalyses] = useState<AnalysisRecord[]>([]);
  const [manualType, setManualType] = useState<DocumentType | "">("");
  const [provider, setProvider] = useState<Provider>("openai_compatible");
  const [model, setModel] = useState("gpt-test");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    const nextDocument = await getDocument(documentId);
    setDocument(nextDocument);
    setManualType(nextDocument.manual_document_type ?? "");
    listAnalyses(documentId).then((response) => setAnalyses(response.analyses)).catch(() => setAnalyses([]));
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
      <main className="main stack">
        {document ? (
          <>
            <div className="toolbar">
              <div>
                <h1>{document.title}</h1>
                <p className="muted">
                  {document.original_filename} · {formatDate(document.created_at)}
                </p>
              </div>
              <a className="secondary-link" href={`${resolveApiBaseUrl()}/documents/${document.id}/raw`}>
                Raw
              </a>
            </div>
            {error ? <section className="panel error">{error}</section> : null}
            <section className="panel stack">
              <div className="meta-grid">
                <div>
                  <div className="muted small">Parse status</div>
                  <StatusBadge status={document.parse_status} />
                </div>
                <div>
                  <div className="muted small">Detected type</div>
                  <strong>{formatLabel(document.detected_document_type)}</strong>
                  {document.document_type_confidence ? (
                    <div className="muted small">confidence {document.document_type_confidence}</div>
                  ) : null}
                </div>
                <div>
                  <div className="muted small">Manual type</div>
                  <select value={manualType} onChange={(event) => setManualType(event.target.value as DocumentType | "")}>
                    {["", ...USER_SELECTABLE_DOCUMENT_TYPES].map((item) => (
                      <option key={item || "auto"} value={item}>
                        {item ? formatLabel(item) : "Auto"}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {document.document_type_explanation ? (
                <div className="muted small">{document.document_type_explanation}</div>
              ) : null}
              {document.parse_error ? <div className="error">{document.parse_error}</div> : null}
              <div className="button-row">
                <button disabled={pending} type="button" onClick={saveType}>
                  Save type
                </button>
                <button className="secondary" disabled={pending} type="button" onClick={reparse}>
                  Reparse
                </button>
                <button className="danger" disabled={pending} type="button" onClick={removeDocument}>
                  Delete
                </button>
              </div>
            </section>

            <section className="panel stack">
              <h2>Parsed Text</h2>
              {parsedText ? <pre className="text-preview">{parsedText}</pre> : <div className="muted">Parsed text is not available yet.</div>}
            </section>

            <form className="panel stack" onSubmit={launchAnalysis}>
              <h2>Analysis</h2>
              <div className="form-grid">
                <label>
                  Provider
                  <select value={provider} onChange={(event) => setProvider(event.target.value as Provider)}>
                    <option value="openai_compatible">OpenAI compatible</option>
                    <option value="anthropic_compatible">Anthropic compatible</option>
                    <option value="hermes">Hermes</option>
                  </select>
                </label>
                <label>
                  Model
                  <input value={model} onChange={(event) => setModel(event.target.value)} />
                </label>
              </div>
              <div>
                <button disabled={pending || document.parse_status !== "completed" || !model} type="submit">
                  Start analysis
                </button>
              </div>
              {analyses.length > 0 ? (
                <table>
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Provider</th>
                      <th>Verdict</th>
                      <th>Created</th>
                      <th>Open</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analyses.map((analysis) => (
                      <tr key={analysis.id}>
                        <td>
                          <StatusBadge status={analysis.status} />
                        </td>
                        <td>
                          {analysis.provider}
                          <div className="muted">{analysis.model}</div>
                        </td>
                        <td>{formatLabel(analysis.verdict)}</td>
                        <td>{formatDate(analysis.created_at)}</td>
                        <td>
                          <Link className="secondary-link" href={`/analyses/${analysis.id}`}>
                            Open
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
            </form>
          </>
        ) : (
          <section className="panel muted">Loading...</section>
        )}
      </main>
    </AppShell>
  );
}
