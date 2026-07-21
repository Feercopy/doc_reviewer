import { describe, expect, it } from "vitest";

import { appPath, normalizeBasePath, stripAppBasePath } from "./routing";

describe("routing helpers", () => {
  it("keeps local root deployments unprefixed", () => {
    expect(normalizeBasePath("")).toBe("");
    expect(normalizeBasePath("/")).toBe("");
    expect(appPath("/login", "")).toBe("/login");
    expect(appPath("documents", "")).toBe("/documents");
  });

  it("prefixes imperative navigation for subpath deployments", () => {
    expect(normalizeBasePath("doc-challanger/")).toBe("/doc-challanger");
    expect(appPath("/login", "/doc-challanger")).toBe("/doc-challanger/login");
    expect(appPath("documents/doc-id", "/doc-challanger")).toBe(
      "/doc-challanger/documents/doc-id",
    );
  });

  it("strips the deployment prefix before matching app routes", () => {
    expect(stripAppBasePath("/doc-challanger/documents/abc", "/doc-challanger")).toBe(
      "/documents/abc",
    );
    expect(stripAppBasePath("/documents/abc", "/doc-challanger")).toBe("/documents/abc");
    expect(stripAppBasePath("/doc-challanger", "/doc-challanger")).toBe("/");
  });
});
