# Documents, Parsing, and Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users upload supported documents, store raw files, extract text, detect document type, and manage document history with correct ownership.

**Architecture:** The API accepts uploads and stores raw files under a deterministic storage path. Parsing runs in the worker, and the backend persists parse status, parsed text, detected type, confidence, and explanation.

**Tech Stack:** FastAPI multipart upload, local filesystem storage, RQ, python-docx, pypdf, Markdown/plain text readers, SQLAlchemy.

---

## Files

- Create: `apps/api/app/storage/local.py`
- Create: `apps/api/app/services/documents.py`
- Create: `apps/api/app/services/document_type_detector.py`
- Create: `apps/api/app/routers/documents.py`
- Create: `apps/api/app/schemas/documents.py`
- Create: `apps/worker/jobs/parse_document.py`
- Create: `apps/worker/parsers/docx_parser.py`
- Create: `apps/worker/parsers/pdf_parser.py`
- Create: `apps/worker/parsers/text_parser.py`
- Create: `apps/api/tests/test_documents_upload.py`
- Create: `apps/worker/tests/test_document_parsers.py`
- Create: `apps/web/src/app/documents/page.tsx`
- Create: `apps/web/src/app/documents/upload/page.tsx`
- Create: `apps/web/src/app/documents/[documentId]/page.tsx`

## Supported File Types

MVP supports:

- `.docx`;
- `.pdf`;
- `.md`;
- `.txt`.

Reject unsupported files with `415 Unsupported Media Type`.

Maximum upload size for MVP: `25 MB`.

## Storage Layout

Raw files:

```text
{STORAGE_ROOT}/documents/{owner_id}/{document_id}/raw/{sha256}-{safe_original_filename}
```

Parser artifacts:

```text
{STORAGE_ROOT}/documents/{owner_id}/{document_id}/parsed/parsed.txt
```

Rules:

- Never serve a storage path directly from user input.
- Always load document row first, then authorize, then resolve storage path.
- Use SHA-256 for deduplication and traceability.
- Keep the original filename in metadata and in the safe storage filename.

## Document Type Detection

Implement deterministic heuristic detection for MVP:

- `Gate 1` when text contains strong signals: `Gate 1`, `problem`, `hypothesis`, `opportunity`, `discovery`.
- `Gate 2` when text contains: `Gate 2`, `MVP`, `traction`, `scope`, `metrics`, `risks`, `business case`.
- `Gate 3` when text contains: `Gate 3`, `scale`, `rollout`, `launch`, `operational readiness`.
- `Progress Review` when text contains: `progress review`, `progress`, `status`, `milestones`.
- `Stream Review` when text contains: `stream review`, `stream`, `portfolio`, `roadmap`.
- `Strategy Review` when text contains: `strategy review`, `strategy`, `market`, `positioning`.
- `Unknown` when no type reaches confidence `0.45`.

Confidence:

- start at `0.0`;
- add `0.35` for exact type phrase;
- add `0.1` per supporting keyword up to `0.55`;
- cap at `0.95`;
- if top two scores differ by less than `0.15`, reduce top score by `0.2`.

The explanation should list the matched phrases.

## API Endpoints

```text
GET /documents
POST /documents
GET /documents/{document_id}
PATCH /documents/{document_id}/document-type
GET /documents/{document_id}/raw
GET /documents/{document_id}/parsed-text
POST /documents/{document_id}/reparse
```

## Tasks

### Task 1: Local Storage Service

- [ ] Implement safe filename normalization.
- [ ] Implement SHA-256 streaming hash.
- [ ] Implement raw file save.
- [ ] Implement parsed artifact save.
- [ ] Add tests for path traversal attempts such as `../../secret.txt`.

Acceptance:

- unsafe filenames are sanitized;
- storage paths stay under `STORAGE_ROOT`;
- same file produces same SHA-256.

### Task 2: Upload Endpoint

- [ ] Implement `POST /documents`.
- [ ] Validate auth, file type, file size, and optional manual document type.
- [ ] Create document row with `parse_status=queued`.
- [ ] Save raw file.
- [ ] Enqueue parse job.
- [ ] Return document metadata.

Acceptance:

- user can upload supported file;
- unsupported file returns `415`;
- upload creates queued document row;
- upload does not parse inside request handler.

### Task 3: Worker Parsers

- [ ] Implement `.docx` parser with `python-docx`, extracting paragraph text and table cell text.
- [ ] Implement `.pdf` parser with `pypdf`, preserving page numbers in text markers.
- [ ] Implement `.md` and `.txt` parser as UTF-8 text readers with encoding fallback to UTF-8 with replacement.
- [ ] Add parser tests with small fixture files.

Acceptance:

- each parser returns non-empty text for valid fixture;
- parser failure updates document `parse_status=failed` and stores error.

### Task 4: Parse Job and Detection

- [ ] Implement `parse_document` job.
- [ ] Load document row and raw file.
- [ ] Run parser by MIME or extension.
- [ ] Save parsed text and parsed artifact.
- [ ] Run deterministic type detector.
- [ ] Update `parse_status=completed`, detected type, confidence, explanation.

Acceptance:

- completed parse has text and detected type;
- unknown type is represented as `unknown`, not null;
- failed parse preserves raw file and records error.

### Task 5: Document List and Detail

- [ ] Implement `GET /documents` with owner filtering for normal users.
- [ ] Implement admin visibility for all documents.
- [ ] Implement document detail, raw download, parsed text download.
- [ ] Implement manual document type override.
- [ ] Implement reparse.

Acceptance:

- user sees only own documents;
- admin sees all documents;
- user cannot download another user's raw document;
- manual type override is saved separately from detected type.

### Task 6: Frontend Document Workflow

- [ ] Build upload page with drag-and-drop zone, title field, optional manual type, and supported formats.
- [ ] Build document list with title, type, date, last verdict, analysis count, last analysis status.
- [ ] Build document detail with parse status, parsed text preview, type confirmation, and action buttons.

Acceptance:

- upload screen follows the source spec workflow;
- parse status visibly updates after refresh;
- document detail allows confirming or changing type before analysis.

## Verification

Run:

```bash
pytest apps/api/tests/test_documents_upload.py apps/worker/tests/test_document_parsers.py -q
```

Expected:

- upload and authorization tests pass;
- parser tests pass for `.docx`, `.pdf`, `.md`, `.txt`.

