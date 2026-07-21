const CONFIGURED_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

export function resolveApiBaseUrl(currentHostname?: string): string {
  const browserHostname =
    currentHostname ?? (typeof window === "undefined" ? undefined : window.location.hostname);
  if (!browserHostname || !isLocalHostname(browserHostname)) {
    return CONFIGURED_API_BASE_URL;
  }

  try {
    const url = new URL(CONFIGURED_API_BASE_URL);
    if (isLocalHostname(url.hostname)) {
      url.hostname = browserHostname;
      return url.toString().replace(/\/$/, "");
    }
  } catch {
    return CONFIGURED_API_BASE_URL;
  }

  return CONFIGURED_API_BASE_URL;
}

export const API_BASE_URL = resolveApiBaseUrl();

export type ApiError = {
  detail?: string;
};

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers =
    init.body instanceof FormData
      ? init.headers
      : {
          "Content-Type": "application/json",
          ...(init.headers ?? {}),
        };
  const response = await fetch(`${resolveApiBaseUrl()}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });

  if (!response.ok) {
    let error: ApiError = {};
    try {
      error = await response.json();
    } catch {
      error = { detail: response.statusText };
    }
    throw new Error(error.detail ?? `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function apiFetchText(path: string, init: RequestInit = {}): Promise<string> {
  const response = await fetch(`${resolveApiBaseUrl()}${path}`, {
    ...init,
    credentials: "include",
    headers: init.headers,
  });

  if (!response.ok) {
    let error: ApiError = {};
    try {
      error = await response.json();
    } catch {
      error = { detail: response.statusText };
    }
    throw new Error(error.detail ?? `Request failed with ${response.status}`);
  }

  return response.text();
}

export async function apiFetchNoContent(path: string, init: RequestInit = {}): Promise<void> {
  const response = await fetch(`${resolveApiBaseUrl()}${path}`, {
    ...init,
    credentials: "include",
    headers: init.headers,
  });

  if (!response.ok) {
    let error: ApiError = {};
    try {
      error = await response.json();
    } catch {
      error = { detail: response.statusText };
    }
    throw new Error(error.detail ?? `Request failed with ${response.status}`);
  }
}
