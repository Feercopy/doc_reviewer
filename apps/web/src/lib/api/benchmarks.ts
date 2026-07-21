import { apiFetch } from "./client";
import type { Provider, RunStatus } from "./documents";

export type BenchmarkRecord = {
  id: string;
  name: string;
  description: string;
  etalon_ids: string[];
  skill_id: string;
  skill_version: string;
  judge_skill_id: string;
  provider: Provider;
  model: string;
  status: RunStatus;
  started_by_id: string;
  started_at: string | null;
  completed_at: string | null;
  overall_score: string | null;
  layer_1_score: string | null;
  layer_2_score: string | null;
  precision: string | null;
  recall: string | null;
  f1: string | null;
  missed_findings: unknown[] | null;
  false_positives: unknown[] | null;
  partial_matches: unknown[] | null;
  judge_output: Record<string, unknown> | null;
  report: Record<string, unknown> | null;
  run_parameters: Record<string, unknown>;
  error_message: string | null;
};

export type BenchmarkCreatePayload = {
  name: string;
  description: string;
  etalon_ids: string[];
  skill_id: string;
  provider: Provider;
  model: string;
  judge_skill_id: string;
  evaluation_mode: string;
  run_parameters: Record<string, unknown>;
};

export async function listBenchmarks(): Promise<{ benchmarks: BenchmarkRecord[] }> {
  return apiFetch<{ benchmarks: BenchmarkRecord[] }>("/benchmarks");
}

export async function createBenchmark(payload: BenchmarkCreatePayload): Promise<BenchmarkRecord> {
  return apiFetch<BenchmarkRecord>("/benchmarks", { method: "POST", body: JSON.stringify(payload) });
}

export async function getBenchmark(benchmarkId: string): Promise<BenchmarkRecord> {
  return apiFetch<BenchmarkRecord>(`/benchmarks/${benchmarkId}`);
}

export async function getBenchmarkReport(benchmarkId: string): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/benchmarks/${benchmarkId}/report`);
}

export async function cancelBenchmark(benchmarkId: string): Promise<BenchmarkRecord> {
  return apiFetch<BenchmarkRecord>(`/benchmarks/${benchmarkId}/cancel`, { method: "POST" });
}
