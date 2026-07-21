import { apiFetch, resolveApiBaseUrl } from "./client";
import type {
  AnalysisCheckRunRecord,
  AnalysisCheckRunsListResponse,
  OutputLanguage,
  Provider,
} from "./documents";

export type IcReviewRunCreatePayload = {
  provider: Provider;
  model: string;
  output_language: OutputLanguage;
  financial_model?: File;
};

export async function createIcReviewRun(
  analysisId: string,
  payload: IcReviewRunCreatePayload,
): Promise<AnalysisCheckRunRecord> {
  const form = new FormData();
  form.set("provider", payload.provider);
  form.set("model", payload.model);
  form.set("output_language", payload.output_language);
  if (payload.financial_model) {
    form.set("financial_model", payload.financial_model);
  }

  return apiFetch<AnalysisCheckRunRecord>(`/analyses/${analysisId}/ic-review-runs`, {
    method: "POST",
    body: form,
  });
}

export async function getIcReviewRun(runId: string): Promise<AnalysisCheckRunRecord> {
  return apiFetch<AnalysisCheckRunRecord>(`/ic-review-runs/${runId}`);
}

export async function listIcReviewRuns(analysisId: string): Promise<AnalysisCheckRunsListResponse> {
  return apiFetch<AnalysisCheckRunsListResponse>(`/analyses/${analysisId}/ic-review-runs`);
}

export async function getLatestIcReviewRun(analysisId: string): Promise<AnalysisCheckRunRecord> {
  return apiFetch<AnalysisCheckRunRecord>(`/analyses/${analysisId}/ic-review-runs/latest`);
}

export function icReviewArtifactUrl(runId: string, artifactKey: string): string {
  return `${resolveApiBaseUrl()}/ic-review-runs/${runId}/artifacts/${encodeURIComponent(artifactKey)}`;
}
