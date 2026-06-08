import type { EtalonLayer1Item } from "@/lib/api/etalons";

export function Layer1Editor({
  value,
  onChange,
}: {
  value: EtalonLayer1Item[];
  onChange: (value: EtalonLayer1Item[]) => void;
}) {
  return (
    <label>
      Layer 1
      <textarea
        className="mono-input"
        value={JSON.stringify(value, null, 2)}
        onChange={(event) => {
          const parsed = safeParseArray<EtalonLayer1Item>(event.target.value);
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
