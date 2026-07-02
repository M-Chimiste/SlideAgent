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
warnings, no build warnings, and no final visual-QA issues. Recent project
status updates record the backend suite at `493 passed`, with ruff, frontend
typecheck, and frontend build clean.

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
  -> TemplateAnalyzer (brand/strict only)
  -> ContentPlanner
  -> DesignAgent
  -> [optional plan-review gate]
  -> PptxBuilder
  -> VisualQAAgent
```

Generated freeform and brand decks default to the polished native renderer
(`RENDERER_ENGINE=native`), which builds editable PowerPoint shapes, text,
tables, and charts. `authored` and `legacy` remain opt-in rollback paths; the
removed image-based `html` value resolves to `native`. Brand mode defaults to
the same native layout system themed with extracted brand DNA
(`BRAND_RENDER_MODE=native`), with the conservative clone/edit path available
via `BRAND_RENDER_MODE=clone`.

Strict-mode decks use XML-level injection to preserve existing template
geometry, formatting, relationships, media, masters, layouts, and content
types. Generated jobs can optionally stop at `planned` for outline review and
then resume rendering.

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
RENDERER_ENGINE=native
BRAND_RENDER_MODE=native
```

Use your local OpenAI-compatible server, LM Studio, or Bedrock settings as
needed. Planner and design routing are controlled per job:

| Field | Values |
| --- | --- |
| `planner_profile` | `fast`, `deep` |
| `quality_profile` | `fast`, `balanced`, `showcase` |
| `length_strategy` | `auto`, `concise`, `expanded` |
| `presentation_style` | `auto`, `consulting`, `investor_pitch`, `sales`, `academic_lecture`, `technical_deep_dive`, `keynote_narrative`, `status_report_qbr` |
| `design_language` | `auto`, `editorial_serif`, `modern_geometric`, `bold_minimal`, `warm_magazine`, `technical_mono`, `data_forward` |
| `background_style` | `auto`, `light`, `dark` |

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
  --base-url http://athena.local:1240/v1 \
  --model minimax-m2.7 \
  --label minimax-m27
```

## API Overview

Main endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Health check |
| `POST` | `/api/jobs` | Create a generation job |
| `GET` | `/api/jobs` | List jobs |
| `GET` | `/api/jobs/{id}` | Get job status, previews, warnings, and QA |
| `POST` | `/api/jobs/{id}/render` | Render a generated job paused at `planned` |
| `GET` | `/api/jobs/{id}/outline` | Fetch a planned/generated outline for review |
| `PATCH` | `/api/jobs/{id}/outline` | Edit outline titles/subheadings before render |
| `GET` | `/api/jobs/{id}/planning/{artifact}` | Fetch planning artifacts such as `story-map`, `spec-gate`, or `narrative-pass` |
| `GET` | `/api/jobs/{id}/qa/rendered-slide-audit` | Fetch rendered-slide audit findings |
| `GET` | `/api/jobs/{id}/preview` | List rendered preview images |
| `GET` | `/api/jobs/{id}/preview/{image}` | Fetch a rendered slide preview |
| `GET` | `/api/jobs/{id}/download?format=pptx|pdf` | Download generated output |
| `POST` | `/api/jobs/{id}/regen/{slide_index}` | Regenerate one slide, optionally with guidance or edits |
| `PATCH` | `/api/jobs/{id}/slides/{slide_index}` | Directly edit title, subheading, points, layout, or background |
| `POST` | `/api/templates/analyze` | Analyze a brand or strict PPTX template |
| `GET` | `/api/templates` | List saved templates |
| `GET` | `/api/templates/{id}` | Fetch a saved template profile |
| `GET` | `/api/templates/{id}/assets` | List thumbnails, discovered images, logo state, and frame-map summary |
| `GET` | `/api/templates/{id}/thumbnail/{image}` | Fetch a rendered template thumbnail |
| `GET` | `/api/templates/{id}/logo` | Fetch the selected template logo |
| `GET` | `/api/templates/{id}/image/{image}` | Fetch a discovered template image |
| `PATCH` | `/api/templates/{id}/logo` | Select or remove a template logo override |
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
| `presentation_style` | `auto`, `consulting`, `investor_pitch`, `sales`, `academic_lecture`, `technical_deep_dive`, `keynote_narrative`, `status_report_qbr` |
| `design_language` | `auto`, `editorial_serif`, `modern_geometric`, `bold_minimal`, `warm_magazine`, `technical_mono`, `data_forward` |
| `background_style` | `auto`, `light`, `dark` |
| `run_visual_qa` | boolean |
| `plan_only` | boolean; generated modes only |
| `instructions` | deck brief |
| `documents` | uploaded source files |

Job lifecycle:

```text
queued -> analyzing -> planning -> [planned] -> generating -> qa <-> repairing -> done | review_failed | error
```

## Repository Layout

```text
backend/
  app/
    routes/              FastAPI API routes
    services/            pipeline services and public facades
    services/planning/   planner internals
    services/pptx_native/
    services/pptx_rendering/  legacy deterministic renderer internals
    services/slide_design/    renderer-agnostic design helpers
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
- The default generated renderer should stay editable. Picture-dominated output
  should surface `editability` build warnings instead of quietly passing review.

## Current Caveat

SlideForge works end-to-end locally across freeform, brand, and strict modes,
and the current native-rendered Qwen path can produce polished, editable PPTX
artifacts for the core smoke set. The broader quality frontier is still manual
Office compatibility review, richer diagram/chart families, deeper brand/layout
fidelity beyond extracted BrandDNA, and broader smoke coverage across non-demo
source documents.
