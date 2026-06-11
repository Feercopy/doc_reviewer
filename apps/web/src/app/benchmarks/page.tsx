"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { createBenchmark, listBenchmarks, type BenchmarkRecord } from "@/lib/api/benchmarks";
import { listEtalons, type EtalonRecord } from "@/lib/api/etalons";
import type { Provider } from "@/lib/api/documents";
import { listSkills, type SkillRecord } from "@/lib/api/skills";
import { formatDate, formatLabel } from "@/lib/format";

export default function BenchmarksPage() {
  const [benchmarks, setBenchmarks] = useState<BenchmarkRecord[]>([]);
  const [etalons, setEtalons] = useState<EtalonRecord[]>([]);
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [provider, setProvider] = useState<Provider>("openai_compatible");

  async function refresh() {
    const [benchmarkResponse, etalonResponse, skillResponse] = await Promise.all([
      listBenchmarks(),
      listEtalons(),
      listSkills(),
    ]);
    setBenchmarks(benchmarkResponse.benchmarks);
    setEtalons(etalonResponse.etalons.filter((item) => item.status === "active"));
    setSkills(skillResponse.skills);
  }

  useEffect(() => {
    setLoading(true);
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load benchmarks"))
      .finally(() => setLoading(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const form = new FormData(event.currentTarget);
      const etalonIds = form.getAll("etalon_ids").map(String).filter(Boolean);
      await createBenchmark({
        name: String(form.get("name") ?? ""),
        description: String(form.get("description") ?? ""),
        etalon_ids: etalonIds,
        skill_id: String(form.get("skill_id") ?? ""),
        provider,
        model: String(form.get("model") ?? ""),
        judge_skill_id: String(form.get("judge_skill_id") ?? ""),
        evaluation_mode: "layer_1_and_layer_2",
        run_parameters: {},
      });
      event.currentTarget.reset();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to launch benchmark");
    } finally {
      setPending(false);
    }
  }

  const mainSkills = useMemo(
    () => skills.filter((skill) => skill.skill_type === "main_analysis" && skill.status === "active"),
    [skills],
  );
  const judgeSkills = useMemo(
    () => skills.filter((skill) => skill.skill_type === "benchmark_judge" && skill.status === "active"),
    [skills],
  );
  const canLaunch = etalons.length > 0 && mainSkills.length > 0 && judgeSkills.length > 0;
  const completedCount = benchmarks.filter((benchmark) => benchmark.status === "completed").length;
  const runningCount = benchmarks.filter((benchmark) => ["queued", "running"].includes(benchmark.status)).length;
  const latestBenchmark = benchmarks[0];

  return (
    <AppShell>
      <main className="benchmarks-console">
        <style>{`${benchmarksStyles}\n${paperBenchmarksOverrides}`}</style>
        <section className="benchmarks-hero">
          <div>
            <div className="benchmarks-eyebrow">Dark launch console</div>
            <h1>Benchmarks</h1>
            <p>
              Run reproducible checks over active etalons, compare Gate Challenger skill quality, and inspect precision,
              recall, misses, false positives, and partial matches.
            </p>
          </div>
          <div className="benchmarks-kpis">
            <Kpi label="Total runs" value={String(benchmarks.length)} />
            <Kpi label="Completed" value={String(completedCount)} />
            <Kpi label="Queued/running" value={String(runningCount)} />
            <Kpi label="Active etalons" value={String(etalons.length)} />
          </div>
        </section>

        {error ? <section className="benchmarks-alert">{error}</section> : null}

        <div className="benchmarks-layout">
          <form className="benchmarks-card benchmarks-launch" onSubmit={submit}>
            <div className="benchmarks-card__header">
              <div>
                <h2>Launch</h2>
                <p>Layer 1 and Layer 2 judge pass over selected active etalons.</p>
              </div>
              <span className={canLaunch ? "benchmarks-ready" : "benchmarks-not-ready"}>
                {canLaunch ? "Ready" : "Needs setup"}
              </span>
            </div>

            <div className="benchmarks-form-grid">
              <label>
                Name
                <input name="name" required placeholder="Gate 2 baseline comparison" />
              </label>
              <label>
                Provider
                <select value={provider} onChange={(event) => setProvider(event.target.value as Provider)}>
                  <option value="openai_compatible">OpenAI compatible</option>
                  <option value="anthropic_compatible">Anthropic compatible</option>
                  <option value="hermes">Hermes</option>
                </select>
              </label>
              <label>
                Model
                <input name="model" required defaultValue="gpt-test" />
              </label>
              <label>
                Main skill
                <select name="skill_id" required disabled={!mainSkills.length}>
                  {mainSkills.map((skill) => (
                    <option key={skill.id} value={skill.id}>
                      {skill.name} · {skill.version}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Judge skill
                <select name="judge_skill_id" required disabled={!judgeSkills.length}>
                  {judgeSkills.map((skill) => (
                    <option key={skill.id} value={skill.id}>
                      {skill.name} · {skill.version}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Active etalons
                <select name="etalon_ids" multiple required disabled={!etalons.length}>
                  {etalons.map((etalon) => (
                    <option key={etalon.id} value={etalon.id}>
                      {formatLabel(etalon.document_type)} · {formatLabel(etalon.expected_verdict)} · {etalon.id}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              Description
              <textarea name="description" placeholder="Scope, expected comparison, or model variant notes." />
            </label>

            {!canLaunch ? (
              <div className="benchmarks-requirements">
                {!etalons.length ? <span>No active etalons.</span> : null}
                {!mainSkills.length ? <span>No active main-analysis skill.</span> : null}
                {!judgeSkills.length ? <span>No active benchmark judge skill.</span> : null}
              </div>
            ) : null}

            <button disabled={pending || !canLaunch} type="submit">
              {pending ? "Launching..." : "Launch benchmark"}
            </button>
          </form>

          <aside className="benchmarks-card benchmarks-inspector">
            <div className="benchmarks-card__header">
              <div>
                <h2>Run context</h2>
                <p>Active inputs loaded from API</p>
              </div>
            </div>
            <InspectorRow label="Active etalons" value={String(etalons.length)} />
            <InspectorRow label="Main skills" value={String(mainSkills.length)} />
            <InspectorRow label="Judge skills" value={String(judgeSkills.length)} />
            <InspectorRow label="Latest status" value={latestBenchmark ? latestBenchmark.status : "n/a"} />
            <InspectorRow label="Latest F1" value={latestBenchmark?.f1 ?? "-"} />
          </aside>
        </div>

        <section className="benchmarks-card benchmarks-table-card">
          <div className="benchmarks-card__header">
            <div>
              <h2>Runs</h2>
              <p>Benchmark history with provider, model, skill version, and aggregate score.</p>
            </div>
          </div>
          {loading ? (
            <div className="benchmarks-state">Loading benchmarks...</div>
          ) : benchmarks.length ? (
            <div className="benchmarks-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Provider</th>
                    <th>Skill</th>
                    <th>Score</th>
                    <th>Started</th>
                    <th>Open</th>
                  </tr>
                </thead>
                <tbody>
                  {benchmarks.map((benchmark) => (
                    <tr key={benchmark.id}>
                      <td>
                        <strong>{benchmark.name}</strong>
                        <div className="benchmarks-muted">{benchmark.description || "No description"}</div>
                      </td>
                      <td>
                        <StatusBadge status={benchmark.status} />
                      </td>
                      <td>
                        {formatLabel(benchmark.provider)}
                        <div className="benchmarks-muted">{benchmark.model}</div>
                      </td>
                      <td>
                        {benchmark.skill_version}
                        <div className="benchmarks-muted">{benchmark.etalon_ids.length} etalon(s)</div>
                      </td>
                      <td>
                        <ScorePill value={benchmark.f1 ?? benchmark.overall_score} />
                        <div className="benchmarks-muted">
                          L1 {benchmark.layer_1_score ?? "-"} · L2 {benchmark.layer_2_score ?? "-"}
                        </div>
                      </td>
                      <td>{formatDate(benchmark.started_at)}</td>
                      <td>
                        <Link className="benchmarks-open" href={`/benchmarks/${benchmark.id}`}>
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="benchmarks-state">
              No benchmarks yet. Choose active etalons, a main skill, and a judge skill to launch the first run.
            </div>
          )}
        </section>
      </main>
    </AppShell>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="benchmarks-kpi">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="benchmarks-inspector-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ScorePill({ value }: { value: string | null }) {
  return <span className={`benchmarks-score benchmarks-score--${scoreTone(value)}`}>{value ?? "-"}</span>;
}

function scoreTone(value: string | null): string {
  const numeric = value === null ? NaN : Number(value);
  if (Number.isNaN(numeric)) {
    return "neutral";
  }
  if (numeric >= 0.8) {
    return "good";
  }
  if (numeric >= 0.5) {
    return "warn";
  }
  return "bad";
}

const benchmarksStyles = `
.benchmarks-console {
  width: min(100%, 1480px);
  margin: 0 auto;
  padding: 28px 24px 48px;
  color: #e6edf3;
}

.benchmarks-console h1,
.benchmarks-console h2,
.benchmarks-console p {
  margin: 0;
}

.benchmarks-console h1 {
  font-size: clamp(32px, 5vw, 56px);
  line-height: 1;
}

.benchmarks-console h2 {
  font-size: 18px;
  line-height: 1.25;
}

.benchmarks-console button,
.benchmarks-open {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(94, 234, 212, 0.28);
  border-radius: 6px;
  background: linear-gradient(180deg, #14b8a6 0%, #0f766e 100%);
  color: #f8fafc;
  padding: 0 14px;
  box-shadow: 0 12px 28px rgba(20, 184, 166, 0.18);
}

.benchmarks-console button:focus-visible,
.benchmarks-console input:focus-visible,
.benchmarks-console select:focus-visible,
.benchmarks-console textarea:focus-visible,
.benchmarks-open:focus-visible {
  outline: 3px solid rgba(56, 189, 248, 0.42);
  outline-offset: 2px;
}

.benchmarks-console input,
.benchmarks-console select,
.benchmarks-console textarea {
  border: 1px solid rgba(148, 163, 184, 0.26);
  background: rgba(2, 6, 23, 0.72);
  color: #e2e8f0;
}

.benchmarks-console textarea {
  min-height: 112px;
}

.benchmarks-console label {
  color: #a7b6ca;
}

.benchmarks-console table {
  color: #dbeafe;
}

.benchmarks-console th {
  border-bottom-color: rgba(148, 163, 184, 0.2);
  color: #7f8ea3;
}

.benchmarks-console td {
  border-bottom-color: rgba(148, 163, 184, 0.12);
}

.benchmarks-console .badge {
  border-color: rgba(148, 163, 184, 0.28);
  background: rgba(15, 23, 42, 0.78);
  color: #cbd5e1;
}

.benchmarks-console .badge.ok {
  border-color: rgba(52, 211, 153, 0.35);
  background: rgba(6, 78, 59, 0.58);
  color: #bbf7d0;
}

.benchmarks-console .badge.info {
  border-color: rgba(56, 189, 248, 0.38);
  background: rgba(12, 74, 110, 0.55);
  color: #bae6fd;
}

.benchmarks-console .badge.danger {
  border-color: rgba(248, 113, 113, 0.44);
  background: rgba(127, 29, 29, 0.55);
  color: #fecaca;
}

.benchmarks-hero,
.benchmarks-card,
.benchmarks-alert {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.96)),
    #020617;
  box-shadow: 0 22px 70px rgba(2, 6, 23, 0.28);
}

.benchmarks-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.65fr);
  gap: 18px;
  margin-bottom: 18px;
  padding: 22px;
}

.benchmarks-hero p,
.benchmarks-card__header p,
.benchmarks-muted,
.benchmarks-state,
.benchmarks-requirements {
  color: #9fb0c4;
  font-size: 13px;
  line-height: 1.6;
}

.benchmarks-hero p {
  max-width: 78ch;
  margin-top: 12px;
  font-size: 15px;
}

.benchmarks-eyebrow {
  margin-bottom: 10px;
  color: #5eead4;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.benchmarks-kpis,
.benchmarks-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.benchmarks-kpi,
.benchmarks-inspector-row,
.benchmarks-requirements {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.62);
  padding: 14px;
}

.benchmarks-kpi {
  display: grid;
  gap: 6px;
}

.benchmarks-kpi span,
.benchmarks-inspector-row span {
  color: #7f8ea3;
  font-size: 11px;
  text-transform: uppercase;
}

.benchmarks-kpi strong {
  font-size: 24px;
}

.benchmarks-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 18px;
  margin-bottom: 18px;
  align-items: start;
}

.benchmarks-card {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.benchmarks-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.benchmarks-launch {
  align-content: start;
}

.benchmarks-ready,
.benchmarks-not-ready,
.benchmarks-score {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  border-radius: 999px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.benchmarks-ready,
.benchmarks-score--good {
  border: 1px solid rgba(52, 211, 153, 0.4);
  background: rgba(6, 95, 70, 0.72);
  color: #bbf7d0;
}

.benchmarks-not-ready,
.benchmarks-score--warn {
  border: 1px solid rgba(251, 191, 36, 0.42);
  background: rgba(120, 53, 15, 0.7);
  color: #fde68a;
}

.benchmarks-score--bad {
  border: 1px solid rgba(248, 113, 113, 0.46);
  background: rgba(127, 29, 29, 0.7);
  color: #fecaca;
}

.benchmarks-score--neutral {
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(30, 41, 59, 0.78);
  color: #cbd5e1;
}

.benchmarks-inspector {
  position: sticky;
  top: 18px;
}

.benchmarks-inspector-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.benchmarks-inspector-row strong {
  color: #f8fafc;
}

.benchmarks-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.benchmarks-state {
  border: 1px dashed rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  padding: 24px;
  text-align: center;
}

.benchmarks-alert {
  margin-bottom: 14px;
  border-color: rgba(248, 113, 113, 0.42);
  color: #fecaca;
  padding: 16px;
}

@media (max-width: 1080px) {
  .benchmarks-hero,
  .benchmarks-layout {
    grid-template-columns: 1fr;
  }

  .benchmarks-inspector {
    position: static;
  }
}

@media (max-width: 720px) {
  .benchmarks-console {
    width: 100%;
    padding: 18px 10px 32px;
  }

  .benchmarks-hero,
  .benchmarks-card {
    padding: 14px;
  }

  .benchmarks-kpis,
  .benchmarks-form-grid {
    grid-template-columns: 1fr;
  }
}
`;

const paperBenchmarksOverrides = `
.benchmarks-console {
  width: min(1536px, 100%);
  padding: 28px 36px 48px;
  color: #111827;
}

.benchmarks-console h1 {
  color: #111827;
  font-size: 30px;
  font-weight: 800;
  line-height: 38px;
}

.benchmarks-console h2,
.benchmarks-console table,
.benchmarks-console td {
  color: #111827;
}

.benchmarks-console button,
.benchmarks-open {
  border-color: #0e9f6e;
  background: #0e9f6e;
  color: #ffffff;
  box-shadow: none;
}

.benchmarks-open:hover,
.benchmarks-console button:hover:not(:disabled) {
  border-color: #087d5f;
  background: #087d5f;
}

.benchmarks-console input,
.benchmarks-console select,
.benchmarks-console textarea {
  border-color: #d6dee8;
  background: #ffffff;
  color: #111827;
}

.benchmarks-console label {
  color: #111827;
}

.benchmarks-console th {
  border-bottom-color: #e5eaf0;
  color: #5b6472;
}

.benchmarks-console td {
  border-bottom-color: #edf1f5;
}

.benchmarks-console .badge {
  border-color: transparent;
  background: #f2f4f7;
  color: #344054;
}

.benchmarks-console .badge.ok,
.benchmarks-ready,
.benchmarks-score--good {
  border-color: transparent;
  background: #eaf8f2;
  color: #075e45;
}

.benchmarks-console .badge.info {
  border-color: transparent;
  background: #eaf3fb;
  color: #1d70b8;
}

.benchmarks-console .badge.danger,
.benchmarks-not-ready {
  border-color: transparent;
  background: #fcecee;
  color: #a5122a;
}

.benchmarks-hero,
.benchmarks-card,
.benchmarks-alert,
.benchmarks-kpi,
.benchmarks-inspector-row,
.benchmarks-requirements {
  border-color: #d6dee8;
  background: #ffffff;
  box-shadow: none;
}

.benchmarks-hero {
  padding: 0;
  border: 0;
  background: transparent;
}

.benchmarks-hero p,
.benchmarks-card__header p,
.benchmarks-muted,
.benchmarks-state,
.benchmarks-requirements,
.benchmarks-kpi span,
.benchmarks-inspector-row span {
  color: #5b6472;
}

.benchmarks-eyebrow {
  color: #5b6472;
}

.benchmarks-kpi,
.benchmarks-inspector-row,
.benchmarks-requirements {
  background: #f7f9fb;
}

.benchmarks-table-wrap {
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  overflow: auto;
}

.benchmarks-table-wrap table {
  background: #ffffff;
}

.benchmarks-table-wrap thead {
  background: #fbfcfd;
}

.benchmarks-state {
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #fbfcfd;
}

.benchmarks-alert {
  border-color: #f2d7d9;
  background: #fcecee;
  color: #a5122a;
}

@media (max-width: 680px) {
  .benchmarks-console {
    padding: 18px 12px 32px;
  }
}
`;
