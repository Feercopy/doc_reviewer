"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  importPastDefense,
  listEtalons,
  type EtalonRecord,
  type Verdict,
} from "@/lib/api/etalons";
import type { DocumentType } from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

export default function EtalonsPage() {
  const [etalons, setEtalons] = useState<EtalonRecord[]>([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    const response = await listEtalons();
    setEtalons(response.etalons);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load etalons"));
  }, []);

  async function submitPastDefense(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const form = new FormData(event.currentTarget);
      await importPastDefense(form);
      event.currentTarget.reset();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import past defense");
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell>
      <main className="main stack">
        <div className="toolbar">
          <div>
            <h1>Etalons</h1>
            <p className="muted">Drafts, active references, and past defenses</p>
          </div>
        </div>
        {error ? <section className="panel error">{error}</section> : null}
        <form className="panel stack" onSubmit={submitPastDefense}>
          <h2>Import Past Defense</h2>
          <div className="form-grid">
            <label>
              Title
              <input name="title" required />
            </label>
            <label>
              Type
              <select name="document_type" defaultValue={"gate_2" satisfies DocumentType}>
                <option value="gate_1">Gate 1</option>
                <option value="gate_2">Gate 2</option>
                <option value="gate_3">Gate 3</option>
                <option value="unknown">Unknown</option>
              </select>
            </label>
            <label>
              Expected verdict
              <select name="expected_verdict" defaultValue={"need_evidence" satisfies Verdict}>
                <option value="approve">Approve</option>
                <option value="approve_with_conditions">Approve with conditions</option>
                <option value="need_evidence">Need evidence</option>
                <option value="reject">Reject</option>
                <option value="unknown">Unknown</option>
              </select>
            </label>
            <label>
              Defense status
              <input name="real_defense_status" required />
            </label>
            <label>
              Defense date
              <input name="defense_date" type="date" />
            </label>
            <label>
              File
              <input name="file" required type="file" />
            </label>
          </div>
          <label>
            Defense comments
            <textarea name="defense_comments" required />
          </label>
          <label>
            Notes
            <textarea name="notes" />
          </label>
          <label className="checkbox-label">
            <input name="raw_file_visible_to_all" type="checkbox" value="true" />
            Raw file visible to all
          </label>
          <button disabled={pending} type="submit">
            Import
          </button>
        </form>
        <section className="panel">
          {etalons.length ? (
            <table>
              <thead>
                <tr>
                  <th>Etalon</th>
                  <th>Type</th>
                  <th>Verdict</th>
                  <th>Layers</th>
                  <th>Status</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {etalons.map((etalon) => (
                  <tr key={etalon.id}>
                    <td>
                      <strong>{formatLabel(etalon.source)}</strong>
                      <div className="muted">{etalon.id}</div>
                    </td>
                    <td>{formatLabel(etalon.document_type)}</td>
                    <td>{formatLabel(etalon.expected_verdict)}</td>
                    <td>
                      L1 {etalon.layer_1.length}
                      <div className="muted">L2 {etalon.layer_2.length}</div>
                    </td>
                    <td>
                      <StatusBadge status={etalon.status} />
                    </td>
                    <td>{formatDate(etalon.updated_at)}</td>
                    <td className="button-row">
                      <Link className="secondary-link" href={`/etalons/${etalon.id}`}>
                        Open
                      </Link>
                      <Link className="secondary-link" href={`/annotation/${etalon.id}`}>
                        Edit
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="muted">No etalons yet.</div>
          )}
        </section>
      </main>
    </AppShell>
  );
}
