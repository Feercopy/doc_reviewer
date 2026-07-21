const { expect, test } = require("@playwright/test");

const mainAnalysisResult = {
  verdict: "need_evidence",
  summary: "Needs stronger metric evidence.",
  assessment_markdown: "Оценка документа\nРекомендация: strengthen metric evidence before approval.",
  findings: [
    {
      id: "F1",
      severity: "high",
      title: "Metric proof is incomplete",
      evidence: "The document names traction but does not provide a cohort or control-group readout.",
    },
  ],
  checks: [
    {
      name: "Incrementality evidence",
      status: "partial",
      explanation: "The defense needs an experiment or comparable holdout to support impact claims.",
    },
  ],
  key_findings: ["Metric proof is incomplete"],
  layer_1_markdown: "Layer 1\nL1-001 - Metric proof is incomplete.",
  layer_1: [
    {
      id: "L1-001",
      severity: "high",
      issue: "The document claims traction without a cohort or control-group readout.",
      evidence: "The document names traction but does not provide a cohort or control-group readout.",
    },
  ],
  layer_2_markdown: "Layer 2\nL2-001 - Incrementality evidence is missing.",
  layer_2: [
    {
      id: "L2-001",
      parent_layer_1_id: "L1-001",
      status: "fail",
      severity: "high",
      question: "Is incrementality evidence tied to an experiment or comparable holdout?",
      answer: "NO",
      issue: "The claimed metric lift is not tied to an experiment or comparable holdout.",
      evidence: "No cohort, control group, or before-after guardrail is provided.",
    },
  ],
};

const devilsAdvocateResult = {
  run_mode: "full_ic_voting",
  native_markdown: [
    "Devil's Advocate - IC voting",
    "",
    "Pre-flight summary",
    "- Gate 2 document with missing incrementality proof.",
    "",
    "The Brutal Truth",
    "The defense still needs a control-group readout.",
    "",
    "The Tough Co-CEO Questions",
    "1. What is incremental impact?",
    "",
    "Actionable JTBDs",
    "1. Add experiment evidence.",
    "2. Show gross profit impact.",
    "3. Separate assumptions from proven traction.",
    "",
    "IC Decision",
    "Verdict: Rework",
  ].join("\n"),
  preflight_summary: ["Gate 2 document with missing incrementality proof."],
  brutal_truth: "The defense still needs a control-group readout.",
  detected_contradictions: [
    {
      section: "Metrics",
      title: "Incrementality is not proven",
      body: "The document claims traction but does not show an experiment or holdout.",
      comment_type: "missing_data",
      severity: "critical",
      citations: ["wiki-ic/risk-patterns.md"],
    },
  ],
  role_comments: [
    {
      voter: "MP",
      vote: "reject",
      rationale: "No incrementality proof.",
      comments: [
        {
          anchor_text: "incrementality proof",
          body: "Show a control group or comparable holdout before IC approval.",
          comment_type: "missing_data",
          severity: "critical",
        },
      ],
    },
    {
      voter: "CPO",
      vote: "reject",
      rationale: "Funnel target needs evidence.",
      comments: [
        {
          anchor_text: "funnel target",
          body: "Tie the target to observed cohort behavior and product changes.",
          comment_type: "methodology_issue",
          severity: "important",
        },
      ],
    },
    {
      voter: "TechDir",
      vote: "reject",
      rationale: "No experiment delta.",
      comments: [
        {
          anchor_text: "experiment delta",
          body: "Provide the experiment readout and guardrails before scaling.",
          comment_type: "missing_data",
          severity: "important",
        },
      ],
    },
    {
      voter: "VertDir",
      vote: "approve",
      rationale: "Direction is useful.",
      comments: [
        {
          anchor_text: "direction is useful",
          body: "Continue vertical rollout only after the evidence gates are satisfied.",
          comment_type: "risk_not_addressed",
          severity: "minor",
        },
      ],
    },
  ],
  tough_questions: [
    { question: "What is incremental impact?", persona: "Managing Partner" },
    { question: "Which cohort proves the lift?", persona: "CPO" },
    { question: "Where is the experiment delta?", persona: "Technical Director" },
  ],
  actionable_jtbds: [
    "Add a hard incrementality KPI gate.",
    "Show gross profit and cumulative uplift.",
    "Separate proven traction from assumptions.",
  ],
  anchored_comments: [
    {
      id: "C1",
      anchor: "metrics",
      comment: "Committee will ask for incrementality evidence.",
      severity: "high",
    },
  ],
  trailer: {
    executive_summary: "Needs evidence.",
    key_risks: ["weak proof"],
    missing_evidence: ["control group"],
    next_steps: ["add experiment readout"],
  },
  ic_decision: {
    verdict: "rework",
    vote_tally: { MP: "reject", CPO: "reject", TechDir: "reject", VertDir: "approve" },
    rationale: "Missing proof.",
    conditions: ["Add experiment or holdout evidence."],
    heuristics_fired: ["missing-proof"],
    patterns_fired: ["experimental-traction-gap"],
    precedents_anchored: ["ic-2025-incrementality"],
    next_ic: "After metric evidence is added",
  },
  predicted_questions: ["What is incremental impact?"],
  consulted_wiki_pages: ["risk-patterns.md"],
  source_citations: ["wiki-ic/risk-patterns.md"],
  retrieval: {
    retrieval_mode: "deterministic_topk",
    retrieval_version: "lexical-v1",
    corpus_fingerprint: "corpus-fingerprint",
    query_fingerprint: "query-fingerprint",
    selected_cases: ["wiki-ic/cases/incrementality.md"],
    selected_patterns: ["wiki-ic/patterns/missing-proof.md"],
    selected_heuristics: ["wiki-ic/heuristics/evidence-gates.md"],
    selected_questions: ["What is the control group?"],
  },
};

