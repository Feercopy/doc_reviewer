import { apiFetch } from "./client";
import type { DocumentType } from "./documents";

export type EtalonStatus = "draft" | "active" | "archived" | "deleted";
export type Verdict = "approve" | "approve_with_conditions" | "need_evidence" | "reject" | "unknown";
export type CheckStatus = "pass" | "partial" | "fail" | "not_applicable";
export type Severity = "low" | "medium" | "high" | "critical";

export type EtalonEvidence = {
  quote: string;
  location: string;
};

export type EtalonLayer1Item = {
  id: string;
  dimension: string;
  status: CheckStatus;
  severity: Severity;
  title: string;
  summary: string;
  evidence: EtalonEvidence[];
  recommendation: string;
  confidence: number | null;
};

export type EtalonLayer2Item = {
  id: string;
  parent_layer_1_id: string;
  check: string;
  status: CheckStatus;
  severity: Severity;
  finding: string;
  evidence: EtalonEvidence[];
  expected_fix: string;
  confidence: number | null;
};

export type EtalonRecord = {
  id: string;
  document_id: string;
  author_id: string;
  source: "manual" | "ai_post_annotation" | "imported_defense" | "gate2_benchmark";
  source_metadata: Record<string, unknown>;
  document_type: DocumentType;
  real_defense_status: string | null;
  defense_comments: string | null;
  expected_verdict: Verdict;
  layer_1: EtalonLayer1Item[];
  layer_2: EtalonLayer2Item[];
  key_findings: string[];
  forbidden_false_findings: string[];
  status: EtalonStatus;
  version: number;
  raw_file_visible_to_all: boolean;
  created_at: string;
  updated_at: string;
};

export type Gate2BenchmarkImportRequest = {
  benchmark_dir?: string | null;
  activate?: boolean;
};

export type Gate2BenchmarkImportResponse = {
  imported_count: number;
  skipped_count: number;
  parse_enqueued_count: number;
  etalons: EtalonRecord[];
};

export type EtalonUpdatePayload = Partial<{
  expected_verdict: Verdict;
  layer_1: EtalonLayer1Item[];
  layer_2: EtalonLayer2Item[];
  key_findings: string[];
  forbidden_false_findings: string[];
  real_defense_status: string | null;
  defense_comments: string | null;
  raw_file_visible_to_all: boolean;
}>;

export async function listEtalons(): Promise<{ etalons: EtalonRecord[] }> {
  return apiFetch<{ etalons: EtalonRecord[] }>("/etalons");
}

export async function getEtalon(etalonId: string): Promise<EtalonRecord> {
  return apiFetch<EtalonRecord>(`/etalons/${etalonId}`);
}

export async function getAnnotationQueue(): Promise<{ etalons: EtalonRecord[] }> {
  return apiFetch<{ etalons: EtalonRecord[] }>("/annotation/queue");
}

export async function createEtalonDraft(analysisId: string): Promise<EtalonRecord> {
  return apiFetch<EtalonRecord>(`/analyses/${analysisId}/etalon-draft`, { method: "POST" });
}

export async function importPastDefense(form: FormData): Promise<EtalonRecord> {
  return apiFetch<EtalonRecord>("/documents/past-defense", { method: "POST", body: form });
}

export async function importGate2Benchmark(payload: Gate2BenchmarkImportRequest): Promise<Gate2BenchmarkImportResponse> {
  return apiFetch<Gate2BenchmarkImportResponse>("/etalons/import/gate2-benchmark", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateEtalon(etalonId: string, payload: EtalonUpdatePayload): Promise<EtalonRecord> {
  return apiFetch<EtalonRecord>(`/etalons/${etalonId}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export async function publishEtalon(etalonId: string): Promise<EtalonRecord> {
  return apiFetch<EtalonRecord>(`/etalons/${etalonId}/publish`, { method: "POST" });
}

export async function archiveEtalon(etalonId: string): Promise<EtalonRecord> {
  return apiFetch<EtalonRecord>(`/etalons/${etalonId}/archive`, { method: "POST" });
}
