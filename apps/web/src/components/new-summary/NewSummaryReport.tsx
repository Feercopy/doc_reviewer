"use client";

import { useState } from "react";

import type { NewSummaryLanguage, NewSummaryReport } from "@/lib/newSummary";

const labels = {
  ru: {
    context: "Краткий контекст инициативы",
    critical: "Критические проблемы",
    confirmed: "Что подтверждено",
    download: "Скачать PDF на русском и английском",
    insufficient: "Что недостаточно подтверждено",
    list: "Все новые Summary",
    missing: "Нет",
    other: "Other",
    present: "Есть",
    prototype: "Summary · скилл new-summary",
    required: "Обязательные элементы документа",
    requiredIntro:
      "Проверяется только наличие обязательных частей соответствующей стадии. Качество доказательств оценивается в следующих разделах.",
    source: "Исходный анализ",
    stage: "Стадия инициативы",
  },
  en: {
    context: "Initiative context",
    critical: "Critical problems",
    confirmed: "What is confirmed",
    download: "Download the Russian and English PDF",
    insufficient: "What is not sufficiently confirmed",
    list: "All New Summaries",
    missing: "Missing",
    other: "Other",
    present: "Present",
    prototype: "Summary · new-summary skill",
    required: "Required document elements",
    requiredIntro:
      "This block checks only whether the stage-required elements are present. Evidence quality is assessed in the sections below.",
    source: "Source analysis",
    stage: "Initiative stage",
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
          {content.required_elements.map((item) => (
            <li className={item.status} key={item.id}>
              <span className="new-summary-required__marker" aria-hidden="true" />
              <div>
                <div className="new-summary-required__title">
                  <strong>{item.label}</strong>
                  <span>{item.status === "present" ? text.present : text.missing}</span>
                </div>
                <p>{item.evidence}</p>
              </div>
            </li>
          ))}
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

function SummarySection({
  className = "",
  items,
  title,
}: {
  className?: string;
  items: string[];
  title: string;
}) {
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

const newSummaryStyles = `
.new-summary-shell {
  display: grid;
  width: min(1240px, 100%);
  gap: 16px;
  margin: 0 auto;
  padding: 18px 24px 40px;
}

.new-summary-shell--embedded {
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

.new-summary-context { padding: 20px 22px; }

.new-summary-context h2,
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
  background: var(--danger);
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
  background: var(--danger-bg);
  color: #a5122a;
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
