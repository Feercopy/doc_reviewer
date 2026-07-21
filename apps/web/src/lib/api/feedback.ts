import { apiFetch } from "./client";

export type FeedbackPayload = {
  usefulness?: "useful" | "partially_useful" | "useless";
  rating?: number | null;
  verdict_correct?: boolean | null;
  has_false_findings?: boolean | null;
  has_missed_findings?: boolean | null;
  comment?: string | null;
  can_use_for_benchmark: boolean;
};

export async function submitFeedback(analysisId: string, payload: FeedbackPayload): Promise<{ id: string }> {
  return apiFetch<{ id: string }>(`/analyses/${analysisId}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
