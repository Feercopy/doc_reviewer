"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { EtalonStatusActions } from "@/components/annotation/EtalonStatusActions";
import { Layer1Editor } from "@/components/annotation/Layer1Editor";
import { Layer2Editor } from "@/components/annotation/Layer2Editor";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  archiveEtalon,
  getEtalon,
  publishEtalon,
  updateEtalon,
  type EtalonLayer1Item,
  type EtalonLayer2Item,
  type EtalonRecord,
  type Verdict,
} from "@/lib/api/etalons";
import { formatLabel } from "@/lib/format";

export default function AnnotationPage() {
  const params = useParams<{ etalonId: string }>();
  const [etalon, setEtalon] = useState<EtalonRecord | null>(null);
  const [expectedVerdict, setExpectedVerdict] = useState<Verdict>("unknown");
  const [defenseComments, setDefenseComments] = useState("");
  const [keyFindings, setKeyFindings] = useState("");
  const [layer1, setLayer1] = useState<EtalonLayer1Item[]>([]);
  const [layer2, setLayer2] = useState<EtalonLayer2Item[]>([]);
  const [rawVisible, setRawVisible] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    const next = await getEtalon(params.etalonId);
    setEtalon(next);
    setExpectedVerdict(next.expected_verdict);
    setDefenseComments(next.defense_comments ?? "");
    setKeyFindings(next.key_findings.join("\n"));
    setLayer1(next.layer_1);
    setLayer2(next.layer_2);
    setRawVisible(next.raw_file_visible_to_all);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load etalon"));
  }, [params.etalonId]);

  async function save() {
    setPending(true);
    setError("");
    try {
      const updated = await updateEtalon(params.etalonId, {
        expected_verdict: expectedVerdict,
        defense_comments: defenseComments || null,
        key_findings: keyFindings.split("\n").map((item) => item.trim()).filter(Boolean),
        layer_1: layer1,
        layer_2: layer2,
        raw_file_visible_to_all: rawVisible,
      });
      setEtalon(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save etalon");
    } finally {
      setPending(false);
    }
  }

  async function lifecycle(action: "publish" | "archive") {
    setPending(true);
    setError("");
    try {
      setEtalon(action === "publish" ? await publishEtalon(params.etalonId) : await archiveEtalon(params.etalonId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell>
      <main className="main stack">
        {error ? <section className="panel error">{error}</section> : null}
        {etalon ? (
          <section className="panel stack">
            <div className="toolbar">
              <div>
                <h1>Annotation</h1>
                <p className="muted">{formatLabel(etalon.source)}</p>
              </div>
              <StatusBadge status={etalon.status} />
            </div>
            <div className="form-grid">
              <label>
                Expected verdict
                <select value={expectedVerdict} onChange={(event) => setExpectedVerdict(event.target.value as Verdict)}>
                  <option value="approve">Approve</option>
                  <option value="approve_with_conditions">Approve with conditions</option>
                  <option value="need_evidence">Need evidence</option>
                  <option value="reject">Reject</option>
                  <option value="unknown">Unknown</option>
                </select>
              </label>
              <label className="checkbox-label">
                <input checked={rawVisible} type="checkbox" onChange={(event) => setRawVisible(event.target.checked)} />
                Raw visible
              </label>
            </div>
            <label>
              Key findings
              <textarea value={keyFindings} onChange={(event) => setKeyFindings(event.target.value)} />
            </label>
            <label>
              Defense comments
              <textarea value={defenseComments} onChange={(event) => setDefenseComments(event.target.value)} />
            </label>
            <Layer1Editor value={layer1} onChange={setLayer1} />
            <Layer2Editor value={layer2} onChange={setLayer2} />
            <EtalonStatusActions
              status={etalon.status}
              pending={pending}
              onSave={save}
              onPublish={() => lifecycle("publish")}
              onArchive={() => lifecycle("archive")}
            />
          </section>
        ) : (
          <section className="panel muted">Loading...</section>
        )}
      </main>
    </AppShell>
  );
}
