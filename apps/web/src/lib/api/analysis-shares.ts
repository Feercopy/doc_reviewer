import { apiFetch, apiFetchNoContent, resolveApiBaseUrl } from "./client";
import type { NewSummaryContent } from "../newSummary";

export type SharedFinancial = {
  executive_brief: string;
  top_findings: Array<{ title: string; severity: string; summary: string; evidence: string; recommendation: string }>;
  key_numbers: Array<{ label: string; value: string; unit: string; source: string }>;
  spreadsheet_audit: { status: string; summary: string };
  validation: { status: string; summary: string; warnings_count: number; failures_count: number };
  critical_risks: string[];
  data_gaps: string[];
  required_actions: string[];
};

export type SharedAnalysis = {
  id: string;
  title: string;
  status: string;
  processing: boolean;
  created_at: string;
  product_markdown: string | null;
  summary_ru: NewSummaryContent | null;
  summary_en: NewSummaryContent | null;
  financial: SharedFinancial | null;
};

export class SharedAnalysisLinkUnavailableError extends Error {}

export async function createAnalysisShare(analysisId: string): Promise<string> {
  const result = await apiFetch<{ token: string }>(`/analyses/${analysisId}/share`, { method: "POST" });
  return result.token;
}

export async function getAnalysisShareStatus(analysisId: string): Promise<boolean> {
  const result = await apiFetch<{ active: boolean }>(`/analyses/${analysisId}/share`);
  return result.active;
}

export async function revokeAnalysisShare(analysisId: string): Promise<void> {
  await apiFetchNoContent(`/analyses/${analysisId}/share`, { method: "DELETE" });
}

export async function getSharedAnalysis(analysisId: string, token: string): Promise<SharedAnalysis> {
  const response = await fetch(`${resolveApiBaseUrl()}/public/analyses/${analysisId}`, {
    credentials: "omit",
    cache: "no-store",
    headers: { "X-Analysis-Share-Token": token },
  });
  if (response.status === 403 || response.status === 404) {
    throw new SharedAnalysisLinkUnavailableError("Ссылка недоступна или доступ по ней был отключён.");
  }
  if (!response.ok) throw new Error("Не удалось обновить результаты. Повторяем попытку…");
  return response.json() as Promise<SharedAnalysis>;
}
