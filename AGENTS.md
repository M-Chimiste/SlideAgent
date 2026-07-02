# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Project Overview

SlideForge (repo directory: `SlideAgent`, backend package: `slideforge-backend`)
is an AI-powered PowerPoint generation service with **three first-class
generation modes**:

- **freeform**: generate a complete deck from a brief and optional documents,
  using built-in layout archetypes.
- **brand**: use an uploaded PPTX as a brand/master reference for colors,
  fonts, logo, and layout DNA while generating new slides.
- **strict**: preserve a rigid PPTX structure and update only designated fields
  through XML-level injection.

The pipeline builds a structured ghost deck before rendering, runs consulting
and visual QA, repairs generated-slide issues when possible, and emits a PPTX
plus previews, warnings, and debug artifacts. The quality source of truth is
[project_docs/style_guide.md](project_docs/style_guide.md).

## Current State

This is a strong local vertical slice, not a finished production deck engine.
All three modes work end-to-end through the backend smoke path, including
deterministic rendering, source grounding, diagram/icon rendering, strict XML
injection, and QA repair loops.

The latest recorded output-polish pass on 2026-06-18 improved planner and
renderer quality without changing the product caveat above:

- Uploaded sections, tables, and metrics now get stable provenance IDs plus a
  `DocumentBundle.source_index`; generated decks should use
  `source_refs` as canonical citations and `sources` as human-readable footer
  labels.
- ConsultingQA now runs on outlines before the PPTX build and again after each
  visual-QA repair. It flags weak/duplicate action titles, repeated or generic
  bullets, missing exhibits, missing source refs, and weak storyline flow; the
  planner can repair those issues from source sections.
- Fallback planning is source-aware and uses `ExhibitCompiler` to build
  source-derived comparison tables, reference tables, KPI/metric charts, line
  charts, checklists/processes, and 2x2 matrices without leaking the Beyond
  Vibe Coding demo language into unrelated decks.
- Brand analysis now adds `BrandDNA.layout_profile` for common title, footer,
  logo, body, background, table, and chart cues. Brand-mode rendering uses that
  profile when present and preserves deterministic defaults when absent.
- Renderer and VisualQA support the new native line-chart and 2x2-matrix
  exhibit paths, while strict mode remains preserve-first.

Since that pass, the generated-deck rendering and review flow changed
substantially:

- The default renderer is now an HTML/CSS design system rendered by headless
  Chrome (`RENDERER_ENGINE=html`), with an `authored` editable python-pptx
  renderer as automatic fallback and `legacy` (the original deterministic
  renderer) as rollback. Brand mode additionally clones the uploaded template
  PPTX via `BrandTemplateCloneRenderer`.
- An optional plan-review gate (`plan_only=true`) stops generated jobs at a new
  `planned` status for outline review/editing before rendering.
- A `narrative` planner pass rewrites the action-title ladder into one
  Situation/Complication/Resolution story; `GenerationEditingContract` enforces
  layout variety; and `rendered_slide_audit` inspects the built PPTX.

The main quality frontier is now manual Office compatibility review, richer
diagram/chart families, deeper brand/layout fidelity beyond the extracted
profile, and broader local-model smoke coverage across non-demo source docs.

Read [project_docs/project_status.md](project_docs/project_status.md) for the
current capability and verification baseline. Read
[project_docs/architecture.md](project_docs/architecture.md) for target
architecture plus current backend module boundaries.

Historical note: the old two-mode SlideAgent implementation preserved in git
history at `ade041c` is obsolete. Borrow its service discipline if useful, but
do not restore its product model.

## Development Environment

```bash
# Conda env (Python 3.11, miniforge3). The env name is still slideagent.
source ~/miniforge3/etc/profile.d/conda.sh && conda activate slideagent

# Use python, not python3, inside the env.
```

External runtime tools used by the full pipeline:

- headless Chrome/Chromium: the default `html` renderer prints slide HTML to PDF
  (binary auto-discovered; override with `SLIDEFORGE_CHROME_BINARY`). When
  absent, rendering degrades to the `authored` python-pptx renderer.
- `node`: rasterizes diagram/icon assets through Sharp/react-icons workers for
  the `authored`/`legacy` renderers; icon rendering has a deterministic Pillow
  fallback when Node deps are absent.
