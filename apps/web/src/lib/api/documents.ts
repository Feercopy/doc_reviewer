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
  ic_review_run: AnalysisCheckRunRecord | null;
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

export type IcReviewVerdict = "GO" | "CONDITIONAL" | "NO-GO" | "FREEZE" | "UNKNOWN";
export type IcReviewSeverity = "blocker" | "critical" | "high" | "medium" | "info" | "data_gap";
export type IcReviewRole =
  | "ic-financial-auditor"
  | "ic-product-analyst"
  | "ic-market-analyst"
  | "ic-web-researcher"
  | "ic-benchmark-valuation"
  | "ic-team-legal"
  | "ic-tech-dd"
  | "ic-risk-scenario";

export type IcReviewFinding = {
  title: string;
  severity: IcReviewSeverity;
  summary: string;
  evidence: string;
  recommendation: string;
};

export type IcReviewKeyNumber = {
  label: string;
  value: string;
  unit: string;
  source: string;
};

export type IcReviewSpreadsheetAudit = {
  status: "not_provided" | "completed" | "failed";
  summary: string;
  formula_issues_count: number;
  critical_formula_issues_count: number;
  source_filename: string | null;
};

export type IcReviewValidationSummary = {
  status: "pass" | "warn" | "fail" | "not_run";
  summary: string;
  warnings_count: number;
  failures_count: number;
};

export type IcReviewResultArtifact = {
  kind:
    | "formula_audit"
    | "legacy_report_json"
    | "legacy_report_text"
    | "legacy_audit_xlsx"
    | "validation_report"
    | "script_log"
    | "other";
  filename: string;
  summary: string;
};

export type IcReviewRoleSummary = {
  role: IcReviewRole;
  summary: string;
};

export type IcReviewCompactResult = {
  run_mode: "ic_agentic_review_compact";
  verdict: IcReviewVerdict;
  executive_brief: string;
  confidence: number;
  top_findings: IcReviewFinding[];
  key_numbers: IcReviewKeyNumber[];
  spreadsheet_audit: IcReviewSpreadsheetAudit;
  critical_risks: string[];
  data_gaps: string[];
  required_actions: string[];
  questions_for_team: string[];
  role_summaries: IcReviewRoleSummary[];
  validation: IcReviewValidationSummary;
  artifacts: IcReviewResultArtifact[];
};

export type IcReviewRoleResult = {
  role: IcReviewRole;
  section_keys: string[];
  summary: string;
  findings: Omit<IcReviewFinding, "summary">[];
  data_gaps: string[];
  numbers_used: Omit<IcReviewKeyNumber, "unit">[];
};

export type IcReviewArtifactRecord = {
  key?: string;
  kind?: IcReviewResultArtifact["kind"] | string;
  filename?: string;
  summary?: string;
  media_type?: string;
  visibility?: string;
  path?: string;
};

export type IcReviewWorkbookMetadata = {
  filename?: string;
  safe_filename?: string;
  size_bytes?: number;
  sha256?: string;
  storage_path?: string;
};

export type AnalysisCheckStepRecord = {
  id: string;
  check_run_id: string;
  step_type: string;
  step_name: string;
  status: RunStatus;
  prompt_fingerprint: string | null;
  prompt_artifact_path: string | null;
  raw_output: string | null;
  structured_output: IcReviewRoleResult | Record<string, unknown> | null;
  error_message: string | null;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: string | null;
  artifacts: IcReviewArtifactRecord[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type AnalysisCheckRunRecord = {
  id: string;
  analysis_id: string;
  skill_id: string;
  skill_name: string;
  skill_version: string;
  check_type: string;
  provider: Provider;
  model: string;
  status: RunStatus;
  current_stage: string | null;
  structured_output: IcReviewCompactResult | Record<string, unknown> | null;
  legacy_output: Record<string, unknown> | null;
  raw_output: string | null;
  error_message: string | null;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: string | null;
  run_parameters: Record<string, unknown>;
  uploaded_workbook_metadata: IcReviewWorkbookMetadata;
  artifacts: IcReviewArtifactRecord[];
  source_trace: SourceTrace | null;
  steps: AnalysisCheckStepRecord[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type AnalysisCheckRunsListResponse = {
  runs: AnalysisCheckRunRecord[];
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
