import type {
  AnalysisCheckRunRecord,
  IcReviewCompactResult,
  IcReviewFinding,
  IcReviewKeyNumber,
  IcReviewSpreadsheetAudit,
  IcReviewValidationSummary,
  Provider,
  RunStatus,
} from "@/lib/api/documents";
import type { ProviderModelOptions } from "@/lib/api/provider-settings";

export const IC_REVIEW_EMPTY_STATE = "IC review starts manually after product analysis completes.";

export type IcReviewLaunchAvailability = {
  disabled: boolean;
  reason: string | null;
};

export type IcReviewCompactSection = {
  title: string;
  items: string[];
};

export type IcReviewCompactDisplay = {
  verdict: string;
  executiveBrief: string;
  confidence: string;
  spreadsheetAudit: string;
  validation: string;
  sections: IcReviewCompactSection[];
};

export function getIcReviewLaunchAvailability({
  analysisStatus,
  providerModels,
  provider,
  model,
  isLaunching,
}: {
  analysisStatus: RunStatus;
  providerModels: ProviderModelOptions[];
  provider: Provider;
  model: string;
  isLaunching: boolean;
}): IcReviewLaunchAvailability {
  if (analysisStatus !== "completed") {
    return { disabled: true, reason: IC_REVIEW_EMPTY_STATE };
  }
  if (isLaunching) {
    return { disabled: true, reason: "IC review launch is already in progress." };
  }

  const providerModel = providerModels.find((item) => item.provider === provider);
  if (!providerModel?.has_key) {
    return { disabled: true, reason: "Configure a provider key before launching IC review." };
  }
  if (providerModel.available_models.length === 0) {
    return { disabled: true, reason: "Add at least one model for the selected provider." };
  }
  if (!model.trim()) {
    return { disabled: true, reason: "Select a model before launching IC review." };
  }
  return { disabled: false, reason: null };
}

export function isXlsxFinancialModelFile(fileOrName: { name?: string } | string | null | undefined): boolean {
  const name = typeof fileOrName === "string" ? fileOrName : fileOrName?.name;
  return Boolean(name?.trim().toLowerCase().endsWith(".xlsx"));
}

export function isIcReviewCompactResult(value: unknown): value is IcReviewCompactResult {
  return Boolean(value && typeof value === "object" && (value as { run_mode?: unknown }).run_mode === "ic_agentic_review_compact");
}

export function getIcReviewRunStageText(run: Pick<AnalysisCheckRunRecord, "status" | "current_stage">): string {
  if (run.current_stage?.trim()) {
    return run.current_stage;
  }
  if (run.status === "queued") {
    return "Queued";
  }
  if (run.status === "running") {
    return "Running";
  }
  return run.status;
}

export function getIcReviewSpreadsheetAuditText(audit: IcReviewSpreadsheetAudit | null | undefined): string {
  if (!audit || audit.status === "not_provided") {
    return "Spreadsheet audit not provided";
  }
  if (audit.status === "completed") {
    return audit.summary ? `Spreadsheet audit completed: ${audit.summary}` : "Spreadsheet audit completed";
  }
  return audit.summary ? `Spreadsheet audit failed: ${audit.summary}` : "Spreadsheet audit failed";
}

export function buildIcReviewCompactDisplay(result: IcReviewCompactResult): IcReviewCompactDisplay {
  return {
    verdict: result.verdict,
    executiveBrief: result.executive_brief,
    confidence: `${Math.round(result.confidence * 100)}% confidence`,
    spreadsheetAudit: getIcReviewSpreadsheetAuditText(result.spreadsheet_audit),
    validation: formatValidationSummary(result.validation),
    sections: [
      { title: "Top findings", items: result.top_findings.map(formatFinding) },
      { title: "Key numbers", items: result.key_numbers.map(formatKeyNumber) },
      { title: "Critical risks", items: result.critical_risks },
      { title: "Data gaps", items: result.data_gaps },
      { title: "Required actions", items: result.required_actions },
      { title: "Questions for team", items: result.questions_for_team },
    ],
  };
}

function formatFinding(finding: IcReviewFinding): string {
  return joinSentences([
    `${finding.title} - ${finding.severity}: ${finding.summary}`,
    finding.evidence ? `Evidence: ${finding.evidence}` : "",
    finding.recommendation ? `Recommendation: ${finding.recommendation}` : "",
  ]);
}

function formatKeyNumber(number: IcReviewKeyNumber): string {
  const unit = number.unit ? ` ${number.unit}` : "";
  const source = number.source ? ` (${number.source})` : "";
  return `${number.label}: ${number.value}${unit}${source}`;
}

function formatValidationSummary(validation: IcReviewValidationSummary): string {
  const warningsLabel = validation.warnings_count === 1 ? "warning" : "warnings";
  const failuresLabel = validation.failures_count === 1 ? "failure" : "failures";
  const counts = `${validation.warnings_count} ${warningsLabel}, ${validation.failures_count} ${failuresLabel}`;
  return validation.summary ? `Validation ${validation.status}: ${counts}. ${validation.summary}` : `Validation ${validation.status}: ${counts}`;
}

function joinSentences(parts: string[]): string {
  return parts
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => (/[.!?]$/.test(part) ? part : `${part}.`))
    .join(" ");
}
