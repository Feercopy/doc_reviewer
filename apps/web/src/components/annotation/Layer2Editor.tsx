"use client";

import { useEffect, useMemo, useState } from "react";

import type { EtalonLayer2Item } from "@/lib/api/etalons";

export function Layer2Editor({
  value,
  onChange,
}: {
  value: EtalonLayer2Item[];
  onChange: (value: EtalonLayer2Item[]) => void;
}) {
  const formattedValue = useMemo(() => JSON.stringify(value, null, 2), [value]);
  const [draft, setDraft] = useState(formattedValue);
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(formattedValue);
    setError("");
  }, [formattedValue]);

  function updateDraft(nextDraft: string) {
    setDraft(nextDraft);
    const result = parseArrayDraft<EtalonLayer2Item>(nextDraft);
    if (result.ok) {
      setError("");
      onChange(result.value);
    } else {
      setError(result.error);
    }
  }

  return (
    <>
      <div>
        <h2>Layer 2</h2>
        <p className="muted">Atomic checks linked to Layer 1 findings.</p>
      </div>
      <label>
        Layer 2 JSON
        <textarea
          className="mono-input"
          value={draft}
          onChange={(event) => updateDraft(event.target.value)}
        />
        {error ? <span className="error small">{error}</span> : null}
      </label>
    </>
  );
}

type ParseResult<T> = { ok: true; value: T[] } | { ok: false; error: string };

function parseArrayDraft<T>(value: string): ParseResult<T> {
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      return { ok: false, error: "JSON must be an array." };
    }
    return { ok: true, value: parsed as T[] };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "Invalid JSON." };
  }
}
