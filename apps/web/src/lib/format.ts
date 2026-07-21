export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  return value.replaceAll("_", " ");
}
