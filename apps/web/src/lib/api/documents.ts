import { apiFetch, apiFetchNoContent, apiFetchText } from "./client";

export type DocumentType =
  | "gate_2"
  | "stream_review_1"
  | "stream_review_2_plus"
  | "gate_3"
  | "unknown";

export const USER_SELECTABLE_DOCUMENT_TYPES = [
  "gate_2",
  "stream_review_1",
  "stream_review_2_plus",
  "gate_3",
] as const satisfies readonly DocumentType[];

export type ParseStatus = "queued" | "running" | "completed" | "failed";
export type Provider = "openai_compatible" | "anthropic_compatible" | "hermes";
export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type OutputLanguage = "ru" | "en";

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
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: string | null;
  run_parameters: Record<string, unknown>;
  source_trace: SourceTrace | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  predicted_comment_run: PredictedCommentRunRecord | null;
  detail_run: AnalysisDetailRunRecord | null;
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
  source_trace: SourceTrace | null;
  retrieval_trace: RetrievalTrace | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type SourceTrace = {
  source_snapshot_id: string | null;
  source_slug: string | null;
  source_revision: string | null;
  source_fingerprint: string | null;
  snapshot_mode: string | null;
  is_dirty: boolean | null;
  prompt_fingerprint: string | null;
  rendered_prompt_artifact_path: string | null;
};

export type RetrievalTrace = {
  retrieval_snapshot_id: string | null;
  retrieval_mode: string | null;
  retrieval_version: string | null;
  corpus_fingerprint: string | null;
  query_fingerprint: string | null;
  prompt_fingerprint: string | null;
  rendered_prompt_artifact_path: string | null;
};

export type AnalysisDetailRunRecord = {
  id: string;
  analysis_id: string;
  status: RunStatus;
  provider: Provider;
  model: string;
  previous_response_id: string | null;
  response_id: string | null;
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
  run_parameters?: Record<string, unknown> & {
    output_language?: OutputLanguage;
  };
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

export async function patchDocumentTitle(documentId: string, title: string): Promise<DocumentRecord> {
  return apiFetch<DocumentRecord>(`/documents/${documentId}/title`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function getParsedText(documentId: string): Promise<string> {
  return apiFetchText(`/documents/${documentId}/parsed-text`);
}

export async function reparseDocument(documentId: string): Promise<DocumentRecord> {
  return apiFetch<DocumentRecord>(`/documents/${documentId}/reparse`, { method: "POST" });
}

export async function deleteDocument(documentId: string): Promise<void> {
  return apiFetchNoContent(`/documents/${documentId}`, { method: "DELETE" });
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

export async function createAnalysisDetails(analysisId: string): Promise<AnalysisDetailRunRecord> {
  return apiFetch<AnalysisDetailRunRecord>(`/analyses/${analysisId}/details`, { method: "POST" });
}

export async function deleteAnalysis(analysisId: string): Promise<void> {
  return apiFetchNoContent(`/analyses/${analysisId}`, { method: "DELETE" });
}

export async function getAnalysis(analysisId: string): Promise<AnalysisRecord> {
  return apiFetch<AnalysisRecord>(`/analyses/${analysisId}`);
}
