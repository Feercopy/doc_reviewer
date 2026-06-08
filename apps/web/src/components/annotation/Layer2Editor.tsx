import type { EtalonLayer2Item } from "@/lib/api/etalons";

export function Layer2Editor({
  value,
  onChange,
}: {
  value: EtalonLayer2Item[];
  onChange: (value: EtalonLayer2Item[]) => void;
}) {
  return (
    <label>
      Layer 2
      <textarea
        className="mono-input"
        value={JSON.stringify(value, null, 2)}
        onChange={(event) => {
          const parsed = safeParseArray<EtalonLayer2Item>(event.target.value);
          if (parsed) {
            onChange(parsed);
          }
        }}
      />
    </label>
  );
}

function safeParseArray<T>(value: string): T[] | null {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? (parsed as T[]) : null;
  } catch {
    return null;
  }
}
