import { apiFetch } from "@/lib/api/client";

export type DocumentAccessGrantItem = { analysis_id: string; logins: string[] };
export type DocumentAccessGrantResult = { analyses: number; grants_created: number; grants_existing: number };

export function grantDocumentAccess(items: DocumentAccessGrantItem[]): Promise<DocumentAccessGrantResult> {
  return apiFetch<DocumentAccessGrantResult>("/admin/documents/access/batch", {
    method: "POST",
    body: JSON.stringify({ items }),
  });
}