- `soffice`: LibreOffice PPTX-to-PDF rendering for visual QA and PDF export.
- `pdftoppm`: Poppler PDF-to-image rendering for slide previews (also the HTML
  renderer's PDF-to-slide-image step).

## Common Commands

```bash
# Backend dev server
cd backend && uvicorn app.main:app --reload --port 8000

# Backend Node workers for diagram/icon rendering
cd backend && npm install

# Frontend dev server (Vite :5173, proxies /api to :8000)
cd frontend && npm run dev

# Backend tests
cd backend && python -m pytest tests/ -q
cd backend && python -m pytest tests/test_orchestrator_modes.py -v
cd backend && python -m pytest tests/test_orchestrator_modes.py::test_orchestrator_runs_freeform_job_without_template -v

# Backend lint
cd backend && ruff check app/ tests/

# Backend coverage snapshot
cd backend && python -m coverage run --data-file=/private/tmp/slideagent-coverage -m pytest tests/ -q
cd backend && python -m coverage report --data-file=/private/tmp/slideagent-coverage --include='app/*'

# Frontend checks
cd frontend && npx tsc --noEmit
cd frontend && npm run build

# Repeatable local-model all-mode smoke
cd backend && python -m app.tools.all_mode_smoke --vision

# Deep/premium planner comparison, when Athena is available
cd backend && python -m app.tools.all_mode_smoke --base-url http://athena.local:1240/v1 --model minimax-m2.7 --label minimax-m27
```

There is no repo-level pytest/ruff/mypy config. Async tests use explicit
`@pytest.mark.asyncio` markers where needed. Most tests call route/service
functions directly rather than through an ASGITransport HTTP harness.

## Architecture

```text
React 19 + Vite + TypeScript frontend (plain; no Tailwind/Zustand/TanStack)
        |
        v
FastAPI backend (routes under /api; create_app() in app/main.py)
├── routes/ jobs, templates, health
├── JobQueue: in-process async background worker
└── JobOrchestrator: per-job pipeline and QA repair loop
        |
        v
DocumentIngester
  -> TemplateAnalyzer (brand/strict only)
  -> ContentPlanner
  -> DesignAgent
  -> [plan-only gate]
  -> PptxBuilder
  -> VisualQAAgent
  -> deterministic QA repair loop
```

Storage is local-first:

- `LocalStorage` writes job artifacts under `backend/data/jobs/<id>/...`.
- `SQLiteStore` persists jobs/templates/outlines/warnings in
  `backend/data/slideforge.db` by default.
- Node workers live in `backend/app/workers/`:
  `diagram_renderer.js` and `icon_renderer.js`.

### Job Lifecycle

`queued -> analyzing -> planning -> [planned] -> generating -> qa <-> repairing -> done | review_failed | error`

`POST /api/jobs` creates a multipart-form job, enqueues it on `JobQueue`, and
`JobOrchestrator.run_job` executes it in the background. Generation mode and
quality knobs live in `job.config_json`.

By default jobs run straight through. With `plan_only=true` (generated modes
only) a job stops at `planned` after planning so outlines can be reviewed/edited
(`GET`/`PATCH /api/jobs/{id}/outline`) and then rendered via
`POST /api/jobs/{id}/render`. `done` is the clean terminal state; `review_failed`
means the deck rendered but still has unresolved visual-QA or editing-contract
issues (still downloadable). The visual-QA loop alternates `qa`/`repairing`
until issues clear, stall, or `QA_MAX_ROUNDS` (default 2) is reached.

### Service Facades And Packages

Keep these public service facades stable:

- `app.services.content_planner.ContentPlanner`
- `app.services.pptx_renderer.DeterministicPptxRenderer`
- `app.services.visual_qa_agent.VisualQAAgent`

Their internals are intentionally split into smaller packages:

- `app.services.planning`: `context`, `exhibit_selection`, `spec_gate`, `llm`,
  `narrative`, `blueprint`, `specs`, `repairs`, `grounding`, `outlines`,
  `exhibits`, `constants` (mixins composed onto `ContentPlanner`; `context`
  builds the story map, `spec_gate` validates/repairs specs post-plan, and
  `narrative` rewrites the action-title ladder)
- `app.services.pptx_rendering`: `assets`, `chrome`, `core_layouts`,
  `table_layouts`, `immersive_layouts`, `exhibit_layouts`, `drawing`,
  `constants`
- `app.services.visual_qa`: `checks`, `preview`, `vision`, `constants`

When refactoring, preserve public imports, call signatures, job behavior,
smoke flags, generated PPTX semantics, and strict-mode preserve-first behavior.

### PPTX Build Paths

- `PptxBuilder.build_deck(...)` owns build-path selection; `RENDERER_ENGINE`
  (default `native`) picks the generated-slide engine.
- **freeform / brand (generated slides)** use one of three engines:
  - `native` (default): `NativePptxRenderer` (`app.services.pptx_native`) builds
    real, editable python-pptx shapes/text reproducing the design-system look
    (rounded cards, shadows, gradient backgrounds, motifs, dark/light rhythm),
    driven by the planning `pinned_primitive` + `fit` budgets. No external tools.
    The legacy headless-Chrome image renderer (`html_rendering`) has been removed;
    renderer-agnostic modules now live in `app.services.slide_design`.
  - `authored`: `AuthoredPptxRenderer`, a content-aware composition facade over
    the deterministic renderer that keeps editable PPTX text and the native
    drawing layer and degrades weak diagram requests to safer compositions.
  - `legacy`: `DeterministicPptxRenderer.render(...)` directly. The renderer
    owns positioning, fonts, colors, native charts, tables, icons, diagram
    assets, headers, footers, source display, text fitting, and contrast-aware
    foreground colors.
- Diagram-capable generated slides can emit `diagram_spec`; deterministic SVG
  diagrams are rasterized to PNG for Office-safe insertion and debug artifacts
  are written to `<output_stem>-diagrams/` (authored/legacy engines).
- **brand** first tries a full clone of the uploaded template PPTX via
  `BrandTemplateCloneRenderer` (real master/layout/theme reuse), falling back to
  the generated engine above when the clone yields nothing; `RENDERER_ENGINE=legacy`
  skips cloning. With `BRAND_LAYOUT_INSTANTIATION=true` (default off),
  `BrandLayoutInstantiationRenderer` runs before the clone and instantiates new
  slides from the template's layout library (`slides.add_slide(layout)` +
  role-matched placeholder fill), falling back to the clone path when it yields
  nothing.
