import { apiFetch } from "./client";
import type { DocumentType } from "./documents";

export type SkillRecord = {
  id: string;
  name: string;
  description: string;
  version: string;
  skill_type: string;
  supported_document_types: DocumentType[];
  result_schema_path: string;
  status: string;
  source_snapshot: {
    source_type: string;
    source_uri: string | null;
    source_entrypoint: string | null;
    source_revision: string | null;
    source_fingerprint: string | null;
    source_metadata: Record<string, unknown>;
  };
};

export async function listSkills(): Promise<{ skills: SkillRecord[] }> {
  return apiFetch<{ skills: SkillRecord[] }>("/skills");
}
