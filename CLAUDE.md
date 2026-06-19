# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlideForge (the repo directory is named `SlideAgent`, the package is `slideforge-backend`)
is an AI-powered PowerPoint generation service. It has **three first-class generation modes**:

- **freeform** — generate a complete deck from a brief + optional documents, using built-in layout archetypes.
- **brand** — use an uploaded PPTX as a brand/master reference (colors, fonts, logo, layout DNA) while generating *new* slides.
- **strict** — preserve a rigid PPTX's structure and update only designated fields via XML-level injection.

The pipeline builds and validates a structured "ghost deck" before rendering, runs the deck through a
quality/repair loop, and emits a PPTX plus preview images and warnings. The quality source of truth is
[project_docs/style_guide.md](project_docs/style_guide.md), which drives planner prompts and QA checks.

## Current State

This is an honest **vertical slice**, not a finished engine. Generation works end-to-end for all three modes
with deterministic rendering, source provenance, diagram/icon rendering, ConsultingQA repair, and a
visual-QA repair loop.
Read [project_docs/project_status.md](project_docs/project_status.md) for the current-vs-target reality and
[project_docs/architecture.md](project_docs/architecture.md) for target architecture + current module boundaries.

> Note: the prior two-mode "SlideAgent" product (preserved in git history at `ade041c`) is obsolete. Borrow the
> old code's service discipline, not its product model.

## Development Environment

```bash
# Conda env (Python 3.11, miniforge3) — note the env name is still `slideagent`
source ~/miniforge3/etc/profile.d/conda.sh && conda activate slideagent
# Use `python`, not `python3`, inside the env
```

External runtime tools (installed via Homebrew on this machine) are required for the full pipeline:
- `node` — rasterizes diagrams/icons (Sharp + react-icons); deterministic Pillow fallback if Node deps are absent.
- `soffice` (LibreOffice) — renders PPTX → PDF for visual QA and the `/download?format=pdf` export.
- `pdftoppm` (Poppler) — renders PDF → slide preview images.

## Common Commands

```bash
# Backend dev server (FastAPI on :8000)
cd backend && uvicorn app.main:app --reload --port 8000

# Install Node workers used for diagram/icon rendering (one-time)
cd backend && npm install

# Frontend dev server (Vite :5173, proxies /api → :8000)
cd frontend && npm run dev

# Backend tests
cd backend && python -m pytest tests/ -q
cd backend && python -m pytest tests/test_orchestrator_modes.py -v                       # single file
cd backend && python -m pytest tests/test_orchestrator_modes.py::test_orchestrator_runs_freeform_job_without_template -v  # single test

# Backend lint (ruff; no repo config → ruff defaults)
cd backend && ruff check app/ tests/

# Frontend typecheck + production build
cd frontend && npx tsc --noEmit
cd frontend && npm run build

# Repeatable all-mode local-model smoke (freeform/brand/strict end-to-end; writes a JSON report)
cd backend && python -m app.tools.all_mode_smoke --vision
# Compare against the deep/premium planner (Minimax via Athena):
cd backend && python -m app.tools.all_mode_smoke --base-url http://athena.local:1240/v1 --model minimax-m2.7 --label minimax-m27
```

There is **no** repo-level pytest/ruff/mypy config. Async tests use explicit `@pytest.mark.asyncio` markers
(there is no `asyncio_mode = "auto"`), and tests call route/service functions directly rather than over HTTP —
there is no ASGITransport/`httpx.AsyncClient` harness anymore.

## Architecture

```
React 19 + Vite + TS frontend (plain — no Tailwind/Zustand/TanStack)
        │  (proxies /api → :8000)
        ▼
FastAPI backend  (all routes under /api; create_app() in app/main.py)
├── routes/  jobs · templates · health
├── JobQueue — in-process async background worker; runs jobs through the orchestrator
└── JobOrchestrator — drives the per-job pipeline and QA repair loop
        │
        ▼  Pipeline (app/services/)
  DocumentIngester → [TemplateAnalyzer (brand/strict only)] → ContentPlanner
    → DesignAgent → PptxBuilder → VisualQAAgent → deterministic QA repair loop
        │
        ├── Storage: LocalStorage (data/jobs/<id>/…) + SQLiteStore (aiosqlite, data/slideforge.db)
        └── Node workers (app/workers/): diagram_renderer.js · icon_renderer.js  (Sharp/react-icons)
```

### Job lifecycle

`queued → analyzing → planning → generating → qa → done | error`

There is **no approval gate** — jobs run straight through. A job is created via `POST /api/jobs` (multipart form),
enqueued on `JobQueue`, and executed by `JobOrchestrator.run_job` in the background. Config travels in the job's
`config_json` and selects mode + quality knobs (see "Request contract" below).

### Service facades → packages