- **strict** uses `StrictSlideInjector.inject(...)` for XML-level field
  updates. Strict mode does not generate diagram assets unless explicitly
  redesigned later; strict/flexible hybrid decks render flexible slides with
  diagram generation disabled before assembly.
- Mixed strict/flexible decks use `HybridAssembler.assemble(...)` while
  preserving relationships, media, masters, layouts, and content types.
- The legacy PptxGenJS worker path is retained but is not the primary tested
  path for current freeform/brand/strict flows.

Cross-cutting generated-deck services: `GenerationEditingContract`
(`app.services.generation_editing_contract`) enforces a Claude-style
layout-variety standard and can fail final review; `rendered_slide_audit`
audits the built PPTX (served at `GET /api/jobs/{id}/qa/rendered-slide-audit`);
`freeform_theme.derive_freeform_brand(...)` derives a topic-specific palette for
freeform decks without a brand template.

## LLM Provider Routing

- `LLM_PROVIDER` selects `openai_compatible` (default) or `bedrock`.
- The default local OpenAI-compatible planner is Qwen via LM Studio/Metis.
- `planner_profile=fast|deep` controls model routing:
  - `fast`: default local Qwen planner.
  - `deep`: premium local planner, currently Minimax via Athena when configured.
- `quality_profile=fast|balanced|showcase` controls output budget/detail.
- `length_strategy=auto|concise|expanded` controls generated deck length.
- `PLANNER_DECOMPOSE` (default true) splits deck planning into smaller batched
  per-section LLM calls.
- Visual QA uses separate `VISION_*` settings so a vision-capable model can
  inspect rendered slides independently of the planner.

## Critical Design Constraints

1. **Structure before rendering:** build and validate the ghost deck before
   creating PPTX output.
2. **LLMs produce structured specs only:** Python/Node services own file I/O,
   XML mutation, ZIP repackaging, layout, validation, and rendering.
