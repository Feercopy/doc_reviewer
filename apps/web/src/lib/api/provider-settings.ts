import { apiFetch } from "./client";
import type { Provider } from "./documents";

export type ProviderKeyRecord = {
  provider: Provider;
  base_url: string | null;
  default_model: string;
  available_models: string[];
  api_key_fingerprint: string;
  has_key: boolean;
};

export type ProviderKeysListResponse = {
  provider_keys: ProviderKeyRecord[];
};

export type ProviderKeyTestResponse = {
  provider: Provider;
  status: string;
  message: string;
  default_model: string | null;
  base_url: string | null;
};

export type ProviderModelOptions = {
  provider: Provider;
  default_model: string;
  available_models: string[];
  has_key: boolean;
};

export type ProviderModelOptionsListResponse = {
  provider_models: ProviderModelOptions[];
};

export function getProviderDefaultModel(providerKeys: Pick<ProviderKeyRecord, "provider" | "default_model">[], provider: Provider): string {
  return providerKeys.find((item) => item.provider === provider)?.default_model ?? "";
}

export async function listProviderKeys(): Promise<ProviderKeysListResponse> {
  return apiFetch<ProviderKeysListResponse>("/settings/provider-keys");
}

export async function listProviderModels(): Promise<ProviderModelOptionsListResponse> {
  return apiFetch<ProviderModelOptionsListResponse>("/settings/provider-models");
}

export async function saveProviderKey(
  provider: Provider,
  payload: { api_key: string; base_url?: string | null; default_model: string; available_models?: string[] },
): Promise<ProviderKeyRecord> {
  return apiFetch<ProviderKeyRecord>(`/settings/provider-keys/${provider}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function updateProviderKeySettings(
  provider: Provider,
  payload: { default_model: string; available_models: string[] },
): Promise<ProviderKeyRecord> {
  return apiFetch<ProviderKeyRecord>(`/settings/provider-keys/${provider}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteProviderKey(provider: Provider): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/settings/provider-keys/${provider}`, { method: "DELETE" });
}

export async function testProviderKey(provider: Provider): Promise<ProviderKeyTestResponse> {
  return apiFetch<ProviderKeyTestResponse>(`/settings/provider-keys/${provider}/test`, { method: "POST" });
}
