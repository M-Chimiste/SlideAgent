# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlideAgent is an AI-powered PowerPoint generation service with two modes:
- **Mode 1 (Template Population):** Fills predefined PPTX templates with structured input data. LLM (Haiku) coerces fields only when input doesn't match schema exactly.
- **Mode 2 (Branded Content Generation):** Generates full deck content from a topic brief via DeckPlanner → approval gate → ContentGenerator → CoherenceCheck.

## Current State

The codebase was fully implemented through 3 phases (135 tests passing), then the code was removed from `dev` (commit `0a5861e`). The prior implementation is preserved in git history at commit `ade041c`. Design docs remain in `project_docs/prd.md`.

## Development Environment

```bash
# Conda environment (Python 3.11, miniforge3)
source ~/miniforge3/etc/profile.d/conda.sh && conda activate slideagent

# Use `python` not `python3` inside the conda env
```

## Common Commands

```bash
# Backend dev server
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend dev server (Vite :5173, proxied to :8000)
cd frontend && npm run dev

# Run all backend tests
cd backend && python -m pytest tests/ -v

# Run a single test file or specific test
cd backend && python -m pytest tests/test_api.py -v
cd backend && python -m pytest tests/test_api.py::test_create_job_and_poll -v

# Python linting (ruff: line-length 100, selects E/F/I/N/W/UP)
cd backend && ruff check app/ slideagent/

# Type checking
cd backend && mypy app/ slideagent/
cd frontend && npx tsc --noEmit

# Frontend lint and build
cd frontend && npx eslint .
cd frontend && npm run build
```

## Architecture

```
React Frontend (Vite + Zustand + TanStack Query)
        │
        ▼
FastAPI Backend (:8000)
├── Routes: POST /jobs, GET /jobs/{id}, POST /jobs/{id}/approve, GET /jobs/{id}/download
│           GET /templates, POST /templates, PATCH /templates/{id}, GET /health
├── Services (pure Python + Pydantic I/O, no FastAPI imports):
│   ├── InputParser        — field matching + Haiku LLM coercion (Mode 1)
│   ├── ConstraintValidator — type/enum/max_chars validation
│   ├── DeckPlanner        — outline generation via Sonnet (Mode 2)
│   ├── ContentGenerator   — per-slide content via Sonnet, asyncio.gather (Mode 2)
│   ├── CoherenceCheck     — deck review via Haiku (Mode 2)
│   ├── XMLInjector        — lxml-based PPTX text injection by shape ID
│   ├── PPTXPipeline       — ZIP unpack → XML inject → repack
│   ├── BedrockClient      — boto3 converse API with structured tool-use output
│   ├── TemplateRegistry   — template discovery + versioning from disk
│   └── TemplateValidator  — validates PPTX shape IDs match schema
├── Storage: LocalStorage (async, atomic writes via .tmp → rename)
└── Store: SQLiteJobStore (aiosqlite)
```

### Job State Machines
- **Mode 1:** `queued → parsing → generating → packaging → complete | failed`
- **Mode 2:** `queued → planning → awaiting_approval → generating → packaging → complete | failed`
  - Planning exits at `awaiting_approval`; generation spawns as a separate background task after approval

### Service Layer Pattern
All services are pure Python with Pydantic models for I/O. No FastAPI imports in the service layer. LLM services accept `model_id` as a constructor parameter.

## Critical Design Constraints

1. **LLM generates content strings only** — Python services handle all file I/O, XML manipulation, and constraints
2. **PPTX uses lxml at XML level**, not python-pptx's write API — preserves all template formatting
3. **XML namespaces:** `<p:txBody>` is presentation namespace (`p:`), children (`<a:p>`, `<a:r>`, `<a:t>`) are drawingml (`a:`). Search for txBody from a shape with `{ns_p}txBody` not `{ns_a}txBody`
4. **Safe XML parsing:** `lxml.etree.XMLParser(resolve_entities=False, no_network=True)` — defusedxml.lxml is deprecated
5. **Template schemas** map human-readable field names to XML shape IDs; shape IDs are stable within a template version

## Tech Stack

| Layer | Stack |
|-------|-------|
| Backend | FastAPI, Python 3.11, Pydantic 2, aiosqlite, python-pptx, lxml, boto3 |
| Frontend | React 19, TypeScript, Vite, TailwindCSS 4, Zustand, TanStack Query |
| LLM | AWS Bedrock converse API — Sonnet for reasoning, Haiku for lightweight tasks |
| Build | Hatchling (Python), npm (Node) |

## Testing Patterns

- `asyncio_mode = "auto"` via pytest-asyncio
- HTTP tests use `httpx.AsyncClient` with `ASGITransport` (not requests/TestClient)
- ASGITransport doesn't trigger FastAPI lifespan; manually manage with `async with app.router.lifespan_context(app)`
- Use `raise_app_exceptions=False` on ASGITransport when lifespan is manually managed

## Environment Variables

See `.env.example` — key vars: `BEDROCK_REGION`, `AWS_PROFILE`, `SONNET_MODEL_ID`, `HAIKU_MODEL_ID`, `SQLITE_PATH`, `TEMPLATES_DIR`, `STAGING_DIR`, `OUTPUTS_DIR`

## Pydantic Gotchas

- Avoid `schema_json` as a field name — shadows `BaseModel.schema_json`
- Don't use `from __future__ import annotations` with Pydantic — breaks runtime eval
- Use `model_copy(update={...})` for immutable record updates
