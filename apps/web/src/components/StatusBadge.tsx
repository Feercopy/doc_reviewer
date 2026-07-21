import type { ParseStatus, RunStatus } from "@/lib/api/documents";

const statusTone: Record<string, "ok" | "info" | "danger" | "neutral" | "warning"> = {
  active: "ok",
  completed: "ok",
  queued: "info",
  running: "info",
  failed: "danger",
  cancelled: "danger",
  draft: "neutral",
  archived: "neutral",
  deleted: "neutral",
  unknown: "neutral",
};

export function StatusBadge({ status }: { status: ParseStatus | RunStatus | string }) {
  const normalizedStatus = String(status).toLowerCase();
  const tone = statusTone[normalizedStatus] ?? "neutral";
  const label = normalizedStatus.replaceAll("_", " ");

  return (
    <span className={`badge status-badge ${tone}`} aria-label={`Status: ${label}`} title={`Status: ${label}`}>
      <span className="badge-mark" aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}
