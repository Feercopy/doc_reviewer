"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { MarkdownPreview } from "@/components/MarkdownPreview";
import { NewSummaryReportView } from "@/components/new-summary/NewSummaryReport";
import { getSharedAnalysis, type SharedAnalysis, type SharedFinancial } from "@/lib/api/analysis-shares";
import type { NewSummaryReport } from "@/lib/newSummary";

type Section = "summary" | "product" | "financial";

export default function SharedAnalysisPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const [analysis, setAnalysis] = useState<SharedAnalysis | null>(null);
  const [error, setError] = useState("");
  const [section, setSection] = useState<Section>("summary");

  useEffect(() => {
    let active = true;
    const token = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("share");
    if (!token) {
      setError("В ссылке нет ключа доступа.");
      return;
    }
    getSharedAnalysis(analysisId, token)
      .then((result) => { if (active) setAnalysis(result); })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [analysisId]);

  const report: NewSummaryReport | null = analysis?.summary_ru && analysis.summary_en ? {
    analysis_id: analysis.id,
    created_at: analysis.created_at,
    ru: analysis.summary_ru,
    en: analysis.summary_en,
  } : null;

  return (
    <main className="shared-analysis">
      <style>{sharedAnalysisStyles}</style>
      <header className="shared-analysis__header">
        <span className="shared-analysis__brand">Gate Challenger</span>
        {analysis ? <span className="shared-analysis__case">{analysis.title}</span> : null}
      </header>
      {error ? <div className="shared-analysis__message" role="alert">{error}</div> : null}
      {!analysis && !error ? <div className="shared-analysis__message" role="status">Загружаем результаты анализа…</div> : null}
      {analysis ? (
        <>
          <nav className="shared-analysis__tabs" aria-label="Разделы анализа">
            {([
              ["summary", "AI Summary"],
              ["product", "Product Analysis"],
              ["financial", "Financial Analysis"],
            ] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={section === id} onClick={() => setSection(id)}>{label}</button>
            ))}
          </nav>
          {section === "summary" ? (report ? <NewSummaryReportView embedded report={report} /> : <Unavailable />) : null}
          {section === "product" ? (
            <section className="shared-analysis__panel">
              <h1>Product Analysis</h1>
              {analysis.product_markdown ? <MarkdownPreview markdown={analysis.product_markdown} /> : <Unavailable />}
            </section>
          ) : null}
          {section === "financial" ? (
            <section className="shared-analysis__panel">
              <h1>Financial Analysis</h1>
              {analysis.financial ? <FinancialResult result={analysis.financial} /> : <Unavailable />}
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}

function Unavailable() {
  return <p className="shared-analysis__message">Этот раздел ещё не подготовлен для данного анализа.</p>;
}

function FinancialResult({ result }: { result: SharedFinancial }) {
  return (
    <div className="shared-analysis__financial">
      {result.executive_brief ? <p>{result.executive_brief}</p> : null}
      {result.top_findings.length ? <section><h2>Ключевые выводы</h2><ol>{result.top_findings.map((item, index) => (
        <li key={index}><strong>{item.title}</strong>{item.summary ? <p>{item.summary}</p> : null}{item.evidence ? <p>{item.evidence}</p> : null}</li>
      ))}</ol></section> : null}
      {result.key_numbers.length ? <section><h2>Ключевые показатели</h2><div className="shared-analysis__table"><table><thead><tr><th>Показатель</th><th>Значение</th><th>Источник</th></tr></thead><tbody>{result.key_numbers.map((item, index) => (
        <tr key={index}><td>{item.label}</td><td>{item.value} {item.unit}</td><td>{item.source}</td></tr>
      ))}</tbody></table></div></section> : null}
      <TextList title="Критические риски" items={result.critical_risks} />
      <TextList title="Недостаток данных" items={result.data_gaps} />
      <TextList title="Необходимые действия" items={result.required_actions} />
      {result.spreadsheet_audit.summary ? <section><h2>Проверка финансовой модели</h2><p>{result.spreadsheet_audit.summary}</p></section> : null}
      {result.validation.summary ? <section><h2>Валидация</h2><p>{result.validation.summary}</p></section> : null}
    </div>
  );
}

function TextList({ title, items }: { title: string; items: string[] }) {
  return items.length ? <section><h2>{title}</h2><ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul></section> : null;
}

const sharedAnalysisStyles = `
.shared-analysis { width: min(100%, 1480px); margin: 0 auto; padding: 20px 24px 56px; }
.shared-analysis__header { display: flex; align-items: center; flex-wrap: wrap; gap: 18px; padding: 10px 0 24px; }
.shared-analysis__brand { color: var(--accent-strong); font-size: 22px; font-weight: 800; }
.shared-analysis__case { color: var(--muted-strong); font-size: 14px; }
.shared-analysis__tabs { display: flex; flex-wrap: wrap; gap: 8px; padding: 6px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--panel); margin-bottom: 16px; }
.shared-analysis__tabs button { min-height: 42px; padding: 8px 14px; border: 0; border-radius: 6px; background: transparent; color: var(--muted-strong); font-weight: 700; }
.shared-analysis__tabs button[aria-pressed="true"] { background: var(--accent-muted); color: var(--accent-strong); }
.shared-analysis__message, .shared-analysis__panel { padding: 20px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.shared-analysis__panel h1 { font-size: 22px; margin: 0 0 18px; }
.shared-analysis__financial { display: grid; gap: 20px; }
.shared-analysis__financial section + section { border-top: 1px solid var(--line); padding-top: 18px; }
.shared-analysis__financial h2 { font-size: 17px; margin: 0 0 10px; }
.shared-analysis__financial p { margin: 7px 0; }
.shared-analysis__financial li { margin: 8px 0; }
.shared-analysis__table { overflow-x: auto; }
.shared-analysis__table table { width: 100%; border-collapse: collapse; }
.shared-analysis__table th, .shared-analysis__table td { text-align: left; padding: 10px; border-bottom: 1px solid var(--line); }
@media(max-width: 600px) { .shared-analysis { padding: 12px 14px 32px; } .shared-analysis__tabs button { flex: 1 1 auto; } }
`;
