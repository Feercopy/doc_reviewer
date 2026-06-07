# Frontend UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP web interface for login, documents, upload, analysis results, etalons, annotation, benchmarks, settings, and admin.

**Architecture:** Use Next.js App Router with authenticated layouts, API client modules, and focused route-level screens. UI should be utilitarian and dense enough for repeated review work, not a landing page.

**Tech Stack:** Next.js, React, TypeScript, TanStack Query, Tailwind CSS, lucide-react, Playwright.

---

## Files

- Create: `apps/web/src/app/layout.tsx`
- Create: `apps/web/src/app/(app)/layout.tsx`
- Create: `apps/web/src/app/login/page.tsx`
- Create: `apps/web/src/app/documents/page.tsx`
- Create: `apps/web/src/app/documents/upload/page.tsx`
- Create: `apps/web/src/app/documents/[documentId]/page.tsx`
- Create: `apps/web/src/app/analyses/[analysisId]/page.tsx`
- Create: `apps/web/src/app/benchmarks/page.tsx`
- Create: `apps/web/src/app/benchmarks/[benchmarkId]/page.tsx`
- Create: `apps/web/src/app/etalons/page.tsx`
- Create: `apps/web/src/app/etalons/[etalonId]/page.tsx`
- Create: `apps/web/src/app/annotation/[etalonId]/page.tsx`
- Create: `apps/web/src/app/settings/page.tsx`
- Create: `apps/web/src/app/admin/page.tsx`
- Create: `apps/web/src/components/nav/AppShell.tsx`
- Create: `apps/web/src/components/ui/StatusBadge.tsx`
- Create: `apps/web/src/components/ui/VerdictBadge.tsx`
- Create: `apps/web/src/components/ui/DataTable.tsx`
- Create: `apps/web/src/lib/api/client.ts`
- Create: `apps/web/tests/e2e/mvp-flow.spec.ts`

## Navigation

Authenticated navigation:

- Documents
- Upload
- Etalons
- Benchmarks
- Settings
- Admin, visible only for `admin`

No marketing home page is needed. The first authenticated screen is Documents.

## Design Rules

- Use compact tables for repeated records.
- Use badges for verdict, status, severity, provider, and document type.
- Use tabs for result sections: Summary, Layer 1, Layer 2, Predicted Comments, Full Output, Raw Output.
- Use icon buttons with tooltips for repeated row actions.
- Avoid nested cards; use full-width panels and tables.
- Use restrained palette: neutral surfaces, green for approve, amber for conditions/partial, red for reject/fail, blue for informational links.

## Page Requirements

### Login

Fields:

- login;
- password.

States:

- loading;
- invalid credentials;
- blocked user;
- success redirect.

### Documents

Columns:

- title;
- type;
- uploaded at;
- last verdict;
- analysis count;
- last analysis status;
- actions.

Actions:

- open;
- run new analysis;
- create etalon from result when analysis exists.

### Upload

Controls:

- drag-and-drop file zone;
- title input;
- optional document type selector;
- provider/model fields disabled until parse completes;
- supported formats note.

After upload:

- show parse status;
- show detected type and confidence;
- allow manual type correction;
- show start analysis action.

### Analysis Result

Sections:

- top card with document, type, date, verdict, provider, model, skill version, status;
- short summary;
- 3 to 7 key problems;
- 3 to 7 recommendations;
- Layer 1 dimensions;
- Layer 2 atomic checks;
- mode-aware Devil's Advocate / predicted-comments block:
  - default `ic_voting_full`: anchored reviewer comments, brutal truth, detected contradictions, tough questions, actionable JTBDs, IC decision, consulted wiki pages;
  - optional `/ic:query` modes: cited adversarial findings, likely questions or comments, evidence gaps, remediation tasks when present;
- full structured output;
- admin-only raw output;
- feedback form.

### Etalons

List columns:

- title;
- type;
- expected verdict;
- Layer 1 count;
- Layer 2 count;
- author;
- status;
- benchmark usage count.

Detail:

- expected verdict;
- Layer 1;
- Layer 2;
- defense comments;
- history metadata.

### Annotation

Controls:

- expected verdict selector;
- Layer 1 editor;
- Layer 2 editor;
- evidence list editor;
- severity selector;
- status selector;
- save draft;
- publish when allowed.

### Benchmarks

List columns:

- name;
- provider/model;
- skill/version;
- status;
- overall score;
- Layer 1 score;
- Layer 2 score;
- started by;
- date.

Result:

- score cards;
- per-document results;
- missed findings;
- false positives;
- partial matches;
- recommendations.

### Settings

Provider settings:

- OpenAI-compatible API key;
- OpenAI-compatible base URL;
- OpenAI-compatible default model;
- Claude API key;
- Claude default model;
- test connection buttons;
- masked saved key display;
- delete key.

### Admin

Sections:

- users;
- documents;
- analyses;
- skills;
- etalons;
- benchmarks;
- feedback.

## Tasks

### Task 1: App Shell and Auth Guard

- [ ] Build app shell with sidebar navigation.
- [ ] Implement `/auth/me` loading.
- [ ] Redirect unauthenticated users to `/login`.
- [ ] Hide admin nav for non-admin users.

Acceptance:

- unauthenticated user cannot reach app pages;
- authenticated user sees Documents first.

### Task 2: Reusable UI Components

- [ ] Build `StatusBadge`.
- [ ] Build `VerdictBadge`.
- [ ] Build `DataTable`.
- [ ] Build empty, loading, and error states.

Acceptance:

- tables do not shift layout when rows load;
- long text wraps cleanly on desktop and mobile.

### Task 3: Document Screens

- [ ] Build document list.
- [ ] Build upload flow.
- [ ] Build document detail with parse status and type override.
- [ ] Add run analysis action.

Acceptance:

- user can complete upload and reach document detail;
- manual type correction is visible and saved.

### Task 4: Analysis Result Screen

- [ ] Build top card.
- [ ] Build summary.
- [ ] Build Layer 1 and Layer 2 views.
- [ ] Build Devil's Advocate / predicted-comments block.
- [ ] Build full output and raw output sections.
- [ ] Build feedback form.

Acceptance:

- result page shows all required fields from source spec;
- result page shows Devil's Advocate critique when `devils_advocate_predefense` completed;
- raw output is visible only to admin.

### Task 5: Etalon, Annotation, and Benchmark Screens

- [ ] Build etalon list and detail.
- [ ] Build annotation editor.
- [ ] Build benchmark list, launch form, and result page.

Acceptance:

- user can create etalon draft from result and edit it;
- benchmark result has separate Layer 1 and Layer 2 sections.

### Task 6: Settings and Admin Screens

- [ ] Build provider key settings.
- [ ] Build admin dashboard sections.
- [ ] Add filters for admin documents, analyses, feedback.

Acceptance:

- API keys are masked after save;
- admin can manage users and inspect analysis metadata.

### Task 7: End-to-End UI Test

- [ ] Add Playwright test for:
  - admin login;
  - user creation;
  - user login;
  - document upload;
  - parse status view;
  - analysis launch with mocked provider;
  - result view;
  - feedback submission;
  - etalon draft creation.

Acceptance:

- Playwright test passes in local Docker stack with mocked provider.

## Verification

Run:

```bash
npm --prefix apps/web run test
npm --prefix apps/web run e2e
```

Expected:

- component tests pass;
- MVP flow passes with mocked backend/provider fixtures.
