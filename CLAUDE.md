# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlideAgent is an AI-powered PowerPoint generation service with two modes:
- **Mode 1 (Template Population):** Fills predefined PPTX templates with structured input data. LLM is used only for field coercion when input doesn't match schema exactly.
- **Mode 2 (Branded Content Generation):** Generates full deck content from a topic brief. Includes a user approval gate on the deck outline before content generation begins.

The project is in a **pre-implementation state** — comprehensive design docs exist in `project_docs/` but no source code has been written yet.

## Design Documentation

All specifications live in `project_docs/`:
- `PRD.md` — Functional and non-functional requirements
- `architecture.md` — System diagrams, sequence flows, state machines (Mermaid)
- `techContext.md` — Stack choices, project structure, env vars, dependencies
- `systemPatterns.md` — Core architectural patterns and principles
- `data-schemas.md` — All Pydantic models (template, job, LLM I/O, pipeline)
- `productContext.md` — User pain points and UX goals
- `projectbrief.md` — Goals, success criteria, phased timeline

## Planned Architecture

### Backend (FastAPI + Python)
- **Routes:** `POST /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/approve`, `GET /templates`, `POST /templates`
- **Services:** InputParser, ConstraintValidator, DeckPlanner, ContentGenerator, CoherenceCheck, XMLInjector, PPTXPipeline, BedrockClient
- **Storage:** Abstract interface with local filesystem (dev) and S3 (prod) implementations
- **Job Store:** Abstract interface with SQLite (dev) and DynamoDB (prod)

### Frontend (React 18 + TypeScript + Vite)
- Tailwind CSS + shadcn/ui for styling
- Zustand for job state machine, TanStack Query for polling/caching
- Dynamic forms generated from template schemas

### LLM (Amazon Bedrock)
- All calls use `converse` API with structured output via tool use
- Claude Sonnet for reasoning tasks (DeckPlanner, ContentGenerator)
- Claude Haiku for simple tasks (InputParser coercion, CoherenceCheck)

## Critical Design Constraints

1. **LLM generates content strings only.** Python services handle all file I/O, XML manipulation, and constraints. Never mix these concerns.
2. **PPTX manipulation uses lxml at the XML level**, not python-pptx's write API. python-pptx is dev-time only (template analysis). Direct XML manipulation preserves all template formatting attributes.
3. **Parse untrusted XML with defusedxml**, manipulate with lxml.
4. **Template schemas** map human-readable field names to XML shape IDs. Shape IDs are stable within a template version.
5. **Job state machine:** `queued → parsing → [planning → awaiting_approval →] generating → packaging → complete | failed`. Mode 2 includes the bracketed states.
6. **Approval gate in Mode 2** is a hard stop — no content generation until outline is approved.
7. **All processing stays within AWS boundary** — Bedrock only, no external API calls.

## Planned Development Commands

```bash
# Backend
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev    # Vite dev server on port 5173, proxied to :8000

# Template analysis (dev tool)
python scripts/analyze_template.py <path-to-template.pptx>
```

## Environment Variables

```
BEDROCK_REGION=us-east-1
STORAGE_BACKEND=local|s3
S3_BUCKET_TEMPLATES=slideagent-templates
S3_BUCKET_OUTPUTS=slideagent-outputs
JOB_STORE_BACKEND=sqlite|dynamodb
SQLITE_PATH=.data/jobs.db
DYNAMODB_TABLE=slideagent-jobs
MAX_JOB_TTL_HOURS=24
LOG_LEVEL=INFO
VITE_API_BASE_URL=http://localhost:8000
```

## Implementation Phases

1. **Phase 1:** Core PPTX pipeline + Mode 1 for a single status deck template
2. **Phase 2:** Mode 2 + layout library + deck planner with approval flow
3. **Phase 3:** Template registry UI, multi-template support, Ariadne integration
