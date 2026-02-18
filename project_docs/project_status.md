# Project Status

**Last updated:** 2026-02-17

## Phase 1: Core PPTX Pipeline + Mode 1 — COMPLETE

Phase 1 delivers a working end-to-end pipeline: structured input data is injected into a PPTX template, producing a downloadable output file, with a React frontend for the full flow.

### What's Built

#### Backend (FastAPI + Python 3.11)

**Models** (4 files):
- `templates.py` — FieldType, TemplateFieldSchema, SlideSchema, TemplateRecord, LayoutDefinition, ContentType
- `jobs.py` — JobStatus, JobRecord, JobError, JobOptions, JobCreateRequest/Response, JobStatusResponse
- `schemas.py` — CoercionInput/Output, CoercedField, InjectionTarget, PipelineResult
- `dev_tools.py` — ShapeInfo, ShapeMap

**Services** (7 files):
- `template_registry.py` — Loads templates from `templates/` directory (meta.json + schema.json + template.pptx)
- `input_parser.py` — Maps input fields to schema fields; exact match pass-through, optional LLM coercion via Bedrock Haiku
- `constraint_validator.py` — Validates required fields, enum membership, max_chars (truncation at word/sentence boundary), date format, number type
- `xml_injector.py` — Injects text into PPTX slide XML by shape ID using lxml; preserves formatting
- `pptx_pipeline.py` — Orchestrates unpack → inject → repack → verify → store
- `job_runner.py` — Background task orchestrating InputParser → ConstraintValidator → InjectionTargets → PPTXPipeline
- `bedrock.py` — Wrapper around boto3 Bedrock converse API with structured output via tool use

