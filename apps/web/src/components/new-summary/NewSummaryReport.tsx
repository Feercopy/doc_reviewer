"use client";

import { useState } from "react";

import type {
  NewSummaryContent,
  NewSummaryLanguage,
  NewSummaryReport,
  NewSummaryRequiredDetails,
  NewSummaryRequiredElement,
  NewSummaryTractionSummary,
} from "@/lib/newSummary";

const labels = {
  ru: {
    appendices: "Appendices",
    bindingConfirmed: "Связь подтверждена",
    bindingInsufficient: "Связь недостаточно подтверждена",
    context: "Краткий контекст инициативы",
    critical: "Выявленные проблемы",
    confirmed: "Что подтверждено",
    download: "Скачать PDF на русском и английском",
    insufficient: "Что недостаточно подтверждено",
    inputMetrics: "Input metrics",
    list: "Все новые Summary",
    metric: "Метрика",
    missing: "Нет",
    nextReview: "Значение к следующему ревью",
    other: "Другие наблюдения",
    outputMetrics: "Output metrics",
    present: "Есть",
    prototype: "AI Summary · скилл new-summary",
    required: "Обязательные элементы документа",
    requiredIntro:
      "Проверяется только наличие обязательных частей соответствующей стадии. Качество доказательств оценивается в следующих разделах.",
    source: "Исходный анализ",
    stage: "Стадия инициативы",
    traction: "Traction Summary",
  },
  en: {
    appendices: "Appendices",
    bindingConfirmed: "Binding confirmed",
    bindingInsufficient: "Binding not sufficiently confirmed",
    context: "Initiative context",
    critical: "Identified problems",
    confirmed: "What is confirmed",
    download: "Download the Russian and English PDF",
    insufficient: "What is not sufficiently confirmed",
    inputMetrics: "Input metrics",
    list: "All New Summaries",
    metric: "Metric",
    missing: "Missing",
    nextReview: "Next review value",
    other: "Other observations",
    outputMetrics: "Output metrics",
    present: "Present",
    prototype: "AI Summary · new-summary skill",
    required: "Required document elements",
    requiredIntro:
      "This block checks only whether the stage-required elements are present. Evidence quality is assessed in the sections below.",
    source: "Source analysis",
    stage: "Initiative stage",
    traction: "Traction Summary",
  },
} as const;

