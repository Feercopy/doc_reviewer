"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { cancelBenchmark, getBenchmark, getBenchmarkReport, type BenchmarkRecord } from "@/lib/api/benchmarks";
import { formatDate } from "@/lib/format";

export default function BenchmarkDetailPage() {
  const params = useParams<{ benchmarkId: string }>();
  const [benchmark, setBenchmark] = useState<BenchmarkRecord | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    const [nextBenchmark, nextReport] = await Promise.all([
      getBenchmark(params.benchmarkId),
      getBenchmarkReport(params.benchmarkId),
    ]);
    setBenchmark(nextBenchmark);
    setReport(nextReport);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load benchmark"));
  }, [params.benchmarkId]);

  async function cancel() {
    setPending(true);
    setError("");
    try {
      setBenchmark(await cancelBenchmark(params.benchmarkId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel benchmark");
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell>
      <main className="main stack">
        {error ? <section className="panel error">{error}</section> : null}
        {benchmark ? (
          <>
            <section className="panel stack">
              <div className="toolbar">
                <div>
                  <h1>{benchmark.name}</h1>
                  <p className="muted">
                    {benchmark.provider} · {benchmark.model} · {formatDate(benchmark.started_at)}
                  </p>
                </div>
                <StatusBadge status={benchmark.status} />
              </div>
              <div className="meta-grid">
                <Score label="Overall F1" value={benchmark.f1} />
                <Score label="Layer 1" value={benchmark.layer_1_score} />
                <Score label="Layer 2" value={benchmark.layer_2_score} />
                <Score label="Precision" value={benchmark.precision} />
                <Score label="Recall" value={benchmark.recall} />
              </div>
              {benchmark.error_message ? <div className="error">{benchmark.error_message}</div> : null}
              <button className="secondary" disabled={pending || !["queued", "running"].includes(benchmark.status)} type="button" onClick={cancel}>
                Cancel
              </button>
            </section>
            <section className="panel stack">
              <h2>Missed Findings</h2>
              <pre className="text-preview">{JSON.stringify(benchmark.missed_findings ?? [], null, 2)}</pre>
            </section>
            <section className="panel stack">
              <h2>False Positives</h2>
              <pre className="text-preview">{JSON.stringify(benchmark.false_positives ?? [], null, 2)}</pre>
            </section>
            <section className="panel stack">
              <h2>Partial Matches</h2>
              <pre className="text-preview">{JSON.stringify(benchmark.partial_matches ?? [], null, 2)}</pre>
            </section>
            <section className="panel stack">
              <h2>Report</h2>
              <pre className="text-preview">{JSON.stringify(report ?? benchmark.report ?? {}, null, 2)}</pre>
            </section>
          </>
        ) : (
          <section className="panel muted">Loading...</section>
        )}
      </main>
    </AppShell>
  );
}

function Score({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <div className="muted small">{label}</div>
      <strong>{value ?? "-"}</strong>
    </div>
  );
}
