import type { AnalysisRecord } from "@/lib/api/documents";

export type FinalVerdict = "Rejected" | "Need Evidence" | "Approved";
export type FinalVerdictTone = "bad" | "warn" | "good";

export type RankedVerdict = {
  label: FinalVerdict;
  rank: number;
  tone: FinalVerdictTone;
};

export type AgentVerdictRow = {
  label: string;
  verdict: RankedVerdict;
};

const REJECTED: RankedVerdict = { label: "Rejected", rank: 0, tone: "bad" };
const NEED_EVIDENCE: RankedVerdict = { label: "Need Evidence", rank: 1, tone: "warn" };
const APPROVED: RankedVerdict = { label: "Approved", rank: 2, tone: "good" };

export function buildFinalVerdict(analysis: Pick<AnalysisRecord, "verdict" | "ic_review_run">): RankedVerdict {
  const verdicts = [
    verdictFromGateChallenger(analysis.verdict),
    verdictFromIcReview(analysis.ic_review_run?.structured_output),
  ].filter((verdict): verdict is RankedVerdict => Boolean(verdict));

  return verdicts.reduce(
    (strictest, verdict) => (verdict.rank < strictest.rank ? verdict : strictest),
    verdicts[0] ?? NEED_EVIDENCE,
  );
}

export function buildAgentVerdicts(analysis: Pick<AnalysisRecord, "verdict" | "ic_review_run">): AgentVerdictRow[] {
  return [
    {
      label: "Продуктовый анализ",
      verdict: verdictFromGateChallenger(analysis.verdict) ?? NEED_EVIDENCE,
    },
    {
      label: "Финансовый анализ",
      verdict: verdictFromIcReview(analysis.ic_review_run?.structured_output) ?? NEED_EVIDENCE,
    },
  ];
}

export function verdictFromGateChallenger(value: string | null | undefined): RankedVerdict | null {
  const normalized = normalizeVerdictToken(value);
  if (!normalized) {
    return null;
  }
  if (["approve", "approved", "pass", "yes"].includes(normalized)) {
    return APPROVED;
  }
  if (
    [
      "approvewithconditions",
      "conditionalapprove",
      "conditionalapproval",
      "conditional",
      "partial",
      "needevidence",
      "needs_evidence",
      "medium",
      "important",
    ].includes(normalized)
  ) {
    return NEED_EVIDENCE;
  }
  if (["reject", "rejected", "rework", "fail", "failed", "critical", "high", "no", "nogo", "freeze"].includes(normalized)) {
    return REJECTED;
  }
  return NEED_EVIDENCE;
}

export function verdictFromIcReview(value: unknown): RankedVerdict | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const verdict = (value as { verdict?: unknown }).verdict;
  if (typeof verdict !== "string") {
    return null;
  }
  switch (verdict.trim().toUpperCase()) {
    case "GO":
      return APPROVED;
    case "CONDITIONAL":
    case "UNKNOWN":
      return NEED_EVIDENCE;
    case "NO-GO":
    case "FREEZE":
      return REJECTED;
    default:
      return NEED_EVIDENCE;
  }
}

function normalizeVerdictToken(value: string | null | undefined): string | null {
  if (!value?.trim()) {
    return null;
  }
  return value.trim().toLowerCase().replace(/[\s_-]+/g, "");
}
