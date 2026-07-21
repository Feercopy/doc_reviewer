import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const repoSource = (path: string) => readFileSync(join(process.cwd(), "..", "..", path), "utf8");
const webSource = (path: string) => readFileSync(join(process.cwd(), path), "utf8");

describe("base path routing", () => {
  it("builds Next.js with a configurable deployment base path", () => {
    const nextConfig = repoSource("apps/web/next.config.ts");
    const dockerfile = repoSource("apps/web/Dockerfile.prod");
    const compose = repoSource("infra/docker-compose.prod.yml");

    expect(nextConfig).toContain("NEXT_PUBLIC_BASE_PATH");
    expect(nextConfig).toContain("basePath:");
    expect(dockerfile).toContain("ARG NEXT_PUBLIC_BASE_PATH=");
    expect(dockerfile).toContain("ENV NEXT_PUBLIC_BASE_PATH=${NEXT_PUBLIC_BASE_PATH}");
    expect(compose).toContain("NEXT_PUBLIC_BASE_PATH: ${NEXT_PUBLIC_BASE_PATH:-/doc-challanger}");
  });

  it("mounts the IC Agentic Review source in production API and worker containers", () => {
    const compose = repoSource("infra/docker-compose.prod.yml");

    expect(compose.match(/IC_AGENTIC_REVIEW_SOURCE_PATH: \/external\/ic-agentic-review/g)).toHaveLength(2);
    expect(
      compose.match(
        /\$\{IC_AGENTIC_REVIEW_HOST_PATH:\?IC_AGENTIC_REVIEW_HOST_PATH is required\}:\/external\/ic-agentic-review:ro/g,
      ),
    ).toHaveLength(2);
  });

  it("uses appPath for imperative redirects that Next Link cannot prefix", () => {
    const appShell = webSource("src/components/AppShell.tsx");
    const loginPage = webSource("src/app/login/page.tsx");
    const homePage = webSource("src/app/page.tsx");
    const adminPage = webSource("src/app/admin/page.tsx");
    const documentsPage = webSource("src/app/documents/page.tsx");
    const documentDetailPage = webSource("src/app/documents/[documentId]/page.tsx");
    const analysisPage = webSource("src/app/analyses/[analysisId]/page.tsx");

    expect(appShell).toContain('from "@/lib/routing"');
    expect(appShell).toContain('window.location.href = appPath("/login")');
    expect(appShell).toContain("stripAppBasePath(pathname)");
    expect(loginPage).toContain('window.location.href = appPath("/documents")');
    expect(homePage).toContain('redirect(appPath("/login"))');
    expect(adminPage).toContain('redirect(appPath("/admin/users"))');
    expect(documentsPage).toContain("window.location.href = appPath(`/documents/${document.id}`)");
    expect(documentDetailPage).toContain('window.location.href = appPath("/documents")');
    expect(documentDetailPage).toContain("window.location.href = appPath(`/analyses/${analysis.id}`)");
    expect(analysisPage).toContain(
      "window.location.href = appPath(`/documents/${analysis.document_id}`)",
    );
  });
});
