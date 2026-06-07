import { apiFetch, apiFetchText } from "./client";

export type DocumentType =
  | "gate_1"
  | "gate_2"
  | "gate_3"
  | "progress_review"
  | "stream_review"
  | "strategy_review"
  | "unknown";

export type ParseStatus = "queued" | "running" | "completed" | "failed";
export type Provider = "openai_compatible" | "anthropic_compatible" | "hermes";
export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type DocumentRecord = {
  id: string;
  owner_id: string;
  title: string;
  original_filename: string;
  mime_type: string;
  file_size_bytes: number;
  file_hash_sha256: string;
  parse_status: ParseStatus;
  detected_document_type: DocumentType;
  document_type_confidence: string | null;
  document_type_explanation: string | null;
  manual_document_type: DocumentType | null;
  parse_error: string | null;
  status: "active" | "archived" | "deleted";
  created_at: string;
  updated_at: string;
};

export type DocumentsListResponse = {
  documents: DocumentRecord[];
};

export type AnalysisRecord = {
  id: string;
  document_id: string;
  user_id: string;
  skill_id: string;
  skill_name: string;
  skill_version: string;
  provider: Provider;
  model: string;
  status: RunStatus;
  verdict: string | null;
  summary: string | null;
  structured_output: Record<string, unknown> | null;
  raw_output: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  predicted_comment_run: PredictedCommentRunRecord | null;
};

export type PredictedCommentRunRecord = {
  id: string;
  analysis_id: string;
  skill_id: string;
  skill_name: string;
  skill_version: string;
  provider: Provider;
  model: string;
  status: RunStatus;
  structured_output: Record<string, unknown> | null;
  raw_output: string | null;
  error_message: string | null;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: string | null;
  run_parameters: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type AnalysesListResponse = {
  analyses: AnalysisRecord[];
};

export type AnalysisCreatePayload = {
  provider: Provider;
  model: string;
  skill_id?: string;
  document_type_override?: DocumentType;
  run_parameters?: Record<string, unknown>;
};

export async function listDocuments(): Promise<DocumentsListResponse> {
  return apiFetch<DocumentsListResponse>("/documents");
}

export async function getDocument(documentId: string): Promise<DocumentRecord> {
  return apiFetch<DocumentRecord>(`/documents/${documentId}`);
}

export async function uploadDocument(form: FormData): Promise<DocumentRecord> {
  return apiFetch<DocumentRecord>("/documents", {
    method: "POST",
    body: form,
  });
}

export async function patchDocumentType(
  documentId: string,
  manualDocumentType: DocumentType | null,
): Promise<DocumentRecord> {
  return apiFetch<DocumentRecord>(`/documents/${documentId}/document-type`, {
    method: "PATCH",
    body: JSON.stringify({ manual_document_type: manualDocumentType }),
  });
}

export async function getParsedText(documentId: string): Promise<string> {
  return apiFetchText(`/documents/${documentId}/parsed-text`);
}

export async function reparseDocument(documentId: string): Promise<DocumentRecord> {
  return apiFetch<DocumentRecord>(`/documents/${documentId}/reparse`, { method: "POST" });
}

export async function listAnalyses(documentId: string): Promise<AnalysesListResponse> {
  return apiFetch<AnalysesListResponse>(`/documents/${documentId}/analyses`);
}

export async function createAnalysis(
  documentId: string,
  payload: AnalysisCreatePayload,
): Promise<AnalysisRecord> {
  return apiFetch<AnalysisRecord>(`/documents/${documentId}/analyses`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAnalysis(analysisId: string): Promise<AnalysisRecord> {
  return apiFetch<AnalysisRecord>(`/analyses/${analysisId}`);
}