export function NewSummaryReportView({
  embedded = false,
  report,
}: {
  embedded?: boolean;
  report: NewSummaryReport;
}) {
  const [language, setLanguage] = useState<NewSummaryLanguage>("ru");
  const content = report[language];
  const text = labels[language];
  const sourceUrl = `https://iseremenko.ru/doc-challanger/analyses/${report.analysis_id}`;
  const ShellTag = embedded ? "section" : "main";

  return (
    <ShellTag className={embedded ? "new-summary-shell new-summary-shell--embedded" : "new-summary-shell"}>
      <style>{newSummaryStyles}</style>

      <div className="new-summary-toolbar">
        {report.route ? (
          <a className="new-summary-list-link" href={report.route}>
            {text.list}
          </a>
        ) : (
          <span aria-hidden="true" />
        )}
        <div className="new-summary-toolbar__actions">
          <div className="new-summary-language-switch" aria-label="Summary language">
            <button
              aria-pressed={language === "ru"}
              className={language === "ru" ? "active" : ""}
              type="button"
              onClick={() => setLanguage("ru")}
            >
              РУС
            </button>
            <button
              aria-pressed={language === "en"}
              className={language === "en" ? "active" : ""}
              type="button"
              onClick={() => setLanguage("en")}
            >
              ENG
            </button>
          </div>
          {report.pdf_path ? (
            <a className="new-summary-download" download href={report.pdf_path}>
              {text.download}
            </a>
          ) : null}
        </div>
      </div>

      <header className="new-summary-header">
        <p>{text.prototype}</p>
        <h1>{content.title}</h1>
        <div className="new-summary-stage">
          <span>{text.stage}</span>
          <strong>{content.stage}</strong>
        </div>
      </header>

      <TractionSummaryTable content={content} labels={text} />

      <section className="new-summary-panel new-summary-context">
        <h2>{text.context}</h2>
        <p>{content.context}</p>
      </section>

      <section className="new-summary-panel new-summary-required">
        <div className="new-summary-section-heading">
          <h2>{text.required}</h2>
          <p>{text.requiredIntro}</p>
        </div>
        <ul>
          {content.required_elements.map((item) => {
            const tone = requiredElementTone(item);
            return (
              <li className={tone} key={item.id}>
                <span className="new-summary-required__marker" aria-hidden="true" />
                <div>
                  <div className="new-summary-required__title">
                    <strong>{item.label}</strong>
                    <span>{tone === "present" ? text.present : text.missing}</span>
                  </div>
                  <p>{item.evidence}</p>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="new-summary-panel new-summary-evidence-grid">
        <SummarySection className="confirmed" items={content.confirmed} title={text.confirmed} />
        <SummarySection
          className="insufficient"
          items={content.insufficiently_confirmed}
          title={text.insufficient}
        />
      </section>

      <section className="new-summary-panel new-summary-critical">
        <SummarySection className="critical" items={content.critical_problems} title={text.critical} />
      </section>

      {content.other.length ? (
        <section className="new-summary-panel new-summary-other">
          <SummarySection items={content.other} title={text.other} />
        </section>
      ) : null}

      <RequiredDetailsPanel content={content} labels={text} />

      {!embedded ? (
        <footer className="new-summary-source">
          <span>{text.source}:</span>
          <a href={sourceUrl} target="_blank" rel="noreferrer">
            {report.analysis_id}
          </a>
        </footer>
      ) : null}
    </ShellTag>
  );
}

function TractionSummaryTable({
  content,
  labels: text,
}: {
  content: NewSummaryContent;
  labels: (typeof labels)[NewSummaryLanguage];
}) {
  const traction = content.traction_summary;
  if (!hasTractionSummary(traction)) {
    return null;
  }

  return (
    <section className="new-summary-panel new-summary-traction">
      <h2>{text.traction}</h2>
      <div className="new-summary-table-scroll">
        <table>
          <thead>
            <tr>
              <th>{traction.metric_label}</th>
              {traction.periods.map((period) => (
                <th key={period}>{period}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {traction.rows.map((row) => (
              <tr key={row.label}>
                <th>{row.label}</th>
                {traction.periods.map((period, index) => (
                  <td key={`${row.label}-${period}`}>{row.values[index] ?? ""}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SummarySection({
  className = "",
  items,
  title,
}: {
  className?: string;
  items: string[];
  title: string;
}) {
  if (!items.length) {
    return null;
  }

  return (
    <section className={`new-summary-list-section ${className}`.trim()}>
      <h2>{title}</h2>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function RequiredDetailsPanel({
  content,
  labels: text,
}: {
  content: NewSummaryContent;
  labels: (typeof labels)[NewSummaryLanguage];
}) {
  const entries = orderedRequiredDetails(content);
  if (!entries.length) {
    return null;
  }

  return (
    <section className="new-summary-panel new-summary-appendices">
      <h2>{text.appendices}</h2>
      <div className="new-summary-appendices__items">
        {entries.map(([id, detail], index) => (
          <article className="new-summary-appendix" id={`appendix-${id}`} key={id}>
            <h3>{appendixTitle(content, id, index)}</h3>
            <RequiredDetailContent detail={detail} labels={text} />
          </article>
        ))}
      </div>
    </section>
  );
}

function RequiredDetailContent({
  detail,
  labels: text,
}: {
  detail: NewSummaryRequiredDetails;
  labels: (typeof labels)[NewSummaryLanguage];
}) {
  if (detail.type === "solution_validation") {
    return (
      <ul className="new-summary-appendix-list">
        {detail.items.map((item) => (
          <li key={item.text}>
            <span>{item.text}</span>
            <StatusChip status={item.verdict} labels={text} />
          </li>
        ))}
      </ul>
    );
  }

  if (detail.type === "metric_binding") {
    return (
      <div className="new-summary-metric-binding">
        <MetricBindingGroup items={detail.input_metrics} labels={text} title={text.inputMetrics} />
        <MetricBindingGroup items={detail.output_metrics} labels={text} title={text.outputMetrics} />
      </div>
    );
  }

  if (detail.type === "next_review_plan") {
    return (
      <div className="new-summary-plan-detail">
        <ul className="new-summary-appendix-list">
          {detail.outputs_until_next_review.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <div className="new-summary-table-scroll">
          <table>
            <thead>
              <tr>
                <th>{text.metric}</th>
                <th>Current</th>
                <th>{text.nextReview}</th>
              </tr>
            </thead>
            <tbody>
              {detail.metrics_until_next_review.map((row) => (
                <tr key={`${row.metric}-${row.current}-${row.next_review}`}>
                  <th>{row.metric}</th>
                  <td>{row.current}</td>
                  <td>{row.next_review}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <ul className="new-summary-appendix-list">
      {detail.criteria.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function MetricBindingGroup({
  items,
  labels: text,
  title,
}: {
  items: Array<{ metric: string; binding: "confirmed" | "insufficient"; evidence: string }>;
  labels: (typeof labels)[NewSummaryLanguage];
  title: string;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <div>
      <h4>{title}</h4>
      <ul className="new-summary-appendix-list">
        {items.map((item) => (
          <li key={`${item.metric}-${item.evidence}`}>
            <span>
              <strong>{item.metric}</strong>
              {item.evidence ? ` - ${item.evidence}` : ""}
            </span>
            <StatusChip status={item.binding} labels={text} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusChip({
  labels: text,
  status,
}: {
  labels: (typeof labels)[NewSummaryLanguage];
  status: "confirmed" | "insufficient";
}) {
  const confirmed = status === "confirmed";
  return (
    <span className={confirmed ? "new-summary-status-chip confirmed" : "new-summary-status-chip insufficient"}>
      {confirmed ? text.bindingConfirmed : text.bindingInsufficient}
    </span>
  );
}

function hasTractionSummary(value: NewSummaryTractionSummary | undefined): value is NewSummaryTractionSummary {
  return Boolean(value?.periods.length && value.rows.length);
}

function requiredElementTone(item: NewSummaryRequiredElement): "present" | "missing" {
  return item.status === "present" || item.status === "есть" ? "present" : "missing";
}

function orderedRequiredDetails(content: NewSummaryContent): Array<[string, NewSummaryRequiredDetails]> {
  const details = content.required_details;
  if (!details) {
    return [];
  }
  const ids = new Set(content.required_elements.map((item) => item.id));
  const orderedIds = [
    ...content.required_elements.map((item) => item.id),
    ...Object.keys(details).filter((id) => !ids.has(id)).sort(),
  ];
  return orderedIds
    .map((id) => [id, details[id]] as [string, NewSummaryRequiredDetails | undefined])
    .filter((entry): entry is [string, NewSummaryRequiredDetails] => Boolean(entry[1]));
}

function appendixTitle(content: NewSummaryContent, id: string, index: number): string {
  const element = content.required_elements.find((item) => item.id === id);
  return element?.label ? `Appendix ${index + 1}. ${element.label}` : `Appendix ${index + 1}`;
}

const newSummaryStyles = `
.new-summary-shell {
  display: grid;
  width: min(1240px, 100%);
  gap: 16px;
  margin: 0 auto;
  padding: 18px 24px 40px;
}

.new-summary-shell--embedded {
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 0;
}

.new-summary-toolbar {
  display: flex;
  min-height: 40px;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.new-summary-toolbar__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.new-summary-list-link {
  color: var(--accent-strong);
  font-size: 13px;
  font-weight: 750;
}

.new-summary-language-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, 54px);
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
}

.new-summary-language-switch button {
  min-height: 36px;
  border: 0;
  border-radius: 0;
  background: var(--panel);
  color: var(--muted-strong);
  font-size: 12px;
  font-weight: 850;
}

.new-summary-language-switch button + button { border-left: 1px solid var(--line-strong); }
.new-summary-language-switch button.active { background: var(--accent-strong); color: #fff; }

.new-summary-download {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  border-radius: 6px;
  background: var(--success);
  color: #fff;
  padding: 0 13px;
  font-size: 12px;
  font-weight: 800;
  text-decoration: none;
}

.new-summary-header {
  display: grid;
  gap: 7px;
  padding: 8px 2px 2px;
}

.new-summary-header > p {
  margin: 0;
  color: var(--accent-strong);
  font-size: 11px;
  font-weight: 850;
  text-transform: uppercase;
}

.new-summary-header h1 {
  margin: 0;
  font-size: 32px;
  line-height: 1.12;
  overflow-wrap: anywhere;
}

.new-summary-stage {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  color: var(--muted-strong);
  font-size: 15px;
  font-weight: 650;
}

.new-summary-stage strong {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  border-radius: 999px;
  background: var(--info-bg);
  color: var(--info);
  padding: 0 14px;
  font-size: 14px;
  font-weight: 850;
  text-transform: uppercase;
}

.new-summary-panel {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--panel);
}

.new-summary-context,
.new-summary-traction,
.new-summary-appendices { padding: 20px 22px; }

.new-summary-context h2,
.new-summary-traction h2,
.new-summary-appendices h2,
.new-summary-section-heading h2,
.new-summary-list-section h2 {
  margin: 0;
  color: var(--foreground);
  font-size: 17px;
  line-height: 1.3;
}

.new-summary-context p {
  max-width: 110ch;
  margin: 9px 0 0;
  color: var(--muted-strong);
  line-height: 1.65;
}

.new-summary-table-scroll {
  width: 100%;
  overflow-x: auto;
}

.new-summary-table-scroll table {
  width: 100%;
  min-width: 560px;
  margin-top: 14px;
  border-collapse: collapse;
  font-size: 13px;
}

.new-summary-table-scroll th,
.new-summary-table-scroll td {
  border: 1px solid var(--line);
  padding: 10px 11px;
  text-align: left;
  vertical-align: top;
}

.new-summary-table-scroll th {
  background: var(--surface);
  color: var(--foreground);
  font-weight: 800;
}

.new-summary-table-scroll td {
  color: var(--muted-strong);
}

.new-summary-section-heading {
  display: grid;
  gap: 7px;
  padding: 20px 22px 16px;
}

.new-summary-section-heading p {
  max-width: 88ch;
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.new-summary-required > ul {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.new-summary-required > ul > li {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  gap: 12px;
  border-top: 1px solid var(--line);
  padding: 15px 22px;
}

.new-summary-required__marker {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 999px;
  background: var(--warning);
}

.new-summary-required li.present .new-summary-required__marker { background: var(--success); }

.new-summary-required__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px 10px;
}

.new-summary-required__title strong {
  color: var(--foreground);
  font-size: 14px;
  line-height: 1.4;
}

.new-summary-required__title span {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  border-radius: 999px;
  background: var(--warning-bg);
  color: #925c00;
  padding: 0 8px;
  font-size: 11px;
  font-weight: 800;
}

.new-summary-required li.present .new-summary-required__title span {
  background: var(--success-bg);
  color: #075e45;
}

.new-summary-required p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.new-summary-evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  overflow: hidden;
}

.new-summary-evidence-grid .new-summary-list-section {
  min-width: 0;
  padding: 20px 22px 22px;
}

.new-summary-evidence-grid .new-summary-list-section + .new-summary-list-section {
  border-left: 1px solid var(--line);
}

.new-summary-critical,
.new-summary-other { padding: 20px 22px 22px; }

.new-summary-list-section h2 {
  position: relative;
  padding-left: 15px;
}

.new-summary-list-section h2::before {
  position: absolute;
  top: 4px;
  bottom: 3px;
  left: 0;
  width: 4px;
  border-radius: 2px;
  background: var(--line-strong);
  content: "";
}

.new-summary-list-section.confirmed h2::before { background: var(--success); }
.new-summary-list-section.insufficient h2::before { background: var(--warning); }
.new-summary-list-section.critical h2::before { background: var(--danger); }

.new-summary-list-section ul {
  display: grid;
  gap: 10px;
  margin: 14px 0 0;
  padding-left: 19px;
}

.new-summary-list-section li {
  color: var(--muted-strong);
  line-height: 1.55;
  padding-left: 3px;
}

.new-summary-list-section li::marker { color: var(--muted); font-weight: 800; }

.new-summary-appendices__items {
  display: grid;
  gap: 16px;
  margin-top: 14px;
}

.new-summary-appendix {
  border-top: 1px solid var(--line);
  padding-top: 16px;
}

.new-summary-appendix h3,
.new-summary-metric-binding h4 {
  margin: 0 0 10px;
  color: var(--foreground);
  font-size: 15px;
  line-height: 1.35;
}

.new-summary-metric-binding {
  display: grid;
  gap: 16px;
}

.new-summary-appendix-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding-left: 19px;
}

.new-summary-appendix-list li {
  color: var(--muted-strong);
  line-height: 1.55;
  padding-left: 3px;
}

.new-summary-status-chip {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  margin-left: 8px;
  border-radius: 999px;
  padding: 0 8px;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
}

.new-summary-status-chip.confirmed {
  background: var(--success-bg);
  color: #075e45;
}

.new-summary-status-chip.insufficient {
  background: var(--warning-bg);
  color: #925c00;
}

.new-summary-source {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 2px;
  color: var(--muted);
  font-size: 12px;
}

.new-summary-source a { color: var(--accent-strong); overflow-wrap: anywhere; }

@media (max-width: 760px) {
  .new-summary-shell { padding: 18px 16px 32px; }
  .new-summary-toolbar { align-items: flex-start; flex-direction: column; }
  .new-summary-toolbar__actions { justify-content: flex-start; }
  .new-summary-evidence-grid { grid-template-columns: 1fr; }
  .new-summary-evidence-grid .new-summary-list-section + .new-summary-list-section {
    border-top: 1px solid var(--line);
    border-left: 0;
  }
}

@media (max-width: 640px) {
  .new-summary-toolbar__actions { align-items: stretch; flex-direction: column; width: 100%; }
  .new-summary-language-switch { align-self: flex-start; }
  .new-summary-download { justify-content: center; text-align: center; }
  .new-summary-header h1 { font-size: 27px; }
  .new-summary-stage { align-items: flex-start; flex-direction: column; }
  .new-summary-context,
  .new-summary-traction,
  .new-summary-appendices,
  .new-summary-section-heading,
  .new-summary-evidence-grid .new-summary-list-section,
  .new-summary-critical,
  .new-summary-other,
  .new-summary-required > ul > li {
    padding-right: 16px;
    padding-left: 16px;
  }
}
`;