3. **Strict mode is preserve-first:** update mapped fields through OOXML;
   preserve geometry/formatting; use `[INSERT CONTENT HERE]` plus warnings for
   unmapped required fields.
4. **Source grounding:** `GeneratedSlideSpec.source_refs` is the canonical
   citation field for generated modes; `sources` is the rendered human label.
   Unsupported numeric claims and invented citation labels are tagged
   `[source needed]`; prompt-only decks may not claim `Uploaded source`.
5. **Safe XML parsing:** use
   `lxml.etree.XMLParser(resolve_entities=False, no_network=True)`.
6. **PPTX namespaces:** `<p:txBody>` is the presentation namespace (`p:`);
   child text elements (`<a:p>`, `<a:r>`, `<a:t>`) are DrawingML (`a:`).
7. **No-fallback acceptance for generated modes:** smoke gates should pass with
   no planner fallback and no build warnings.
8. **Style guide as rubric:** planner prompts, ConsultingQA, VisualQA, and
   repair behavior should stay aligned with
   [project_docs/style_guide.md](project_docs/style_guide.md).

## Request Contract

`POST /api/jobs` is multipart form data. Key fields:

| Field | Values | Notes |
| --- | --- | --- |
| `generation_mode` | `freeform` \| `brand` \| `strict` | Empty defaults to `freeform` when no template is supplied. |
| `template_id` | template UUID | Required for `brand` and `strict`; freeform uses `__freeform__`. |
| `planner_profile` | `fast` \| `deep` | Model routing. |
| `quality_profile` | `fast` \| `balanced` \| `showcase` | Default `balanced`. |
| `length_strategy` | `auto` \| `concise` \| `expanded` | Default `auto`. |
| `run_visual_qa` | bool | Default true. |
| `plan_only` | bool | Default false; generated modes only. Stops at `planned` for plan review. |
| `instructions` | text brief | Used by planner. |
| `documents` | uploaded files | Ingested with provenance. |

Other important endpoints:

- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `GET /api/jobs/{id}/preview[/{image}]`
- `GET /api/jobs/{id}/download?format=pptx|pdf`
- `POST /api/jobs/{id}/regen/{slide_index}`
- `POST /api/jobs/{id}/render` (render a `planned` job)
- `GET`/`PATCH /api/jobs/{id}/outline`
- `GET /api/jobs/{id}/planning/{artifact}`
- `GET /api/jobs/{id}/qa/rendered-slide-audit`
- `POST /api/templates/analyze`
- `GET /api/templates[/{id}]`
- `PATCH /api/templates/{id}`
- `DELETE /api/templates/{id}`
- `POST /api/templates/{id}/duplicate`
- `GET /api/templates/{id}/assets`, `GET /api/templates/{id}/thumbnail/{image}`, `GET /api/templates/{id}/logo`

## Testing And Refactor Guidance

- The backend suite is now ~400 tests (collected):
  `cd backend && python -m pytest tests/ -q`. New suites since the last recorded
  baseline include `test_html_renderer`, `test_generation_editing_contract`,
  `test_freeform_theme`, and `test_planning_decomposition`. The prior
  "172 tests / 78% coverage" baseline is stale — re-run tests/coverage to
  confirm a current number before relying on it.
- Lint baseline: `ruff check app/ tests/`.
- Add or keep characterization tests before behavior-preserving extractions.
- Prefer focused subsystem tests plus full backend tests after touching shared
  planner, renderer, strict injection, or QA behavior.
- Generated PPTX tests should validate package integrity and inspect with
  `python-pptx` where practical.
- Diagram-related changes should verify SVG/HTML/PNG artifacts and ensure
  native PowerPoint fallback emits explicit `diagram_render` warnings.
- Strict-mode changes should verify XML-level injection, package validity, and
  no generated diagram assets.
- Do not introduce frontend cleanup in backend refactor passes unless the user
  explicitly asks for it.

## Pydantic Gotchas

- Avoid `schema_json` as a field or parameter name because it shadows
  `BaseModel.schema_json`.
- Do not use `from __future__ import annotations` with Pydantic models here;
  it can break runtime evaluation.
- Use `model_copy(update={...})` for immutable record updates and derived
  settings.