test.setTimeout(120000);

test("admin creates user and user completes the MVP document analysis flow", async ({ page }) => {
  const baseUrl = process.env.E2E_BASE_URL;
  const apiBaseUrl = resolveApiBaseUrl(baseUrl);
  const adminLogin = process.env.E2E_ADMIN_LOGIN;
  const adminPassword = process.env.E2E_ADMIN_PASSWORD;
  const userLogin = `e2e-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const userPassword = "e2e-strong-password";

  await page.goto(`${baseUrl}/login`);
  await fillAndSubmitSignIn(page, adminLogin, adminPassword);
  await expect(page).toHaveURL(/\/documents/);

  await saveDummyProviderKey(page, apiBaseUrl);

  await page.goto(`${baseUrl}/admin/users`);
  await page.getByLabel("Login").fill(userLogin);
  await page.getByLabel("Display name").fill("E2E User");
  await page.getByLabel("Initial password").fill(userPassword);
  await page.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByText(userLogin)).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await fillAndSubmitSignIn(page, userLogin, userPassword);
  await expect(page).toHaveURL(/\/documents/);

  await page.goto(`${baseUrl}/documents`);
  await expect(page.getByRole("region", { name: "Upload document" })).toBeVisible();

  await page.getByLabel("Title").fill("E2E Gate 2 document");
  await page.getByLabel("Manual type").selectOption("gate_2");
  await page.getByLabel("File").setInputFiles({
    name: "gate2-e2e.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      [
        "# Gate 2 investment defense",
        "",
        "This document describes MVP traction, monetization assumptions, and metrics.",
        "It intentionally needs stronger metric evidence for committee review.",
      ].join("\n"),
    ),
  });
  await page.getByRole("button", { name: "Upload document" }).click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f-]+$/);

  const documentId = page.url().split("/").pop();
  await waitForDocumentParsed(page, apiBaseUrl, documentId);
  await page.reload();
  await expect(page.getByText("completed").first()).toBeVisible();
  await expect(page.getByText("This document describes MVP traction")).toBeVisible();

  const analysis = await apiJson(page, apiBaseUrl, `/documents/${documentId}/analyses`, {
    method: "POST",
    body: {
      provider: "openai_compatible",
      model: "openai/gpt-5.5",
      document_type_override: "gate_2",
      run_parameters: {
        snapshot_mode: "development_current",
        mock_provider_result: {
          structured_text: JSON.stringify(mainAnalysisResult),
          raw_output: "raw e2e main analysis",
          input_tokens: 10,
          output_tokens: 20,
          latency_ms: 30,
        },
        predicted_comments_mock_provider_result: {
          structured_text: JSON.stringify(devilsAdvocateResult),
          raw_output: "raw e2e predicted comments",
          input_tokens: 7,
          output_tokens: 11,
          latency_ms: 25,
        },
      },
    },
  });

  await waitForCompletedAnalysis(page, apiBaseUrl, analysis.id);
  await page.goto(`${baseUrl}/analyses/${analysis.id}`);
  await expect(page.getByRole("heading", { name: "Analysis" })).toBeVisible();
  await expect(page.getByText("Needs stronger metric evidence.", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Рекомендация: strengthen metric evidence before approval.").first()).toBeVisible();
  await page.getByRole("button", { name: "Full Output" }).click();
  await expect(page.getByRole("heading", { name: "Devil's Advocate" })).toBeVisible();
  await expect(page.getByText("What is incremental impact?", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "Leave feedback" }).click();
  await page.getByRole("textbox", { name: "Your comments (optional)" }).fill("E2E feedback: result is useful for review.");
  await page.getByRole("button", { name: "Submit feedback" }).click();
  await expect(page.getByText("Feedback saved")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create etalon draft" })).toHaveCount(0);
});

function resolveApiBaseUrl(baseUrl) {
  if (process.env.E2E_API_BASE_URL) {
    return process.env.E2E_API_BASE_URL.replace(/\/$/, "");
  }
  const url = new URL(baseUrl);
  url.port = "8000";
  return url.toString().replace(/\/$/, "");
}

async function fillAndSubmitSignIn(page, login, password) {
  const loginInput = page.getByLabel("Login");
  const passwordInput = page.getByLabel("Password");
  const submit = page.getByRole("button", { name: "Sign in" });

  await expect(loginInput).toBeVisible();
  await expect(passwordInput).toBeVisible();

  for (let attempt = 0; attempt < 3; attempt += 1) {
    await loginInput.fill("");
    await passwordInput.fill("");
    await loginInput.click();
    await loginInput.pressSequentially(login);
    await passwordInput.click();
    await passwordInput.pressSequentially(password);
    try {
      await expect(submit).toBeEnabled({ timeout: 1000 });
      await submit.click();
      return;
    } catch (error) {
      if (attempt === 2) {
        throw error;
      }
      await page.waitForTimeout(250);
    }
  }
}

async function saveDummyProviderKey(page, apiBaseUrl) {
  await apiJson(page, apiBaseUrl, "/settings/provider-keys/openai_compatible", {
    method: "PUT",
    body: {
      api_key: "sk-e2e-local-test",
      base_url: null,
      default_model: "openai/gpt-5.5",
      available_models: ["openai/gpt-5.5"],
    },
  });
}

async function waitForDocumentParsed(page, apiBaseUrl, documentId) {
  return waitFor(page, "document parse completion", async () => {
    const document = await apiJson(page, apiBaseUrl, `/documents/${documentId}`);
    if (document.parse_status === "failed") {
      throw new Error(document.parse_error || "document parse failed");
    }
    return document.parse_status === "completed" ? document : null;
  });
}

async function waitForCompletedAnalysis(page, apiBaseUrl, analysisId) {
  return waitFor(page, "analysis and predicted comments completion", async () => {
    const analysis = await apiJson(page, apiBaseUrl, `/analyses/${analysisId}`);
    if (analysis.status === "failed") {
      throw new Error(analysis.error_message || "analysis failed");
    }
    if (analysis.status !== "completed") {
      return null;
    }
    if (!analysis.predicted_comment_run) {
      return null;
    }
    if (analysis.predicted_comment_run.status === "failed") {
      throw new Error(analysis.predicted_comment_run.error_message || "predicted comments failed");
    }
    return analysis.predicted_comment_run.status === "completed" ? analysis : null;
  });
}

async function waitFor(page, description, condition, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const result = await condition();
      if (result) {
        return result;
      }
    } catch (error) {
      lastError = error;
    }
    await page.waitForTimeout(750);
  }
  throw new Error(`Timed out waiting for ${description}${lastError ? `: ${lastError.message}` : ""}`);
}

async function apiJson(page, apiBaseUrl, path, options = {}) {
  const result = await page.evaluate(
    async ({ apiBaseUrl: evaluatedApiBaseUrl, path: evaluatedPath, options: evaluatedOptions }) => {
      const response = await fetch(`${evaluatedApiBaseUrl}${evaluatedPath}`, {
        method: evaluatedOptions.method || "GET",
        credentials: "include",
        headers:
          evaluatedOptions.body === undefined
            ? evaluatedOptions.headers || {}
            : { "Content-Type": "application/json", ...(evaluatedOptions.headers || {}) },
        body: evaluatedOptions.body === undefined ? undefined : JSON.stringify(evaluatedOptions.body),
      });
      const text = await response.text();
      let body = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = text;
      }
      return { ok: response.ok, status: response.status, body };
    },
    { apiBaseUrl, path, options },
  );

  if (!result.ok) {
    const detail =
      result.body && typeof result.body === "object" && "detail" in result.body ? result.body.detail : result.body;
    throw new Error(`API ${path} failed with ${result.status}: ${detail || "no response body"}`);
  }
  return result.body;
}
