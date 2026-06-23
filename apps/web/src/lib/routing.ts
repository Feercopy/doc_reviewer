const RAW_APP_BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export const APP_BASE_PATH = normalizeBasePath(RAW_APP_BASE_PATH);

export function normalizeBasePath(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed === "/") {
    return "";
  }

  const withoutEdges = trimmed.replace(/^\/+|\/+$/g, "");
  return withoutEdges ? `/${withoutEdges}` : "";
}

export function appPath(path: string, basePath = APP_BASE_PATH): string {
  const normalizedBasePath = normalizeBasePath(basePath);
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  if (normalizedPath === "/") {
    return normalizedBasePath || "/";
  }

  return `${normalizedBasePath}${normalizedPath}`;
}

export function stripAppBasePath(pathname: string, basePath = APP_BASE_PATH): string {
  const normalizedBasePath = normalizeBasePath(basePath);
  if (!normalizedBasePath || pathname === normalizedBasePath) {
    return pathname === normalizedBasePath ? "/" : pathname;
  }

  if (pathname.startsWith(`${normalizedBasePath}/`)) {
    return pathname.slice(normalizedBasePath.length) || "/";
  }

  return pathname;
}
