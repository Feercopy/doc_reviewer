import { apiFetch, apiFetchNoContent } from "./client";
import type { DocumentType, Provider } from "./documents";
import type { SkillRecord } from "./skills";

export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type EntityStatus = "active" | "archived" | "deleted";
export type EtalonStatus = "draft" | "active" | "archived" | "deleted";

export type AdminDocument = {
  id: string;
  owner_id: string;
  owner_login: string;
  title: string;
  original_filename: string;
  parse_status: string;
  detected_document_type: DocumentType;
  manual_document_type: DocumentType | null;
  status: EntityStatus;
  parsed_text_available: boolean;
  created_at: string;
  updated_at: string;
};

export type AdminAnalysis = {
  id: string;
  document_id: string;
  document_title: string;
  user_id: string;
  user_login: string;
  skill_id: string;
  skill_name: string;
  skill_version: string;
  provider: Provider;
  model: string;
  status: RunStatus;
  verdict: string | null;
  summary: string | null;
  raw_output: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
};

export type AdminEtalon = {
  id: string;
  document_id: string;
  document_title: string;
  author_id: string;
  author_login: string;
  source: string;
  document_type: DocumentType;
  expected_verdict: string;
  layer_1_count: number;
  layer_2_count: number;
  status: EtalonStatus;
  version: number;
  created_at: string;
  updated_at: string;
};

export type AdminBenchmark = {
  id: string;
  name: string;
  started_by_login: string;
  skill_name: string;
  skill_version: string;
  judge_skill_name: string;
  provider: Provider;
  model: string;
  status: RunStatus;
  overall_score: string | null;
  layer_1_score: string | null;
  layer_2_score: string | null;
  precision: string | null;
  recall: string | null;
  f1: string | null;
  started_at: string | null;
  completed_at: string | null;
};

export type AdminFeedback = {
  id: string;
  user_id: string;
  user_login: string;
  document_id: string;
  document_title: string;
  analysis_id: string;
  analysis_verdict: string | null;
  provider: string;
  model: string;
  skill_id: string;
  skill_version: string;
  rating: number | null;
  usefulness: string;
  verdict_correct: boolean | null;
  has_false_findings: boolean | null;
  has_missed_findings: boolean | null;
  comment: string | null;
  can_use_for_benchmark: boolean;
  processed_at: string | null;
  created_at: string;
};

export type AdminFeedbackSummary = {
  total_count: number;
  scored_count: number;
  average_rating: number | null;
  usefulness_counts: Record<string, number>;
  incorrect_verdict_count: number;
  false_findings_count: number;
  missed_findings_count: number;
  benchmark_candidate_count: number;
  unprocessed_count: number;
  low_rating_count: number;
  legacy_count: number;
};

type QueryValue = string | null | undefined;

function withQuery(path: string, filters: Record<string, QueryValue>): string {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) {
      query.set(key, value);
    }
  });
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export function listAdminDocuments(filters: {
  owner_id?: string;
  document_type?: DocumentType | "";
} = {}) {
  return apiFetch<{ documents: AdminDocument[] }>(withQuery("/admin/documents", filters));
}

export function listAdminAnalyses(filters: {
  provider?: Provider | "";
  model?: string;
  skill_id?: string;
  status?: RunStatus | "";
} = {}) {
  return apiFetch<{ analyses: AdminAnalysis[] }>(withQuery("/admin/analyses", filters));
}

export function listAdminSkills() {
  return apiFetch<{ skills: SkillRecord[] }>("/admin/skills");
}

export function listAdminEtalons(filters: { status?: EtalonStatus | ""; document_type?: DocumentType | "" } = {}) {
  return apiFetch<{ etalons: AdminEtalon[] }>(withQuery("/admin/etalons", filters));
}

export function deleteAdminEtalon(etalonId: string) {
  return apiFetchNoContent(`/admin/etalons/${etalonId}`, { method: "DELETE" });
}

export function listAdminBenchmarks(filters: { provider?: Provider | ""; status?: RunStatus | ""; model?: string } = {}) {
  return apiFetch<{ benchmarks: AdminBenchmark[] }>(withQuery("/admin/benchmarks", filters));
}

export function listAdminFeedback(filters: {
  provider?: Provider | "";
  model?: string;
  verdict?: string;
  skill_id?: string;
  user_id?: string;
  date_from?: string;
  date_to?: string;
  processed_state?: "all" | "processed" | "unprocessed" | "";
} = {}) {
  return apiFetch<{ feedback: AdminFeedback[]; summary: AdminFeedbackSummary }>(withQuery("/admin/feedback", filters));
}

export function markAdminFeedbackProcessed(feedbackId: string) {
  return apiFetch<AdminFeedback>(`/admin/feedback/${feedbackId}/processed`, { method: "PATCH" });
}
