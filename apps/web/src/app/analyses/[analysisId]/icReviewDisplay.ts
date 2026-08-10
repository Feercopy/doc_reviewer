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

export function getIcReviewSpreadsheetAuditText(
  audit: IcReviewSpreadsheetAudit | null | undefined,
  language: "ru" | "en" = "en",
): string {
  const labels = language === "ru"
    ? { notProvided: "Проверка таблицы не проводилась", completed: "Проверка таблицы завершена", failed: "Проверка таблицы завершилась ошибкой" }
    : { notProvided: "Spreadsheet audit not provided", completed: "Spreadsheet audit completed", failed: "Spreadsheet audit failed" };
  if (!audit || audit.status === "not_provided") {
    return labels.notProvided;
  }
  if (audit.status === "completed") {
    return audit.summary ? `${labels.completed}: ${audit.summary}` : labels.completed;
  }
  return audit.summary ? `${labels.failed}: ${audit.summary}` : labels.failed;
}

export function buildIcReviewCompactDisplay(result: IcReviewCompactResult, language: "ru" | "en" = "en"): IcReviewCompactDisplay {
  const labels = language === "ru"
    ? ["Ключевые выводы", "Ключевые цифры", "Критические риски", "Пробелы в данных", "Обязательные действия", "Вопросы команде"]
    : ["Top findings", "Key numbers", "Critical risks", "Data gaps", "Required actions", "Questions for team"];
  return {
    verdict: result.verdict,
    executiveBrief: result.executive_brief,
    confidence: language === "ru" ? `Уверенность ${Math.round(result.confidence * 100)}%` : `${Math.round(result.confidence * 100)}% confidence`,
    spreadsheetAudit: getIcReviewSpreadsheetAuditText(result.spreadsheet_audit, language),
    validation: formatValidationSummary(result.validation, language),
    sections: [
      { title: labels[0], items: result.top_findings.map((finding) => formatFinding(finding, language)) },
      { title: labels[1], items: result.key_numbers.map(formatKeyNumber) },
      { title: labels[2], items: result.critical_risks },
      { title: labels[3], items: result.data_gaps },
      { title: labels[4], items: result.required_actions },
      { title: labels[5], items: result.questions_for_team },
    ],
  };
}

function formatFinding(finding: IcReviewFinding, language: "ru" | "en"): string {
  return joinSentences([
    `${finding.title} - ${finding.severity}: ${finding.summary}`,
    finding.evidence ? `${language === "ru" ? "Подтверждение" : "Evidence"}: ${finding.evidence}` : "",
    finding.recommendation ? `${language === "ru" ? "Рекомендация" : "Recommendation"}: ${finding.recommendation}` : "",
  ]);
}

function formatKeyNumber(number: IcReviewKeyNumber): string {
  const unit = number.unit ? ` ${number.unit}` : "";
  const source = number.source ? ` (${number.source})` : "";
  return `${number.label}: ${number.value}${unit}${source}`;
}

function formatValidationSummary(validation: IcReviewValidationSummary, language: "ru" | "en"): string {
  if (language === "ru") {
    const counts = `${validation.warnings_count} предупреждений, ${validation.failures_count} ошибок`;
    return validation.summary ? `Валидация ${validation.status}: ${counts}. ${validation.summary}` : `Валидация ${validation.status}: ${counts}`;
  }
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
