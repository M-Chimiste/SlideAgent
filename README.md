# SlideForge

SlideForge is an AI-powered PowerPoint generation app. It turns a brief,
optional source documents, and optional PowerPoint templates into editable PPTX
decks with previews, warnings, downloads, and QA feedback.

This repository is named `SlideAgent`; the backend package is
`slideforge-backend`. The app is currently a strong local vertical slice, not a
finished production deck engine.

## What It Does

SlideForge supports three first-class generation modes:

| Mode | Purpose |
| --- | --- |
| `freeform` | Generate a complete deck from a brief and optional documents using built-in consulting-style layout archetypes. |
| `brand` | Use an uploaded PPTX as a brand reference for colors, fonts, logo, and layout DNA while generating new slides. |
| `strict` | Preserve a rigid PPTX structure and update designated fields through XML-level injection. |

The pipeline builds a structured ghost deck before rendering, runs consulting
and visual QA, repairs generated-slide issues when possible, then emits:

- editable `.pptx` output
- optional `.pdf` export
- rendered slide previews
- QA issues and warnings
- debug artifacts for diagrams and generated assets

The quality rubric lives in [project_docs/style_guide.md](project_docs/style_guide.md).

Current local Qwen baseline: the `data/Beyond Vibe Coding.docx` all-mode smoke
passes across freeform, brand, and strict with no planner fallback, no planning
warnings, no build warnings, and no final visual-QA issues. The latest verified
backend suite is `234 passed`.

## App Architecture

```text
React 19 + Vite frontend
        |
        v
FastAPI backend
+-- routes: jobs, templates, health
+-- JobQueue: in-process async background worker
+-- JobOrchestrator: per-job pipeline and QA repair loop
        |
        v
DocumentIngester
  -> TemplateAnalyzer
  -> ContentPlanner
  -> DesignAgent
  -> PptxBuilder
  -> VisualQAAgent
```

Generated freeform and brand decks use the deterministic PPTX renderer.
Strict-mode decks use XML-level injection to preserve existing template
geometry, formatting, relationships, media, masters, layouts, and content
types.

For deeper context, read:

- [project_docs/project_status.md](project_docs/project_status.md)
- [project_docs/architecture.md](project_docs/architecture.md)
- [project_docs/style_guide.md](project_docs/style_guide.md)

## Prerequisites

Local development expects:

- Python 3.11
- Node.js 20+
- `npm`
- LibreOffice `soffice` for PPTX-to-PDF rendering and visual QA
- Poppler `pdftoppm` for slide previews
- Docker or Docker Desktop for containerized UI testing

The backend Node workers use Sharp/react-icons for diagram and icon
rasterization, with deterministic Python fallbacks where supported.

## Configuration

Create a local environment file from the example:

```bash
cp .env.example .env
```

Important defaults:

```bash
LLM_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=http://localhost:1240/v1
OPENAI_COMPATIBLE_MODEL=qwen3.6-35b-a3b-mtp
VISION_BASE_URL=http://localhost:1240/v1
VISION_MODEL=qwen3.6-35b-a3b-mtp
```

Use your local OpenAI-compatible server, LM Studio, or Bedrock settings as
needed.
Planner routing is controlled per job with:

- `planner_profile=fast|deep`
- `quality_profile=fast|balanced|showcase`
- `length_strategy=auto|concise|expanded`

## Quick Start: Docker UI

The easiest way to run the full app for UI or E2E testing is:

```bash
scripts/e2e-ui.sh
```

This builds and starts the Docker Compose `slideforge` service, waits for
`/api/health`, then prints the UI URL.

Default URLs:

- UI: `http://localhost:8080`
- Health: `http://localhost:8080/api/health`

Useful commands:

```bash
scripts/e2e-ui.sh start --no-build
scripts/e2e-ui.sh restart
scripts/e2e-ui.sh logs
scripts/e2e-ui.sh status
scripts/e2e-ui.sh stop
```

Docker Compose persists SQLite, templates, and job artifacts under:

```text
data/
```

If startup fails with a Docker daemon error, start Docker Desktop or Colima and
run the script again.

## Local Development

### 1. Backend

```bash
source ~/miniforge3/etc/profile.d/conda.sh
conda activate slideagent

cd backend
python -m pip install -e .
npm ci
uvicorn app.main:app --reload --port 8000
```

Backend API:

