import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("settings provider keys page", () => {
  it("lets saved keys edit model settings without replacing the key secret", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const savedKeysSource = pageSource.slice(
      pageSource.indexOf("<h2>Saved Provider Keys</h2>"),
      pageSource.indexOf("</section>", pageSource.indexOf("<h2>Saved Provider Keys</h2>")),
    );

    expect(pageSource).toContain("updateProviderKeySettings");
    expect(pageSource).toContain("async function saveModelSettings");
    expect(savedKeysSource).toContain("Edit");
    expect(savedKeysSource).toContain("Save");
    expect(savedKeysSource).toContain("Cancel");
    expect(savedKeysSource).toContain('aria-label={`Default model for ${item.provider.replaceAll("_", " ")}`}');
    expect(savedKeysSource).toContain('aria-label={`Model allowlist for ${item.provider.replaceAll("_", " ")}`}');
  });
});