**Routes** (3 files, 7 endpoints):
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/templates` | List all templates |
| GET | `/templates/{id}` | Template metadata + schema + layouts |
| POST | `/jobs` | Create job (returns 202) |
| GET | `/jobs` | List all jobs |
| GET | `/jobs/{id}` | Job status + progress |
| GET | `/jobs/{id}/download` | Download generated PPTX |

**Infrastructure:**
- `storage/local.py` — LocalStorage with atomic writes
- `store/sqlite.py` — SQLiteJobStore via aiosqlite
- `dependencies.py` — FastAPI dependency injection
- `config.py` — Pydantic BaseSettings

#### Frontend (React 18 + TypeScript + Vite)

**Stack:** Tailwind CSS v4, Zustand, TanStack Query, Lucide icons

**Components** (4 files):
- `TemplateSelector.tsx` — Card grid for template selection
- `InputForm.tsx` — Dynamic form generated from template schema (text inputs with char count, enum selects, date fields, number inputs; grouped by slide)
- `JobProgress.tsx` — Progress bar + stage checklist with polling (1s interval)
- `DownloadComplete.tsx` — Success state with warnings display and download button

**State:** Zustand step machine: `select → input → submitting → polling → complete | failed`

#### Dev Tooling
- `scripts/analyze_template.py` — CLI tool using python-pptx to introspect PPTX and output ShapeMap JSON

#### Sample Template
- `templates/novartis-status-weekly/` — 2-slide weekly status deck (title slide + project status slide) with 6 fields

---

## Phase 2: Mode 2 + Layout Library + Deck Planner — COMPLETE

Phase 2 adds content generation from topic briefs with a user approval gate on the deck outline. Users provide a brief (title, audience, key messages, tone) and the system generates a full deck outline for review, then generates content for each slide upon approval.

### What's Built

#### Backend — New Services (3 files)

- `deck_planner.py` — LLM service (Sonnet) that generates a `DeckOutline` from a topic brief + available layouts. Supports `plan_deck()` and `replan_deck()` for revision flow.
- `content_generator.py` — LLM service (Sonnet) that generates `SlideContent` for each slide concurrently via `asyncio.gather` with a semaphore (`MAX_CONCURRENT_LLM_CALLS=5`).
- `coherence_check.py` — LLM review pass (Haiku) over all generated slide content. Detects repetition, tonal drift, inconsistency. Major issues surfaced as warnings.

#### Backend — Extended Services

- `job_runner.py` — Added `run_mode2_planning()`, `run_mode2_replan()`, `run_mode2_generation()`. Planning phase exits at `awaiting_approval`; generation spawned as separate background task after approval.
- `pptx_pipeline.py` — Added `execute_mode2()`: uses python-pptx to create slides from layouts (handles relationship management), then lxml for content injection.
- `constraint_validator.py` — Added `validate_flat()` for per-slide field validation against layout definitions.
- `template_registry.py` — Added `get_layouts_for_template()` and `_parse_layouts_schema()` for Mode 2 layout loading.
- `dependencies.py` — Added `get_deck_planner()`, `get_content_generator()`, `get_coherence_check()`.
- `main.py` — Initializes Mode 2 services when AWS credentials are available (Bedrock STS check); graceful fallback to Mode 1 only.

#### Backend — New Models

- `schemas.py` — Added: SlideOutlineEntry, DeckOutline, SlideFieldContent, SlideContent, CoherenceIssue, CoherenceCheckOutput
- `jobs.py` — Added: OutlineApprovalRequest

#### Backend — New API Endpoint

| Method | Path | Description |
|--------|------|-------------|
| POST | `/jobs/{id}/approve` | Approve or reject deck outline (Mode 2 approval gate) |

**Approval flow:**
- `{approved: true}` → Job transitions to `generating`, spawns generation background task
- `{approved: true, revised_outline: {...}}` → Updates stored outline, then generates
- `{approved: false, revision_instructions: "..."}` → Re-plans outline with instructions

#### Frontend — New/Updated Components

- `OutlineEditor.tsx` — **NEW**: Editable deck outline view with slide reordering, title/summary editing, slide add/remove, approve/reject with revision instructions
- `InputForm.tsx` — **UPDATED**: Mode 2 brief input form (title, audience, key messages list, tone, slide count range, freeform brief); Mode 1 form unchanged
- `TemplateSelector.tsx` — **UPDATED**: Visual distinction between Mode 1 (blue, "Template Fill") and Mode 2 (purple, "AI Generated") templates
- `JobProgress.tsx` — **UPDATED**: Mode 2 stage names (planning, outline approved, generating content); purple theming for Mode 2
- `App.tsx` — **UPDATED**: Added `outline_review` step routing

**State:** Extended Zustand step machine: `select → input → submitting → polling → outline_review → polling → complete | failed`

#### Mode 2 Template

- `templates/corporate-deck/` — Clean PPTX (0 content slides, 11 slide layouts) with 5 layout definitions:
  - `title_slide` — Title Slide layout (deck_title, subtitle)
  - `content_bullets` — Title and Content layout (slide_title, body)
  - `section_divider` — Section Header layout (section_title, section_subtitle)
  - `two_column` — Two Content layout (slide_title, left_content, right_content)
  - `closing` — Title Only layout (closing_title)

### Test Coverage

**110 tests across 13 test files, all passing:**

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_models.py | 17 | All Pydantic models: valid round-trips, invalid data rejection |
| test_storage.py | 10 | LocalStorage: write/read, atomicity, missing keys, list, download URL |
| test_job_store.py | 9 | SQLiteJobStore: CRUD, partial updates, TTL expiry |
| test_template_registry.py | 8 | Registry load, list, get, schema parsing, real template |
| test_xml_injector.py | 7 | Text replacement, formatting preservation, multi-run consolidation, missing shapes |
| test_pptx_pipeline.py | 4 | Happy path with real template, staging cleanup, missing template, missing shape warnings |
| test_constraint_validator.py | 12 | Required fields, enum, date formats, number, truncation, unknown fields |
| test_input_parser.py | 4 | Exact match, subset, unmatched fields ignored, type coercion |
| test_api.py | 10 | Full E2E (create→poll→download→verify PPTX), template 404, validation errors, list jobs |
| test_mode2_models.py | 11 | Mode 2 models: outline, slide content, coherence, approval request |
| test_mode2_template.py | 6 | Mode 2 template loading, layout definitions, backward compatibility |
| test_mode2_pipeline.py | 3 | Mode 2 pipeline: slide creation from layouts, content injection, empty/unknown handling |
| test_mode2_api.py | 9 | Full Mode 2 E2E (create→plan→approve→generate→download), reject/replan, state validation |

### Known Limitations

- **Bedrock required for Mode 2:** DeckPlanner, ContentGenerator, and CoherenceCheck require AWS credentials and Bedrock access. Mode 2 is disabled when credentials are unavailable.
- **No authentication:** All endpoints are unauthenticated.
- **Local storage only:** Filesystem-based storage (no cloud backend).
- **No concurrent job limits:** Background tasks run without throttling.
- **CoherenceCheck issues not auto-corrected:** Currently, coherence issues are surfaced as warnings only; automatic content correction is not implemented.
- **Single Mode 2 template:** Only `corporate-deck` template exists with 5 layouts.

---

## Phase 3: Template Registry UI + Multi-Template + Ariadne Prep — COMPLETE

Phase 3 adds production-grade template management with upload, versioning, and a standalone programmatic API for embedding in other applications.

### What's Built

#### Backend — New Services

- `template_validator.py` — Validates uploaded PPTX templates against their schema. Checks shape IDs exist on correct slides (Mode 1) or layout indices are valid (Mode 2). Raises `TemplateValidationError` with detailed error list on failure.

#### Backend — New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/templates` | Upload template (multipart: PPTX + schema JSON + metadata) with validation |
| PATCH | `/templates/{id}` | Activate or deactivate a template |
| GET | `/templates/{id}/versions` | List all versions of a template |

**Upload flow:**
- Validates mode, parses schema JSON, checks PPTX is non-empty
- Validates shape IDs/layout indices against the PPTX file
- Stores versioned files at `templates/{id}/{version}/` + flat path for backward compat
- Registers template in-memory immediately (no restart required)

#### Backend — Extended Services

