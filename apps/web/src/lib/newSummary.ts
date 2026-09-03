export type NewSummaryLanguage = "ru" | "en";

export type NewSummaryStage =
  | "Gate 1"
  | "Gate 2"
  | "Gate 3"
  | "Progress Review"
  | "Stream Review 1"
  | "Stream Review 2+"
  | "Stream Review 2+ / Progress Review";

export type NewSummaryRequiredElement = {
  id: string;
  label: string;
  status: "есть" | "нет" | "present" | "missing";
  evidence: string;
};

export type NewSummaryTractionSummary = {
  metric_label: string;
  periods: string[];
  rows: Array<{
    label: string;
    values: string[];
  }>;
};

export type NewSummaryRequiredDetails =
  | {
      type: "solution_validation";
      items: Array<{ text: string; verdict: "confirmed" | "insufficient" }>;
    }
  | {
      type: "metric_binding";
      input_metrics: Array<{ metric: string; binding: "confirmed" | "insufficient"; evidence: string }>;
      output_metrics: Array<{ metric: string; binding: "confirmed" | "insufficient"; evidence: string }>;
    }
  | {
      type: "next_review_plan";
      outputs_until_next_review: string[];
      metrics_until_next_review: Array<{ metric: string; current: string; next_review: string }>;
    }
  | {
      type: "stop_criteria";
      criteria: string[];
    };

export type NewSummaryRequiredDetailsById = Record<string, NewSummaryRequiredDetails>;

export type NewSummaryContent = {
  schema_version: "new-summary-v1";
  language: NewSummaryLanguage;
  title: string;
  stage: NewSummaryStage;
  traction_summary?: NewSummaryTractionSummary;
  context: string;
  required_elements: NewSummaryRequiredElement[];
  required_details?: NewSummaryRequiredDetailsById;
  confirmed: string[];
  insufficiently_confirmed: string[];
  critical_problems: string[];
  other: string[];
};

export type NewSummaryReport = {
  analysis_id: string;
  created_at?: string | null;
  pdf_path?: string | null;
  route?: string | null;
  ru: NewSummaryContent;
  en: NewSummaryContent;
};
