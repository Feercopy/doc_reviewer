"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { archiveEtalon, getEtalon, publishEtalon, type EtalonRecord } from "@/lib/api/etalons";
import { formatDate, formatLabel } from "@/lib/format";

export default function EtalonDetailPage() {
  const params = useParams<{ etalonId: string }>();
  const [etalon, setEtalon] = useState<EtalonRecord | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    setEtalon(await getEtalon(params.etalonId));
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load etalon"));
  }, [params.etalonId]);

  async function runAction(action: "publish" | "archive") {
    setPending(true);
    setError("");
    try {
      setEtalon(action === "publish" ? await publishEtalon(params.etalonId) : await archiveEtalon(params.etalonId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update etalon");
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell>
      <main className="main stack">
        {error ? <section className="panel error">{error}</section> : null}
        {etalon ? (
          <>
            <section className="panel stack">
              <div className="toolbar">
                <div>
                  <h1>Etalon</h1>
                  <p className="muted">
                    {formatLabel(etalon.source)} · version {etalon.version}
                  </p>
                </div>
                <StatusBadge status={etalon.status} />
              </div>
              <div className="meta-grid">
                <div>
                  <div className="muted small">Type</div>
                  <strong>{formatLabel(etalon.document_type)}</strong>
                </div>
                <div>
                  <div className="muted small">Expected verdict</div>
                  <strong>{formatLabel(etalon.expected_verdict)}</strong>
                </div>
                <div>
                  <div className="muted small">Updated</div>
                  <strong>{formatDate(etalon.updated_at)}</strong>
                </div>
              </div>
              <div className="button-row">
                <Link className="secondary-link" href={`/annotation/${etalon.id}`}>
                  Edit
                </Link>
                <button className="secondary" disabled={pending || etalon.status !== "draft"} type="button" onClick={() => runAction("publish")}>
                  Publish
                </button>
                <button className="secondary" disabled={pending || etalon.status === "archived"} type="button" onClick={() => runAction("archive")}>
                  Archive
                </button>
              </div>
            </section>
            {etalon.defense_comments ? (
              <section className="panel stack">
                <h2>Defense Comments</h2>
                <pre className="text-preview">{etalon.defense_comments}</pre>
              </section>
            ) : null}
            <LayerTable title="Layer 1" rows={etalon.layer_1} />
            <LayerTable title="Layer 2" rows={etalon.layer_2} />
            <section className="panel stack">
              <h2>Full Etalon</h2>
              <pre className="text-preview">{JSON.stringify(etalon, null, 2)}</pre>
            </section>
          </>
        ) : (
          <section className="panel muted">Loading...</section>
        )}
      </main>
    </AppShell>
  );
}

function LayerTable({ title, rows }: { title: string; rows: Record<string, unknown>[] }) {
  return (
    <section className="panel stack">
      <h2>{title}</h2>
      {rows.length ? (
        <table>
          <tbody>
            {rows.map((row, index) => (
              <tr key={String(row.id ?? index)}>
                <td>{String(row.id ?? index + 1)}</td>
                <td>{String(row.title ?? row.check ?? row.finding ?? row.summary ?? "-")}</td>
                <td>{formatLabel(String(row.status ?? ""))}</td>
                <td>{formatLabel(String(row.severity ?? ""))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="muted">No rows.</div>
      )}
    </section>
  );
}