```text
http://localhost:8000/api
```

### 2. Frontend

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Frontend UI:

```text
http://localhost:5173
```

Vite proxies `/api` to `http://localhost:8000`.

## Common Commands

Backend tests:

```bash
cd backend
python -m pytest tests/ -q
python -m pytest tests/test_orchestrator_modes.py -v
```

Backend lint:

```bash
cd backend
ruff check app/ tests/
```

Frontend checks:

```bash
cd frontend
npx tsc --noEmit
npm run build
```

All-mode local smoke:

```bash
cd backend
python -m app.tools.all_mode_smoke --vision
```

Fast Qwen production-polish smoke used for the current baseline:

```bash
cd backend
python -m app.tools.all_mode_smoke \
  --doc ../data/'Beyond Vibe Coding.docx' \
  --modes freeform,brand,strict \
  --quality-profile fast \
  --length-strategy concise \
  --label qwen-allmodes-fast
```

Premium/deep planner smoke, when a separate planner server is available:

```bash
cd backend
python -m app.tools.all_mode_smoke \
  --base-url http://localhost:1240/v1 \
  --model your-model-name \
  --label deep-planner
```

## API Overview

Main endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Health check |
| `POST` | `/api/jobs` | Create a generation job |
| `GET` | `/api/jobs` | List jobs |
| `GET` | `/api/jobs/{id}` | Get job status, previews, warnings, and QA |
| `GET` | `/api/jobs/{id}/preview/{image}` | Fetch a rendered slide preview |
| `GET` | `/api/jobs/{id}/download?format=pptx|pdf` | Download generated output |
| `POST` | `/api/jobs/{id}/regen/{slide_index}` | Regenerate one slide |
| `POST` | `/api/templates/analyze` | Analyze a brand or strict PPTX template |
| `GET` | `/api/templates` | List saved templates |
| `PATCH` | `/api/templates/{id}` | Update template metadata/schema |
| `DELETE` | `/api/templates/{id}` | Delete a template |
| `POST` | `/api/templates/{id}/duplicate` | Duplicate a template |

`POST /api/jobs` uses multipart form data. Key fields:

| Field | Values |
| --- | --- |
| `generation_mode` | `freeform`, `brand`, `strict` |
| `template_id` | required for `brand` and `strict` |
| `planner_profile` | `fast`, `deep` |
| `quality_profile` | `fast`, `balanced`, `showcase` |
| `length_strategy` | `auto`, `concise`, `expanded` |
| `run_visual_qa` | boolean |
| `instructions` | deck brief |
| `documents` | uploaded source files |

Job lifecycle:

```text
queued -> analyzing -> planning -> generating -> qa -> done | error
```

## Repository Layout

```text
backend/
  app/
    routes/              FastAPI API routes
    services/            pipeline services and public facades
    services/planning/   planner internals
    services/pptx_rendering/
    services/visual_qa/
    workers/             Node workers for diagrams/icons
  tests/

frontend/
  src/
    components/          wizard screens, library rail, lightbox
    api/                 frontend API client

project_docs/            architecture, status, style guide
scripts/
  e2e-ui.sh              Docker UI/E2E helper
```

## Development Notes

- Keep the public service facades stable:
  `ContentPlanner`, `DeterministicPptxRenderer`, and `VisualQAAgent`.
- LLMs should produce structured specs only. Python and Node services own file
  I/O, XML mutation, packaging, validation, layout, and rendering.
- Strict mode is preserve-first. Use `[INSERT CONTENT HERE]` plus warnings when
  required mapped content is missing.
- `GeneratedSlideSpec.source_refs` is the canonical citation field for
  generated modes. Rendered `sources` are human-readable labels.
- Use safe XML parsing with
  `lxml.etree.XMLParser(resolve_entities=False, no_network=True)`.
- Generated-mode smoke gates should pass without planner fallback or build
  warnings. The current Qwen acceptance gate also expects no final planning
  warnings and no final visual-QA issues for the Beyond Vibe Coding smoke.

## Current Caveat

SlideForge works end-to-end locally across freeform, brand, and strict modes,
and the current Qwen path can produce polished, production-grade PPTX artifacts
for the Beyond Vibe Coding smoke. The broader quality frontier is still manual
Office compatibility review, richer diagram/chart families, deeper brand/layout
fidelity, and broader smoke coverage across non-demo source documents.