Three large services are stable public facades that delegate to internal packages (behavior-preserving refactors —
keep the facade's public shape stable):

- `services/content_planner.py` (`ContentPlanner`) → `services/planning/` (`blueprint`, `llm`, `specs`, `repairs`, `grounding`, `outlines`, `exhibits`, `constants`)
- `services/pptx_renderer.py` (`DeterministicPptxRenderer`) → `services/pptx_rendering/` (`assets`, `chrome`, `core_layouts`, `table_layouts`, `immersive_layouts`, `exhibit_layouts`, `drawing`, `constants`)
- `services/visual_qa_agent.py` (`VisualQAAgent`) → `services/visual_qa/` (`checks`, `preview`, `vision`, `constants`)

### PPTX build paths (`PptxBuilder.build_deck`)

- **freeform / brand** → `DeterministicPptxRenderer.render(...)` — a pure-Python deterministic renderer is the
  primary path. It owns positioning, fonts, colors, charts, icons, tables, diagrams, source footers, and brand
  layout-profile placement. Diagram/icon PNGs are rasterized by the Node workers (with a Pillow fallback) and
  written to `<output_stem>-diagrams/`.
- **strict** → `StrictSlideInjector.inject(...)` updates strict fields via XML; any `flexible` slides are rendered
  (diagrams disabled) and merged back with `HybridAssembler.assemble(...)`, preserving relationships/media/masters.
- The legacy PptxGenJS path (`workers/pptxgen_runner.js` via `NodePptxGenRunner`) is retained but **not used** in the tested freeform/brand/strict flows.

### LLM provider routing (config.py + main.py + orchestrator.py)

- `LLM_PROVIDER` selects `openai_compatible` (default) or `bedrock`. The default is a **local** OpenAI-compatible
  model (Qwen via LM Studio / Metis) — *not* Bedrock. Bedrock (Sonnet/Haiku) is a fallback path.
- Jobs accept `planner_profile=fast|deep`: `fast` = default local Qwen; `deep` = premium planner (Minimax via Athena),
  built by `model_copy`-ing settings onto the `DEEP_PLANNER_*` config.
- **Visual QA uses a separately-configured vision client** (`VISION_*` env), so a vision-capable model can inspect
  rendered slides even when the planner is text-only or slow.

## Critical Design Constraints

1. **Structure before rendering** — build/validate the outline ("ghost deck") before generating full slide content or PPTX.
2. **LLMs return validated specs/strings only** — Python/Node services own all file I/O, XML mutation, ZIP repackaging, and validation. Never let model output execute as the source of truth for a slide.
3. **Strict mode is preserve-first** — XML-level field injection only, no diagram assets generated; unmapped required fields get `[INSERT CONTENT HERE]` plus a warning. Strict slide geometry/formatting must survive.
4. **Source grounding** — `source_refs` is the canonical generated-slide citation field and `sources` is the rendered human label. Numeric claims not supported by uploaded source/inventory/metrics are tagged `[source needed]`; prompt-only decks may not claim `Uploaded source`; invented labels normalize to `[source needed]`.
5. **Safe XML parsing** — `lxml.etree.XMLParser(resolve_entities=False, no_network=True)`; `defusedxml.lxml` is deprecated.
6. **PPTX namespaces** — `<p:txBody>` is the **presentation** namespace (`p:`); its children (`<a:p>`, `<a:r>`, `<a:t>`) are drawingml (`a:`). Search for txBody from a shape with `{ns_p}txBody`, not `{ns_a}txBody`.
7. **No-fallback acceptance** for generated modes — the smoke gate expects no planner fallback and no build warnings.

## Request Contract

`POST /api/jobs` is a multipart form (not JSON). Key fields:

| Field | Values | Notes |
|-------|--------|-------|
| `generation_mode` | `freeform` \| `brand` \| `strict` | empty → `freeform` when no `template_id` |
| `template_id` | template UUID | required for `brand`/`strict`; forced to `__freeform__` for freeform |
| `planner_profile` | `fast` \| `deep` | model routing (Qwen vs Minimax) |
| `quality_profile` | `fast` \| `balanced` \| `showcase` | default `balanced` |
| `length_strategy` | `auto` \| `concise` \| `expanded` | default `auto` |
| `run_visual_qa` | bool | default true |
| `instructions` | text brief | |
| `documents` | uploaded files | ingested with provenance |

Other endpoints: `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/preview[/{image}]`,
`GET /api/jobs/{id}/download?format=pptx|pdf`, `POST /api/jobs/{id}/regen/{slide_index}`;
templates: `POST /api/templates/analyze`, `GET /api/templates[/{id}]`, `PATCH/DELETE /api/templates/{id}`, `POST /api/templates/{id}/duplicate`.

## Pydantic Gotchas

- Avoid `schema_json` as a field/param name — shadows `BaseModel.schema_json`.
- Don't use `from __future__ import annotations` with Pydantic — breaks runtime eval.
- Use `model_copy(update={...})` for immutable record updates (used heavily for deriving deep-planner/vision settings).
