"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

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
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load benchmarks"));
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

  const mainSkills = skills.filter((skill) => skill.skill_type === "main_analysis" && skill.status === "active");
  const judgeSkills = skills.filter((skill) => skill.skill_type === "benchmark_judge" && skill.status === "active");

  return (
    <AppShell>
      <main className="main stack">
        <div className="toolbar">
          <div>
            <h1>Benchmarks</h1>
            <p className="muted">Runs over active etalons</p>
          </div>
        </div>
        {error ? <section className="panel error">{error}</section> : null}
        <form className="panel stack" onSubmit={submit}>
          <h2>Launch</h2>
          <div className="form-grid">
            <label>
              Name
              <input name="name" required />
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
              <select name="skill_id" required>
                {mainSkills.map((skill) => (
                  <option key={skill.id} value={skill.id}>
                    {skill.name} · {skill.version}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Judge skill
              <select name="judge_skill_id" required>
                {judgeSkills.map((skill) => (
                  <option key={skill.id} value={skill.id}>
                    {skill.name} · {skill.version}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Active etalons
              <select name="etalon_ids" multiple required>
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
            <textarea name="description" />
          </label>
          <button disabled={pending || !etalons.length || !mainSkills.length || !judgeSkills.length} type="submit">
            Launch benchmark
          </button>
        </form>
        <section className="panel">
          {benchmarks.length ? (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Provider</th>
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
                      <div className="muted">{benchmark.description}</div>
                    </td>
                    <td>
                      <StatusBadge status={benchmark.status} />
                    </td>
                    <td>
                      {benchmark.provider}
                      <div className="muted">{benchmark.model}</div>
                    </td>
                    <td>
                      {benchmark.f1 ?? "-"}
                      <div className="muted">
                        L1 {benchmark.layer_1_score ?? "-"} · L2 {benchmark.layer_2_score ?? "-"}
                      </div>
                    </td>
                    <td>{formatDate(benchmark.started_at)}</td>
                    <td>
                      <Link className="secondary-link" href={`/benchmarks/${benchmark.id}`}>
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="muted">No benchmarks yet.</div>
          )}
        </section>
      </main>
    </AppShell>
  );
}
