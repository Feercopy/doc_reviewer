"use client";

import { useState } from "react";
import { confirmedFirst, gate2HypothesisSummary, metricBindingSummary } from "@/lib/newSummaryRequired";

import type {
  NewSummaryContent,
  NewSummaryCriticalProblem,
  NewSummaryLanguage,
  NewSummaryReport,
  NewSummaryRequiredDetails,
  NewSummaryRequiredElement,
  NewSummaryTractionSummary,
  NewSummaryTractionTable,
} from "@/lib/newSummary";

const labels = {
  ru: {
    appendices: "Appendices",
    additionalStops: "Дополнительные найденные Stop критерии",
    bindingConfirmed: "Связь подтверждена",
    bindingInsufficient: "Связь кажется неподтвержденной",
    outputHeader: "Output-метрики — uplifts",
    launches: "План-факт по запускам",
    metricsFact: "План-факт по метрикам",
    planned: "План",
    fact: "Факт",
    completed: "Выполнено",
    partialLaunch: "Частично выполнено",
    notCompleted: "Не выполнено",
    unknownLaunch: "Нет данных",
    linksAbsent: "Ссылки в документе не представлены",
    linksUnavailable: "Не удалось скопировать ссылки из документа",
    verdictConfirmed: "Подтверждено",
    verdictInsufficient: "Недостаточно подтверждено",
    context: "Краткий контекст инициативы",
    current: "Текущее значение",
    critical: "Выявленные проблемы",
    downloadPdf: "Скачать PDF",
    downloadWord: "Скачать Word",
    inputMetrics: "Input metrics",
    list: "Все новые Summary",
    metric: "Метрика",
    missing: "Нет",
    partial: "Частично подтверждено",
    nextReview: "Значение к следующему ревью",
    outputsUntilGate3: "Outputs until Gate 3",
    metricsUntilGate3: "Metrics until Gate 3",
    outputsUntilNextReview: "Outputs until the next Review",
    metricsUntilNextReview: "Metrics until the next Review",
    other: "Другие наблюдения",
    outputMetrics: "Output metrics",
    present: "Есть",
    quality: "Качество документа",
    qualityHelpTitle: "Как рассчитано качество",
    qualityHelpText: "Оценка основана на обязательных элементах этой стадии: «Есть» — 2 балла, «Частично подтверждено» — 1, «Нет» — 0. Если у пункта есть оцененные подпункты, считаются они, а не родительский пункт. Процент — доля набранных баллов от максимума.",
    required: "Обязательные элементы документа",
    source: "Исходный анализ",
    stage: "Стадия инициативы",
    traction: "Traction Summary",
    test: "Проверка",
    expected: "ожидали",
    actual: "получили",
  },
  en: {
    additionalStops: "Additional stop criteria",
    appendices: "Appendices",
    bindingConfirmed: "Binding is relevant",
    bindingInsufficient: "Binding seems irrelevant",
    outputHeader: "Output metrics — uplifts",
    launches: "Launches: plan vs actual",
    metricsFact: "Metrics: plan vs actual",
    planned: "Plan",
    fact: "Actual",
    completed: "Completed",
    partialLaunch: "Partially completed",
    notCompleted: "Not completed",
    unknownLaunch: "No data",
    linksAbsent: "No links are provided in the document",
    linksUnavailable: "Could not copy links from the document",
    verdictConfirmed: "Confirmed",
    verdictInsufficient: "Not sufficiently confirmed",
    context: "Initiative context",
    current: "Current value",
    critical: "Identified problems",
    downloadPdf: "Download PDF",
    downloadWord: "Download Word",
    inputMetrics: "Input metrics",
    list: "All New Summaries",
    metric: "Metric",
    missing: "Missing",
    partial: "Partially confirmed",
    nextReview: "Next review value",
    outputsUntilGate3: "Outputs until Gate 3",
    metricsUntilGate3: "Metrics until Gate 3",
    outputsUntilNextReview: "Outputs until the next Review",
    metricsUntilNextReview: "Metrics until the next Review",
    other: "Other observations",
    outputMetrics: "Output metrics",
    present: "Present",
    quality: "Document quality",
    qualityHelpTitle: "How quality is calculated",
    qualityHelpText: "Required elements for this stage are scored: Present — 2 points, Partially confirmed — 1, Missing — 0. When a criterion has scored subitems, those replace the parent score. The percentage is the share of points earned out of the maximum.",
    required: "Required document elements",
    source: "Source analysis",
    stage: "Initiative stage",
    traction: "Traction Summary",
    test: "Test",
    expected: "expected",
    actual: "observed",
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
  const v6 = content.schema_version === "new-summary-v6" || content.schema_version === "new-summary-v7" || content.schema_version === "new-summary-v8";
  const currentFormat = v6 || content.schema_version === "new-summary-v5";
  const newFormat = currentFormat || content.schema_version === "new-summary-v2" || content.schema_version === "new-summary-v3" || content.schema_version === "new-summary-v4";
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
        ) : null}
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
              {text.downloadPdf}
            </a>
          ) : null}
          {report.docx_path ? (
            <a className="new-summary-download" download href={report.docx_path}>
              {text.downloadWord}
            </a>
          ) : null}
        </div>
      </div>

      <header className="new-summary-header">
        <h1>{displayTitle(content.title)}</h1>
        <div className="new-summary-stage">
          <span>{text.stage}</span>
          <strong>{content.stage}</strong>
        </div>
        {!newFormat && typeof content.document_quality_percent === "number" ? (
          <div className="new-summary-quality-row">
            <p className="new-summary-quality">{text.quality} - {content.document_quality_percent}%</p>
            <span className="new-summary-help-wrap">
              <button className="new-summary-help" type="button" aria-label={text.qualityHelpTitle} aria-describedby="new-summary-quality-help">?</button>
              <span className="new-summary-help__tooltip" id="new-summary-quality-help" role="tooltip">
                <strong>{text.qualityHelpTitle}</strong>
                <span>{text.qualityHelpText}</span>
              </span>
            </span>
          </div>
        ) : null}
      </header>

      <TractionSummaryTable content={content} labels={text} />

      <section className="new-summary-panel new-summary-context">
        <h2>{text.context}</h2>
        <p>{content.context}</p>
      </section>

      <section className={`new-summary-panel new-summary-required${newFormat ? " new-summary-required--numbered" : ""}`}>
        <div className="new-summary-section-heading">
          <h2>{text.required}</h2>
        </div>
        <ul>
          {content.required_elements.map((item, index) => {
            const tone = requiredElementTone(item);
            const countedMetrics = v6 && ["gate2_metric_linkage", "stream_review_1_input_output_metric_link"].includes(item.id);
            const hypothesisSummary = (countedMetrics ? metricBindingSummary(item, language) : null) ?? gate2HypothesisSummary(item, language, newFormat, currentFormat);
            return (
              <li className={tone} key={item.id}>
                {newFormat ? (
                  <span className="new-summary-required__number" aria-hidden="true">{index + 1}.</span>
                ) : (
                  <span className="new-summary-required__marker" aria-hidden="true" />
                )}
                <div>
                  <div className="new-summary-required__title">
                    {currentFormat && hypothesisSummary ? <>
                      <strong>{hypothesisSummary.slice(0, hypothesisSummary.indexOf(":") + 1)}</strong>
                      <span>{hypothesisSummary.slice(hypothesisSummary.indexOf(":") + 1)}</span>
                    </> : <strong style={content.schema_version === "new-summary-v4" && item.id === "gate2_hypothesis_results" && hypothesisSummary ? { fontWeight: 400 } : undefined}>
                      {hypothesisSummary ?? <>
                        {leadingWords(item.label)}
                        <span className="new-summary-inline-tail">
                          {lastWord(item.label)}
                          {!countedMetrics ? <span className="new-summary-required__status">{tone === "fraction" ? item.status : text[tone]}</span> : null}
                        </span>
                      </>}
                    </strong>}
                  </div>
                  {item.evidence ? <p>{item.evidence}</p> : null}
                  {item.detail ? (
                    <div className="new-summary-required__detail">
                      <RequiredDetailContent detail={item.detail} labels={text} inlineItemId={item.id} currentFormat={currentFormat} v6={v6} />
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {content.critical_problems?.length ? (
        <section className="new-summary-panel new-summary-critical">
          <ProblemsSection items={content.critical_problems} title={text.critical} />
        </section>
      ) : null}

      {!newFormat && content.other?.length ? (
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
      {tractionTables(traction).map((table) => (
        <div className="new-summary-table-scroll" key={table.metric ?? table.metric_label ?? "combined"}>
          <table>
            <thead>
              <tr>
                <th>{content.schema_version === "new-summary-v7" || content.schema_version === "new-summary-v8" ? (content.language === "ru" ? "Output-метрики" : "Output metrics") : text.outputHeader}</th>
                {table.periods.map((period, index) => (
                  <th key={`${period}-${index}`}>{period}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, rowIndex) => (
                <tr key={`${row.label}-${rowIndex}`}>
                  <th>{tractionRowLabel(table, row.label)}</th>
                  {table.periods.map((period, index) => (
                    <td key={`${rowIndex}-${period}-${index}`} className={row.mismatch_periods?.includes(period) ? "new-summary-traction-mismatch" : undefined}>
                      {displayTractionCell(row.values[index], content.schema_version)}
                      {row.mismatch_periods?.includes(period) ? <small>{languageMismatchNote(content.language)}</small> : null}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}

export function tractionRowLabel(table: NewSummaryTractionTable, label: string): string {
  if (!table.metric_label) return label;
  if (/revenue|выручк|\bDTB\b/i.test(label)) {
    const unit = table.metric_label.split(",").slice(1).join(",").trim();
    return unit && !label.includes(unit) ? `${label}, ${unit}` : label;
  }
  if (["total incremental output uplifts", "итоговый инкрементальный прирост", ""].includes(label.toLowerCase())) return table.metric_label;
  return table.metric_label ? `${table.metric_label}: ${label}` : label;
}

function languageMismatchNote(language: NewSummaryLanguage): string {
  return language === "ru" ? "Не равно Rev. from DTB + Rev. non-DTB" : "Does not equal Rev. from DTB + Rev. non-DTB";
}

function SummarySection({
  className = "",
  items,
  title,
}: {
  className?: string;
  items?: string[];
  title: string;
}) {
  if (!items?.length) {
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

function ProblemsSection({ items, title }: { items: NewSummaryCriticalProblem[]; title: string }) {
  return (
    <section className="new-summary-list-section critical">
      <h2>{title}</h2>
      <ul>
        {items.map((item, index) => (
          <li key={`${index}-${typeof item === "string" ? item : item.issue}`}>
            {typeof item === "string" ? item : <><strong className="new-summary-problem__issue">{item.issue}</strong> {item.fact}</>}
          </li>
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
  inlineItemId,
  currentFormat = false,
  v6 = false,
}: {
  detail: NewSummaryRequiredDetails;
  labels: (typeof labels)[NewSummaryLanguage];
  inlineItemId?: string;
  currentFormat?: boolean;
  v6?: boolean;
}) {
  if (detail.type === "hypotheses_with_thresholds") {
    return (
      <ul className="new-summary-appendix-list">
        {detail.items.map((item) => (
          <li key={`${item.hypothesis}-${item.confirmation_condition}`}>
            <strong>{item.hypothesis}</strong> - {item.confirmation_condition}
          </li>
        ))}
      </ul>
    );
  }

  if (detail.type === "solution_validation") {
    return (
      <ul className="new-summary-appendix-list">
        {confirmedFirst(detail.items, (item) => item.verdict).map((item) => (
          <li key={item.text}>
            <InlineVerdict text={item.text} status={item.verdict} labels={text} kind="hypothesis" />
            {item.test || item.expected_result || item.actual_result ? (
              <p className="new-summary-validation-evidence">
                {[
                  item.test && `${text.test}: ${item.test}`,
                  item.expected_result && `${text.expected}: ${item.expected_result}`,
                  item.actual_result && `${text.actual}: ${item.actual_result}`,
                ].filter(Boolean).join("; ")}.
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    );
  }

  if (detail.type === "metric_binding") {
    return (
      <div className="new-summary-metric-binding">
        <MetricBindingGroup items={detail.input_metrics} labels={text} title={text.inputMetrics} currentFormat={currentFormat} />
        <MetricBindingGroup items={detail.output_metrics} labels={text} title={text.outputMetrics} currentFormat={currentFormat} />
      </div>
    );
  }

  if (detail.type === "source_links") {
    const links = detail.links.filter((link) => /^https?:\/\//i.test(link.url));
    return links.length ? <ul className="new-summary-appendix-list">{links.map((link) => (
      <li key={link.url}><a className={v6 ? "new-summary-source-link" : undefined} href={link.url} target="_blank" rel="noreferrer">{link.label}</a></li>
    ))}</ul> : <p>{detail.availability === "absent" ? text.linksAbsent : text.linksUnavailable}</p>;
  }

  if (detail.type === "next_review_plan" || detail.type === "plan_fact") {
    const gate2 = inlineItemId === "gate2_commitments";
    const inline = Boolean(inlineItemId);
    const planFact = detail.type === "plan_fact";
    const launchStatus = { completed: text.completed, partial: text.partialLaunch, not_completed: text.notCompleted, unknown: text.unknownLaunch };
    const outputs = planFact ? detail.launches.map((item) => `${item.output} — ${launchStatus[item.status]}${item.comment ? `. ${item.comment}` : ""}`) : detail.outputs_until_next_review;
    const metrics = planFact ? detail.metrics.map((item) => ({ metric: item.metric, current: item.planned, next_review: item.actual })) : detail.metrics_until_next_review;
    return (
      <div className="new-summary-plan-detail">
        {outputs.length ? (
          <>
            {inline ? <h4>{planFact ? text.launches : gate2 ? text.outputsUntilGate3 : text.outputsUntilNextReview}</h4> : null}
            <ul className="new-summary-appendix-list">
              {planFact && v6 ? detail.launches.map((item, index) => (
                <li key={`${index}-${item.output}`}>
                  {item.output}<span className={`new-summary-status-chip launch-${item.status}`}>{launchStatus[item.status]}</span>
                  {item.comment ? `. ${item.comment}` : ""}
                </li>
              )) : outputs.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        ) : null}
        {metrics.length ? (
          <>
            {inline ? <h4>{planFact ? text.metricsFact : gate2 ? text.metricsUntilGate3 : text.metricsUntilNextReview}</h4> : null}
            <div className="new-summary-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{text.metric}</th>
                    <th>{planFact ? text.planned : text.current}</th>
                    <th>{planFact ? text.fact : text.nextReview}</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.map((row) => (
                    <tr key={`${row.metric}-${row.current}-${row.next_review}`}>
                      <th>{row.metric}</th>
                      <td>{row.current}</td>
                      <td>{row.next_review}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </div>
    );
  }

  if (detail.type === "criteria_list") {
    return (
      <ol className="new-summary-appendix-list">
        {detail.criteria.map((item) => <li key={item}>{item}</li>)}
      </ol>
    );
  }

  if (v6 && !detail.criteria.length) return null;
  return (
    <>
    {v6 ? <h4>{text.additionalStops}</h4> : null}
    <ul className="new-summary-appendix-list">
      {detail.criteria.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
    </>
  );
}

function MetricBindingGroup({
  items,
  labels: text,
  title,
  currentFormat = false,
}: {
  items: Array<{ metric: string; binding: "confirmed" | "insufficient"; evidence: string }>;
  labels: (typeof labels)[NewSummaryLanguage];
  title: string;
  currentFormat?: boolean;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <div>
      <h4>{title}</h4>
      <ul className="new-summary-appendix-list">
        {confirmedFirst(items, (item) => item.binding).map((item) => (
          <li key={`${item.metric}-${item.evidence}`}>
            {currentFormat ? <>
              <strong>{item.metric}</strong>{" — "}
              <InlineVerdict text={item.evidence} status={item.binding} labels={text} />
            </> : <>
              <InlineVerdict text={item.metric} status={item.binding} labels={text} />
              {item.evidence ? <p className="new-summary-validation-evidence">{item.evidence}</p> : null}
            </>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusChip({
  labels: text,
  status,
  kind = "binding",
}: {
  labels: (typeof labels)[NewSummaryLanguage];
  status: "confirmed" | "insufficient";
  kind?: "binding" | "hypothesis";
}) {
  const confirmed = status === "confirmed";
  const label = kind === "hypothesis"
    ? confirmed ? text.verdictConfirmed : text.verdictInsufficient
    : confirmed ? text.bindingConfirmed : text.bindingInsufficient;
  return (
    <span className={confirmed ? "new-summary-status-chip confirmed" : "new-summary-status-chip insufficient"}>
      {label}
    </span>
  );
}

function leadingWords(value: string): string {
  const index = value.trimEnd().lastIndexOf(" ");
  return index < 0 ? "" : `${value.slice(0, index)} `;
}

function lastWord(value: string): string {
  const index = value.trimEnd().lastIndexOf(" ");
  return value.slice(index + 1).trim();
}

function InlineVerdict({
  text: value,
  status,
  labels: text,
  kind,
}: {
  text: string;
  status: "confirmed" | "insufficient";
  labels: (typeof labels)[NewSummaryLanguage];
  kind?: "binding" | "hypothesis";
}) {
  return <>{leadingWords(value)}<span className="new-summary-inline-tail">{lastWord(value)}<StatusChip status={status} labels={text} kind={kind} /></span></>;
}

function hasTractionSummary(value: NewSummaryTractionSummary | undefined): value is NewSummaryTractionSummary {
  return tractionTables(value).some((table) => table.periods.length > 0 && table.rows.length > 0);
}

function displayTitle(title: string): string {
  const stage = "(?:gate\\s*[1-4]|progress\\s+review|stream\\s+review(?:\\s*#?\\s*(?:1|2\\+?))?|ic\\s+update\\s+request|дозапрос\\s+ресурс[а-яё]*)";
  const shortLanguage = "(?:en|eng|ru|rus|рус)";
  const language = `(?:${shortLanguage}|english|russian|рус(?:ский|ская|ское|ские)|англ(?:ийский|ийская|ийское)?)`;
  const annotation = `(?:${stage}|${language})`;
  const annotationGroup = `${annotation}(?:\\s*(?:and|и|&|,|/|\\+)\\s*${annotation})*`;
  const trailingAnnotation = new RegExp(`(?:\\s*[-–—_|:]\\s*|\\s*\\()\\s*${annotationGroup}\\s*\\)?\\s*$|\\s+(?:${stage}|${shortLanguage})\\s*$`, "i");
  const leadingAnnotation = new RegExp(`^\\s*(?:${annotationGroup}\\s*[-–—_|:]\\s*|${stage}\\s+)`, "i");
  let initiative = title
    .replace(/(?:<br\s*\/?>|&lt;br\s*\/?&gt;)/gi, " ")
    .replace(/^AI Summary\s+/i, "")
    .replace(/\s*[-–—]\s*AI Summary\s*$/i, "")
    .replace(/\[([^\]]+)\]\(https?:\/\/[^)]+\)/gi, (_, label: string) =>
      /(?:3\s*sigma|tri\s*sigma|три\s*сигм|ссылка|\blink\b)/i.test(label) ? "" : label,
    )
    .replace(/https?:\/\/\S+/gi, "");
  for (let index = 0; index < 8; index += 1) {
    const cleaned = initiative
      .replace(/(?:\s*\((?:3\s*sigma|tri\s*sigma|три\s*сигм|ссылка|link)[^)]*\)\s*)+$/i, "")
      .replace(trailingAnnotation, "")
      .replace(leadingAnnotation, "");
    if (cleaned === initiative) break;
    initiative = cleaned;
  }
  initiative = initiative.replace(/\s+/g, " ").replace(/^[\s\-–—,;:]+|[\s\-–—,;:]+$/g, "");
  if (new RegExp(`^${annotationGroup}$`, "i").test(initiative)) initiative = "";
  return `${initiative || "Untitled initiative"} - AI Summary`;
}

function displayTractionCell(value: string | undefined, schemaVersion: NewSummaryContent["schema_version"]): string {
  const text = (value ?? "").trim();
  if (text === "" || text === "-" || text === "–" || text === "—") return "—";
  if (schemaVersion === "new-summary-v8" && /^(?:отсутствуют данные в документе защиты|невозможно извлечь данные|нет данных в документе|не смог получить данные|значение не найдено в документе|no data in the defense document|could not extract data|no data in the document|value not found in the document)$/i.test(text)) return "—";
  return text;
}

function tractionTables(value: NewSummaryTractionSummary | undefined): NewSummaryTractionTable[] {
  if (!value) return [];
  return "tables" in value ? value.tables : [value];
}

function requiredElementTone(item: NewSummaryRequiredElement): "present" | "partial" | "missing" | "fraction" {
  if (/^\d+\/\d+$/.test(item.status)) return "fraction";
  if (item.status === "present" || item.status === "есть") return "present";
  if (item.status === "partially confirmed" || item.status === "частично подтверждено") return "partial";
  return "missing";
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
.new-summary-shell a.new-summary-source-link { color: #0563C1; text-decoration: underline; }
.new-summary-status-chip.launch-completed { color: #0FA36B; background: #e8f7ef; }
.new-summary-status-chip.launch-partial { color: #C77800; background: #fff4e5; }
.new-summary-status-chip.launch-not_completed { color: #D92D20; background: #fff0ee; }
.new-summary-status-chip.launch-unknown { color: #5D6675; background: #f6f8fa; }
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
  justify-content: flex-start;
  gap: 14px;
  padding-inline: 0;
}

.new-summary-toolbar__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-start;
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

.new-summary-quality-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.new-summary-quality {
  margin: 1px 0 0;
  color: var(--muted-strong);
  font-size: 17px;
  font-weight: 700;
}

.new-summary-help-wrap { position: relative; display: inline-flex; }
.analysis-workbench button.new-summary-help {
  display: inline-grid;
  width: 22px;
  height: 22px;
  min-height: 22px;
  place-items: center;
  border: 1px solid var(--info);
  border-radius: 50%;
  background: transparent;
  color: var(--info);
  box-shadow: none;
  padding: 0;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  cursor: help;
}

.analysis-workbench button.new-summary-help:hover:not(:disabled) {
  border-color: var(--info);
  background: transparent;
  color: var(--info);
  transform: none;
}

.new-summary-help__tooltip {
  display: none;
  position: absolute;
  z-index: 3;
  top: calc(100% + 8px);
  right: 0;
  width: min(360px, calc(100vw - 32px));
  max-height: min(230px, 35vh);
  overflow: auto;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  background: var(--panel);
  box-shadow: var(--shadow);
  padding: 12px 14px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
}
.new-summary-help__tooltip strong { display: block; margin-bottom: 6px; color: var(--foreground); font-size: inherit; }
.new-summary-help:hover + .new-summary-help__tooltip,
.new-summary-help:focus-visible + .new-summary-help__tooltip,
.new-summary-help__tooltip:hover { display: block; }

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
  font-size: 19px;
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
  table-layout: fixed;
  font-size: 13px;
}

.new-summary-table-scroll th:first-child { width: 32%; }

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

.new-summary-traction td { overflow-wrap: anywhere; }
.new-summary-traction td.new-summary-traction-mismatch { color: #b91c1c; }
.new-summary-traction-mismatch small { display: block; margin-top: 3px; font-size: 11px; }

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
.new-summary-required > ul > li:first-child { border-top: 0; }

.new-summary-required--numbered > ul > li { grid-template-columns: 24px minmax(0, 1fr); }
.new-summary-required__number { color: var(--muted); font-size: 14px; font-weight: 700; line-height: 1.4; }
.new-summary-validation-evidence { margin: 4px 0 0; color: var(--muted); font-size: 13px; line-height: 1.5; }

.new-summary-required__marker {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 999px;
  background: var(--danger);
}

.new-summary-required li.present .new-summary-required__marker { background: var(--success); }
.new-summary-required li.partial .new-summary-required__marker { background: var(--warning); }
.new-summary-required li.fraction .new-summary-required__marker { background: transparent; }

.new-summary-required__title {
  display: block;
  font-size: 14px;
  line-height: 1.4;
  color: var(--foreground);
}

.new-summary-inline-tail { display: inline-block; white-space: nowrap; }

.new-summary-required__title strong {
  color: var(--foreground);
  font-size: 14px;
  line-height: 1.4;
}

.new-summary-required__title .new-summary-required__status {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  margin-left: 3ch;
  border-radius: 999px;
  background: var(--danger-bg);
  color: var(--danger);
  padding: 0 8px;
  font-size: 11px;
  font-weight: 800;
}

.new-summary-required li.present .new-summary-required__title .new-summary-required__status {
  background: var(--success-bg);
  color: #075e45;
}

.new-summary-required li.partial .new-summary-required__title .new-summary-required__status {
  background: var(--warning-bg);
  color: #925c00;
}

.new-summary-required li.fraction .new-summary-required__title .new-summary-required__status {
  background: transparent;
  color: var(--foreground);
  padding: 0;
  font-size: 13px;
}

.new-summary-required p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.new-summary-required__detail {
  margin-top: 14px;
}

.new-summary-required__detail .new-summary-appendix-list li,
.new-summary-required__detail .new-summary-appendix-list li strong {
  color: var(--muted);
  font-size: 13px;
}

.new-summary-required__detail h4 {
  margin: 0 0 8px;
  color: var(--foreground);
  font-size: 13px;
}

.new-summary-plan-detail > .new-summary-appendix-list + h4 {
  margin-top: 16px;
}

.new-summary-required__detail .new-summary-table-scroll {
  margin-top: 10px;
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

.new-summary-problem__issue { color: var(--foreground); font-weight: 750; }

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
  margin-left: 3ch;
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
