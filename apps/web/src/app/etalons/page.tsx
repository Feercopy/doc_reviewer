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
import { USER_SELECTABLE_DOCUMENT_TYPES, type DocumentType } from "@/lib/api/documents";
import { formatDate, formatLabel } from "@/lib/format";

export default function EtalonsPage() {
  const [etalons, setEtalons] = useState<EtalonRecord[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);

  async function refresh() {
    const response = await listEtalons();
    setEtalons(response.etalons);
  }

  useEffect(() => {
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load etalons"))
      .finally(() => setLoading(false));
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
            <p className="muted">Drafts, active references, and imported defense outcomes.</p>
          </div>
          <span className="badge info">{etalons.length} total</span>
        </div>
        {error ? <section className="panel error">{error}</section> : null}
        <form className="panel stack" onSubmit={submitPastDefense}>
          <div>
            <h2>Import Past Defense</h2>
            <p className="muted">Upload a historical defense package and capture its expected verdict and comments.</p>
          </div>
          <div className="form-grid">
            <label>
              Title
              <input name="title" required />
            </label>
            <label>
              Type
              <select name="document_type" defaultValue={"gate_2" satisfies DocumentType}>
                {USER_SELECTABLE_DOCUMENT_TYPES.map((item) => (
                  <option key={item} value={item}>
                    {formatLabel(item)}
                  </option>
                ))}
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
          <div className="button-row">
            <button disabled={pending} type="submit">
              {pending ? "Importing..." : "Import"}
            </button>
          </div>
        </form>
        <section className="panel stack">
          <div>
            <h2>Etalon Registry</h2>
            <p className="muted">Open a reference for review or continue annotation without changing its source trace.</p>
          </div>
          {loading ? <div className="muted">Loading etalons...</div> : null}
          {!loading && etalons.length === 0 ? <div className="muted">No etalons yet.</div> : null}
          {!loading && etalons.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Etalon</th>
                    <th>Type</th>
                    <th>Verdict</th>
                    <th>Layers</th>
                    <th>Defense</th>
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
                        <div className="muted small">{etalon.id}</div>
                      </td>
                      <td>{formatLabel(etalon.document_type)}</td>
                      <td>
                        <VerdictBadge verdict={etalon.expected_verdict} />
                      </td>
                      <td>
                        <span className="badge">L1 {etalon.layer_1.length}</span>{" "}
                        <span className="badge">L2 {etalon.layer_2.length}</span>
                      </td>
                      <td>{etalon.real_defense_status ? formatLabel(etalon.real_defense_status) : "-"}</td>
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
            </div>
          ) : null}
        </section>
      </main>
    </AppShell>
  );
}

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const tone = verdict === "approve" ? "ok" : verdict === "reject" ? "danger" : "info";
  return <span className={`badge ${tone}`}>{formatLabel(verdict)}</span>;
}
