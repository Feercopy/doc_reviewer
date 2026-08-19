export type NewSummaryLanguage = "ru" | "en";

export type NewSummaryStage =
  | "Gate 1"
  | "Gate 2"
  | "Gate 3"
  | "Stream Review 1"
  | "Stream Review 2+ / Progress Review";

export type NewSummaryRequiredElement = {
  id: string;
  label: string;
  status: "present" | "missing";
  evidence: string;
};

export type NewSummaryContent = {
  schema_version: "new-summary-v1";
  language: NewSummaryLanguage;
  title: string;
  stage: NewSummaryStage;
  context: string;
  required_elements: NewSummaryRequiredElement[];
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
