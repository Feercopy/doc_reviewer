# Etalons and Annotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support etalon creation from imported defense documents, manual annotation, and post-annotation of AI analysis results.

**Architecture:** Etalons are structured rows tied to documents. MVP supports draft creation from analysis and admin activation; annotator workflows are modeled and partially implemented so the role can be enabled without schema changes.

**Tech Stack:** FastAPI, SQLAlchemy JSONB, Next.js forms, Pydantic validation, pytest.

---

## Files

- Create: `apps/api/app/services/etalons.py`
- Create: `apps/api/app/routers/etalons.py`
- Create: `apps/api/app/schemas/etalons.py`
- Create: `apps/api/tests/test_etalons.py`
- Create: `apps/web/src/app/etalons/page.tsx`
- Create: `apps/web/src/app/etalons/[etalonId]/page.tsx`
- Create: `apps/web/src/app/annotation/[etalonId]/page.tsx`
- Create: `apps/web/src/components/annotation/Layer1Editor.tsx`
- Create: `apps/web/src/components/annotation/Layer2Editor.tsx`
- Create: `apps/web/src/components/annotation/EtalonStatusActions.tsx`

## Etalon JSON Shapes

Layer 1 item:

```json
{
  "id": "L1-001",
  "dimension": "Traction credibility",
  "status": "FAIL",
  "severity": "HIGH",
  "title": "Traction does not prove scaling",
  "summary": "The document extrapolates pilot results without showing scaling evidence.",
  "evidence": [
    {
      "quote": "source quote",
      "location": "page 5 / section Metrics"
    }
  ],
  "recommendation": "Add cohort analysis, baseline, confidence intervals, and guardrail metrics.",
  "confidence": 0.8
}
```

Layer 2 item:

```json
{
  "id": "L2-014",
  "parent_layer_1_id": "L1-001",
  "check": "Is there evidence of effect incrementality?",
  "status": "PARTIAL",
  "severity": "MEDIUM",
  "finding": "Incrementality is claimed but the estimation method is missing.",
  "evidence": [
    {
      "quote": "source quote",
      "location": "page 8"
    }
  ],
  "expected_fix": "Show test methodology, control group, sample size, and significance.",
  "confidence": 0.76
}
```

## API Endpoints

```text
GET /etalons
GET /etalons/{etalon_id}
POST /analyses/{analysis_id}/etalon-draft
POST /documents/past-defense
PATCH /etalons/{etalon_id}
POST /etalons/{etalon_id}/publish
POST /etalons/{etalon_id}/archive
GET /annotation/queue
```

## Tasks

### Task 1: Etalon Validation

- [ ] Add Pydantic schemas for Layer 1, Layer 2, evidence, and etalon payloads.
- [ ] Validate that every `parent_layer_1_id` in Layer 2 points to an existing Layer 1 item.
- [ ] Validate allowed statuses and severities.
- [ ] Add tests for valid payload, orphan Layer 2, invalid severity, and missing expected verdict.

Acceptance:

- invalid etalon payloads fail before database write;
- all Layer 2 rows have valid Layer 1 parent IDs.

### Task 2: Draft From Analysis

- [ ] Implement `POST /analyses/{analysis_id}/etalon-draft`.
- [ ] Validate current user can read the analysis.
- [ ] Copy Layer 1, Layer 2, key findings, and verdict from analysis structured output.
- [ ] Set source `ai_post_annotation`.
- [ ] Set status `draft` for normal users.
- [ ] Allow `active` only for admin or annotator.

Acceptance:

- user can create own draft from analysis;
- user cannot create draft from another user's analysis;
- draft preserves links to source document and author.

### Task 3: Past Defense Import

- [ ] Implement upload endpoint for document with defense comments, real status, date, and notes.
- [ ] Reuse document upload and parsing workflow.
- [ ] Create a draft etalon shell after upload.
- [ ] Store defense comments in etalon fields.

Acceptance:

- past-defense upload stores raw document and comments;
- user receives an etalon draft to edit.

### Task 4: Annotation Workspace

- [ ] Build editor for expected verdict.
- [ ] Build Layer 1 editor with add, edit, delete.
- [ ] Build Layer 2 editor with add, edit, delete, parent reassignment.
- [ ] Build merge action that combines two Layer 2 items into one item with merged evidence.
- [ ] Build severity and status selectors.
- [ ] Build save draft action.
- [ ] Build publish action for admin and annotator.

Acceptance:

- annotator can edit AI-created blocks;
- normal user can save draft;
- normal user cannot publish active etalon.

### Task 5: Etalon List and Detail

- [ ] Implement etalon list with type, summary, expected verdict, Layer 1 count, Layer 2 count, author, status, created date.
- [ ] Implement detail page with expected verdict, Layer 1, Layer 2, defense comments, and change timestamps.
- [ ] Enforce raw-file visibility rules.

Acceptance:

- all authenticated users can see active structured etalons;
- raw etalon file is only visible when public or when admin owns permission.

## Verification

Run:

```bash
pytest apps/api/tests/test_etalons.py -q
```

Expected:

- etalon creation, validation, authorization, draft, publish, and archive tests pass.

