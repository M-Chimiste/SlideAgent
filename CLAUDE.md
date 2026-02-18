# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlideAgent is an AI-powered PowerPoint generation service with two modes:
- **Mode 1 (Template Population):** Fills predefined PPTX templates with structured input data. LLM is used only for field coercion when input doesn't match schema exactly.
- **Mode 2 (Branded Content Generation):** Generates full deck content from a topic brief. Includes a user approval gate on the deck outline before content generation begins.

All three phases are implemented. Design docs live in `project_docs/`.

## Development Commands

```bash
# Activate conda env (must do first)
source ~/miniforge3/etc/profile.d/conda.sh && conda activate slideagent

# Backend — run dev server (from backend/)
cd backend && uvicorn app.main:app --reload --port 8000

# Backend — run all tests (from backend/)
cd backend && python -m pytest tests/ -v

# Backend — run single test file
cd backend && python -m pytest tests/test_api.py -v

# Backend — run single test
cd backend && python -m pytest tests/test_api.py::test_create_job_and_poll -v

# Frontend — install deps (first time only)
cd frontend && npm install

# Frontend — dev server on :5173 (proxied to :8000)
cd frontend && npm run dev

# Frontend — type-check
cd frontend && npx tsc --noEmit

# Frontend — build
cd frontend && npm run build

# Template analysis dev tool
cd backend && python ../scripts/analyze_template.py <path-to-template.pptx>
```

## Architecture

### Backend (FastAPI + Python 3.11)
- **Routes:** `POST /jobs`, `GET /jobs/{id}`, `GET /jobs`, `GET /jobs/{id}/download`, `POST /jobs/{id}/approve`, `GET /templates`, `GET /templates/{id}`, `POST /templates`, `PATCH /templates/{id}`, `GET /templates/{id}/versions`
- **Mode 1 Services:** InputParser, ConstraintValidator, XMLInjector, PPTXPipeline, JobRunner, BedrockClient
- **Mode 2 Services:** DeckPlanner (Sonnet), ContentGenerator (Sonnet, concurrent), CoherenceCheck (Haiku)
- **Template Management:** TemplateValidator (PPTX + schema validation), upload API, versioning, activate/deactivate
- **Storage:** LocalStorage (filesystem with atomic writes)
- **Job Store:** SQLiteJobStore via aiosqlite
- **Template Registry:** Loads from `templates/` dir — each template has `meta.json`, `schema.json`, `template.pptx`. Supports runtime registration via upload API and multi-version tracking.

### Programmatic API (`slideagent` package)
- `SlideAgentClient` — standalone Python API, no FastAPI required
- `generate_deck(template_id, mode, input_data, outline?) -> GenerateResult`
- All core services are pure Python with Pydantic I/O (no FastAPI imports)
- Designed for embedding in other Python applications (e.g., Ariadne)

### Frontend (React 18 + TypeScript + Vite)
- Tailwind CSS v4 for styling, Lucide for icons
- Zustand for step machine state, TanStack Query for polling/caching
- Mode 1: Dynamic forms generated from template schemas
- Mode 2: Brief input form + outline editor with approve/reject flow
- Template Manager: Upload, versioning, activate/deactivate
- Template Selector: Search and mode filtering
- Vite proxy routes `/jobs` and `/templates` to backend at `:8000`

### LLM (Amazon Bedrock)
- All calls use `converse` API with structured output via tool use
- BedrockClient wraps boto3, converts Pydantic schemas to Bedrock tool defs
- DeckPlanner uses Sonnet for outline generation; ContentGenerator uses Sonnet for per-slide content (concurrent via asyncio.gather); CoherenceCheck uses Haiku for review
- InputParser uses Haiku for fuzzy field coercion; falls back to strict mode when Bedrock is unavailable

## Critical Design Constraints

1. **LLM generates content strings only.** Python services handle all file I/O, XML manipulation, and constraints.
2. **PPTX manipulation uses lxml at the XML level**, not python-pptx's write API. python-pptx is used for structural operations only (Mode 2 slide creation from layouts). This preserves all template formatting.
3. **XML namespaces:** `<p:txBody>` is in the presentation namespace (`p:`), child elements (`<a:p>`, `<a:r>`, `<a:t>`) are in the drawingml namespace (`a:`). Use `lxml.etree.XMLParser(resolve_entities=False, no_network=True)` for safe parsing (defusedxml.lxml is deprecated).
4. **Template schemas** map human-readable field names to XML shape IDs. Shape IDs are stable within a template version.
5. **Mode 1 job state machine:** `queued → parsing → generating → packaging → complete | failed`.
6. **Mode 2 job state machine:** `queued → planning → awaiting_approval → generating → packaging → complete | failed`. Planning phase exits at `awaiting_approval`; generation spawned as separate background task after user approval.
7. **Template upload validates PPTX against schema** — shape IDs must exist on the correct slides/layouts.

## Key Patterns

- **Text injection:** Find shape by ID via XPath `.//p:sp[p:nvSpPr/p:cNvPr[@id='{shape_id}']]`, set first `<a:r>` run's `<a:t>` to new text (preserving `<a:rPr>` formatting), remove subsequent runs.
- **PPTX as ZIP:** Unpack with zipfile, manipulate XML with lxml, repack with ZIP_DEFLATED (XML) / ZIP_STORED (media).
- **Mode 2 slide creation:** python-pptx `add_slide()` for structural operations (handles relationships), then lxml for content injection. Shape IDs are deterministic per layout (placeholder idx + 2).
- **Atomic writes:** LocalStorage writes to `.tmp` then renames.
- **Background tasks:** Jobs run via FastAPI BackgroundTasks. JobRunner updates status in SQLite at each stage.
- **Mode 2 approval gate:** Background task exits at `awaiting_approval`. `POST /jobs/{id}/approve` spawns a new background task for generation (avoids holding coroutines open).
- **Template versioning:** Templates stored at `templates/{template_id}/{version}/`. Registry tracks all versions; `GET /templates` returns latest active. Upload validates PPTX shape IDs against schema.

## Environment Variables

See `.env.example`. Key vars: `BEDROCK_REGION`, `AWS_PROFILE`, `SONNET_MODEL_ID`, `HAIKU_MODEL_ID`, `TEMPLATES_DIR`, `SQLITE_PATH`, `LOG_LEVEL`.
