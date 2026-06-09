import type { EtalonStatus } from "@/lib/api/etalons";

export function EtalonStatusActions({
  status,
  pending,
  onSave,
  onPublish,
  onArchive,
}: {
  status: EtalonStatus;
  pending: boolean;
  onSave: () => void;
  onPublish: () => void;
  onArchive: () => void;
}) {
  return (
    <div className="button-row">
      <button disabled={pending || status === "archived"} type="button" onClick={onSave}>
        Save draft
      </button>
      <button className="secondary" disabled={pending || status !== "draft"} type="button" onClick={onPublish}>
        Publish
      </button>
      <button className="danger" disabled={pending || status === "archived"} type="button" onClick={onArchive}>
        Archive
      </button>
    </div>
  );
}