- `template_registry.py` — Added `register_template()`, `activate_template()`, `deactivate_template()`, `list_active_templates()`, `list_versions()`, `get_template_version()`. Version tracking via `_versions` dict (template_id → {version: TemplateRecord}).
- `routes/templates.py` — Extended with upload, PATCH, and versions endpoints. `GET /templates` now returns only active templates.

#### Programmatic API (`slideagent` package)

Standalone Python API for embedding SlideAgent in other applications:

- `slideagent/__init__.py` — Package with `SlideAgentClient`, `GenerateResult`, `DeckMode` exports
- `slideagent/client.py` — `SlideAgentClient` class wrapping all core services
  - `initialize()` — Loads templates
  - `generate_deck(template_id, mode, input_data, outline?) -> GenerateResult`
  - Mode 1: parse → validate → inject → pipeline → result
  - Mode 2: plan → generate → validate → inject → pipeline → result (auto-approves outline)
  - No FastAPI dependency; all services are pure Python with Pydantic I/O
- `slideagent/models.py` — `GenerateResult`, `DeckMode` public API models

#### Frontend — New Components

- `TemplateManager.tsx` — **NEW**: Template management UI with:
  - Upload form (drag-and-drop PPTX, schema JSON input/file load, metadata fields)
  - Template list with expand/collapse for version history
  - Activate/deactivate toggle per template
  - Auto-derives template_id from filename
  - Schema file loading from JSON file

#### Frontend — Updated Components

- `TemplateSelector.tsx` — **UPDATED**: Added search bar (filters by name, description, template_id) and mode filter buttons (All / Fill / AI)
- `App.tsx` — **UPDATED**: Added `manage` step for Template Manager, "Manage Templates" button in header
- `jobStore.ts` — **UPDATED**: Added `manage` step to step machine
- `client.ts` — **UPDATED**: Added `uploadTemplate()`, `updateTemplateStatus()`, `listTemplateVersions()` API functions
- `types.ts` — **UPDATED**: Added `TemplateVersion`, `TemplateUploadResponse`, `TemplateStatusResponse` interfaces; `is_active` field on `TemplateSummary`

### Test Coverage

**135 tests across 15 test files, all passing:**

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_models.py | 17 | All Pydantic models |
| test_storage.py | 10 | LocalStorage |
| test_job_store.py | 9 | SQLiteJobStore |
| test_template_registry.py | 8 | Registry load, list, get |
| test_xml_injector.py | 7 | XML injection |
| test_pptx_pipeline.py | 4 | PPTX pipeline |
| test_constraint_validator.py | 12 | Field validation |
| test_input_parser.py | 4 | Input parsing |
| test_api.py | 10 | Mode 1 E2E |
| test_mode2_models.py | 11 | Mode 2 models |
| test_mode2_template.py | 6 | Mode 2 template loading |
| test_mode2_pipeline.py | 3 | Mode 2 pipeline |
| test_mode2_api.py | 9 | Mode 2 E2E |
| test_template_upload.py | 18 | Template upload API, validation, versioning, activate/deactivate |
| test_slideagent_client.py | 7 | Programmatic API: init, Mode 1 generation, error cases |

### Known Limitations

- **Bedrock required for Mode 2:** DeckPlanner, ContentGenerator, and CoherenceCheck require AWS credentials.
- **No authentication:** All endpoints are unauthenticated.
- **No concurrent job limits:** Background tasks run without throttling.
- **Version management is in-memory:** Template version history resets on server restart (loaded from disk on startup).

---

## Post-Phase 3: Config Cleanup — COMPLETE

Removed cloud abstractions (S3, DynamoDB) and simplified AWS/Bedrock configuration.

### What Changed

#### Removed
- **Protocol files deleted:** `storage/base.py` (StorageInterface) and `store/base.py` (JobStoreInterface) — cloud backend abstractions that were never implemented
- **Config fields removed:** `storage_backend`, `s3_bucket_templates`, `s3_bucket_outputs`, `job_store_backend`, `dynamodb_table`
- **Hardcoded model IDs removed** from DeckPlanner, ContentGenerator, CoherenceCheck, InputParser — replaced with constructor parameters

#### Added
- **`AWS_PROFILE`** env var — specify a named CLI profile (empty = default credential chain)
- **`SONNET_MODEL_ID`** env var — configurable Sonnet model for planning + content generation
- **`HAIKU_MODEL_ID`** env var — configurable Haiku model for coercion + coherence checks
- **`BedrockClient(profile_name=...)`** — uses `boto3.Session(profile_name=...)` when set

#### Updated
- `config.py`, `.env.example` — simplified to local-only config + AWS/model vars
- `main.py` — passes profile + model IDs to all services
- `dependencies.py` — removed unused imports
- `pptx_pipeline.py` — `LocalStorage` type hint replaces `StorageInterface`
- `slideagent/client.py` — added `aws_profile`, `sonnet_model_id`, `haiku_model_id` params
- All project docs cleaned of S3/DynamoDB references

### Test Coverage

**135 tests across 15 test files, all passing** (unchanged count — no new tests needed, 3 test fixtures updated to remove stale config kwargs).
