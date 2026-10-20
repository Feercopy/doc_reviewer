import { NextRequest, NextResponse } from "next/server";

import { appPath, stripAppBasePath } from "./lib/routing";

const internalApiBaseUrl = process.env.INTERNAL_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function middleware(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_EXTERNAL_ACCESS_DISABLED !== "true") {
    return NextResponse.next();
  }

  const path = stripAppBasePath(request.nextUrl.pathname);
  if (path === "/transition" || path === "/login") {
    return NextResponse.next();
  }

  const cookie = request.headers.get("cookie");
  if (!cookie) {
    return redirectToTransition(request);
  }

  try {
    const response = await fetch(`${internalApiBaseUrl}/auth/me`, {
      headers: { cookie },
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (response.ok && (await response.json()).role === "admin") {
      return NextResponse.next();
    }
  } catch {
    return redirectToTransition(request);
  }

  return redirectToTransition(request);
}

function redirectToTransition(request: NextRequest) {
  const publicOrigin = process.env.PUBLIC_WEB_ORIGIN || request.url;
  const response = NextResponse.redirect(new URL(appPath("/transition"), publicOrigin));
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export const config = {
  matcher: ["/((?!_next/|favicon.ico|robots.txt|sitemap.xml).*)"],
};
