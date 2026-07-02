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
with an HTML/CSS design-system renderer (python-pptx fallbacks), an optional plan-review gate, source
provenance, diagram/icon rendering, ConsultingQA repair, and a visual-QA repair loop.
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

External runtime tools (installed via Homebrew on this machine) are required for the full pipeline. The default
`native` renderer needs **no** external tools (the legacy headless-Chrome image renderer has been removed):
- `node` — rasterizes diagrams/icons (Sharp + react-icons) for the `authored`/`legacy` renderers; deterministic Pillow fallback if Node deps are absent.
- `soffice` (LibreOffice) — renders PPTX → PDF for visual QA and the `/download?format=pdf` export.
- `pdftoppm` (Poppler) — PDF → slide preview images.

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

# Containerized full app — one container, backend serves the built frontend on :8080 (UI E2E)
./scripts/e2e-ui.sh                     # build + start, wait on /api/health, print UI (http://localhost:8080)
./scripts/e2e-ui.sh start --no-build    # skip rebuild;  also: stop | restart | logs | status

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
    → DesignAgent → ⟦plan-only gate⟧ → PptxBuilder → VisualQAAgent → deterministic QA repair loop
        │
        ├── Storage: LocalStorage (data/jobs/<id>/…) + SQLiteStore (aiosqlite, data/slideforge.db)
        └── Node workers (app/workers/): diagram_renderer.js · icon_renderer.js  (Sharp/react-icons)
```

### Job lifecycle

`queued → analyzing → planning → [planned] → generating → qa ⇄ repairing → done | review_failed | error`

A job is created via `POST /api/jobs` (multipart form), enqueued on `JobQueue`, and executed by
`JobOrchestrator.run_job` in the background. Config travels in the job's `config_json` and selects mode +
quality knobs (see "Request contract" below).

**Optional plan-review gate:** by default jobs run straight through. When `plan_only=true` (generated modes only),
the job stops at `planned` after planning — outlines can be inspected/edited via `GET`/`PATCH /api/jobs/{id}/outline`
— and resumes to render via `POST /api/jobs/{id}/render` (which sets `render_from_plan` in `config_json`). `done` is
the clean terminal state; `review_failed` means the deck rendered but still has unresolved visual-QA or
editing-contract issues (it is still downloadable). The visual-QA loop alternates `qa`/`repairing` until issues
clear, the repair makes no further progress, or `QA_MAX_ROUNDS` (default 2) is hit.

### Frontend (single-page stepper, no router)

There is no router (`react-router` is not a dependency). `App.tsx` owns all state and advances a `Screen` through
`mode → setup → brief → job → [plan] → review`, rendered by `components/` (`ModeScreen`, `SetupScreen`,
`BriefScreen`, `JobScreen`, `PlanReviewScreen`, `ReviewScreen`) with a `Stepper`; `TopBar`, `LibraryRail`,
`SlideLightbox`, and `StrictSchemaEditor` sit alongside. The `plan` screen (`PlanReviewScreen`) is the plan-review
cockpit for `planned` jobs (outline editing + render trigger); `ReviewScreen` carries a "deck intelligence" cockpit
(planning health, editing-contract status, template-frame/clone mapping, deviation logs, QA history, rendered-slide
audit). Helpers: `api/client.ts` (typed fetch wrappers + shared types), `types.ts` (UI enums), `ui.ts`, `qa.ts`.
The old `pages/*` routed components were removed.

In Docker/production a single uvicorn process serves both the API and the built frontend (`StaticFiles` mount at
`/` when `FRONTEND_DIST_DIR` exists, port 8080); in dev the Vite server (:5173) proxies `/api` → :8000.

### Service facades → packages

Three large services are stable public facades that delegate to internal packages (behavior-preserving refactors —
keep the facade's public shape stable; `tests/test_refactor_boundaries.py` guards the facade imports + behavior):

- `services/content_planner.py` (`ContentPlanner`) → `services/planning/` (`context`, `exhibit_selection`, `spec_gate`, `llm`, `narrative`, `blueprint`, `specs`, `outlines`, `repairs`, `grounding`, `exhibits`, `constants`). `ContentPlanner` *subclasses* one `*Mixin` per module (not delegation). The newer layers — `context` (source compression → story map), `exhibit_selection`, `spec_gate` (post-plan spec validation/repair), and `narrative` (one LLM pass rewriting the action-title ladder into a single Situation→Complication→Resolution story, gated so a bad rewrite can't degrade the deck) — operate on the story-map/evidence types in `models/planning.py` (`StoryMap`, `StoryBeat`, `EvidenceUnit`, `SourceCompression`, `SpecGateReport`). `PLANNER_DECOMPOSE=true` (default) splits planning into smaller batched per-section LLM calls. **The LLM authors and refines content; deterministic code validates + provides a no-LLM fallback — it does not rewrite content on the LLM path.** Flow: sentence-aware source extraction → author (`{title, body}` point objects) → `spec_gate` (DETECT defects + structural-safety repairs: dedup, fit-to-box, source grounding) → `narrative` (LLM title-ladder) → `refine` (`planning/refine.py` — the critique-and-refine pass: per slide the model gets what it produced + the intent/evidence/contract/detected-defects and returns an enhanced slide; defensively applied — a refinement that is weak or introduces an ungrounded number is rejected) → re-ground numerics → drop thin slides (fewer, denser) → `_backstop_weak_titles` (the only remaining deterministic title rewrite on the LLM path, a last resort). The title gate (`spec_gate._gate_title_is_weak`, `consulting_qa._has_action_signal`) tests grammar/completeness, not a first-word-verb whitelist. The canned title banks (`repairs._repair_weak_action_title`/`_benchmark_title_repair`, `outlines._keyword_action_title`/`_themed_action_title`, `content_planner._polish_source_action_titles`, `context._claim_to_action_title` verb-graft) are demoted to the no-LLM fallback + last-resort backstop; the fallback path itself never grafts a verb onto a complete sentence (`context._claim_reads_as_sentence`). **Exhibits are protected the same way as titles:** with a configured LLM client, `exhibit_selection._apply_exhibit_selection` refreshes a slide only on a real defect (incomplete exhibit, repeated fingerprint/over-budget type, blown metric budget) — never on a keyword-heuristic disagreement — and any rebuild is authored-first (`_authored_reselection_target` demotes scaffold-dependent archetypes to a list shape compiled from the slide's own points); `_ensure_core_exhibit_mix` is fallback-only. Quote exhibits quote a real source sentence (`specs._quotable_sentence`) or omit the quote — never a canned fake quotation. Evidence binding (`StoryBeat.evidence`) + the type+density+char-budget authoring contract (`llm._beat_authoring_contract`, computed for the job's resolved `design_language`) feed both the author and refine prompts; `content_planner._ensure_structural_variety` breaks runs of >2 consecutive list-shaped slides. `tests/test_planning_decomposition.py::test_llm_path_deck_has_no_canned_strings` + `test_llm_authored_exhibit_survives_heuristic_disagreement` guard that canned banks/scaffolds never reach LLM-path output.
- `services/pptx_renderer.py` (`DeterministicPptxRenderer`) → `services/pptx_rendering/` (`assets`, `chrome`, `core_layouts`, `table_layouts`, `immersive_layouts`, `exhibit_layouts`, `drawing`, `constants`)
- `services/visual_qa_agent.py` (`VisualQAAgent`) → `services/visual_qa/` (`checks`, `preview`, `vision`, `constants`)

### PPTX build paths (`PptxBuilder.build_deck`)

`PptxBuilder` selects a renderer engine via `RENDERER_ENGINE` (default `native`). Any unrecognized value —
including the removed image-based `html` engine — resolves to `native`, and every generated render runs a
post-build **editability audit** (`_editability_audit`: a slide ≥40% picture coverage emits an `editability`
build warning), so generated decks always download as editable PowerPoint. For generated (freeform/brand) slides:

- **`native`** (default) → `NativePptxRenderer` (`services/pptx_native/`: `geometry`, `theme`, `components`,
  `primitives`, `renderer`): builds **real, editable** python-pptx shapes/text that reproduce the design-system look
  (rounded cards, `effectLst` shadows, `gradFill` backgrounds, motifs, dark/light rhythm, design-language
  typography). Computed auto-layout (`geometry.grid/column_split/stack`) replaces hardcoded EMU. Consumes the
  planning `pinned_primitive` + `fit.CAPACITIES` budgets. Reuses the renderer-agnostic
  `slide_design/{design_system,fit,content}` modules (`_normalize_items` etc.) but emits native shapes. Header text
  boxes are sized to their estimated height (no title/subhead overlap), decorative motifs stay in-bounds, and the
  `rendered_slide_audit` geometry checks (overlap/occlusion/bounds/unicode-bullets/small-text) are guarded by
  `tests/test_native_renderer_audit.py`.
- **`authored`** → `AuthoredPptxRenderer`: content-aware composition facade over the deterministic renderer that
  keeps **editable** PPTX text + the native drawing layer and degrades weak diagram requests into safer
  card/editorial compositions. The resilient flat-native fallback.
- **`legacy`** → `DeterministicPptxRenderer.render(...)` directly — the original pure-Python renderer (positioning,
  fonts, colors, charts, icons, tables, diagrams, footers, brand layout-profile placement). Diagram/icon PNGs are
  rasterized by the Node workers (Pillow fallback) into `<output_stem>-diagrams/`.

- **brand** first attempts a full clone of the *uploaded* template PPTX via `BrandTemplateCloneRenderer` (real
  master/layout/theme reuse); if the clone produces nothing it strips template frames and falls back to the engine
  above. Set `RENDERER_ENGINE=legacy` to skip cloning entirely. With `BRAND_LAYOUT_INSTANTIATION=true` (default off),
  `BrandLayoutInstantiationRenderer` runs *before* the clone and builds new slides from the template's **layout
  library** (`slides.add_slide(layout)` + role-matched placeholder fill), falling back to the clone path if it yields
  nothing — this lifts the "capped at the uploaded file's slide count" ceiling.
- **strict** → `StrictSlideInjector.inject(...)` updates strict fields via XML; any `flexible` slides are rendered
  (diagrams disabled) and merged back with `HybridAssembler.assemble(...)`, preserving relationships/media/masters.
- The legacy PptxGenJS path (`workers/pptxgen_runner.js` via `NodePptxGenRunner`) is retained but **not used** in the tested freeform/brand/strict flows.

Cross-cutting generated-deck services run inside the pipeline: `GenerationEditingContract`
(`services/generation_editing_contract.py`) enforces a Claude-style layout-variety standard (varied layouts, no
repeated text-heavy slides, deliberate diagram use) and surfaces unresolved issues as warnings that can fail final
review; `rendered_slide_audit.py` audits the **built** PPTX for text/layout defects (served at
`GET /api/jobs/{id}/qa/rendered-slide-audit`); and `freeform_theme.derive_freeform_brand(...)`
generates a topic-seeded palette + a `design_language` preset for freeform decks that have no brand
template.

**Style & visual variety:** two declarative registries drive variety — `services/presentation_styles.py`
(planner persona/arc/section-labels/exhibit-mix per genre; `consulting` is the default and reproduces
the original prompt byte-for-byte) and `services/design_languages.py` (HTML renderer type-scale/geometry/
gradient/motif/font presets; `editorial_serif` is the default and reproduces the original CSS literals).
Both the `presentation_style` and `design_language` job knobs are `auto`-inferred from the brief and
resolved once in the orchestrator (persisted back to `config_json`), or set explicitly in the Brief
screen. The HTML `_choose_primitive` is family-complete + history-aware so generated decks rotate among
layout primitives instead of collapsing to repeated cards.

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
| `presentation_style` | `auto` \| `consulting` \| `investor_pitch` \| `sales` \| `academic_lecture` \| `technical_deep_dive` \| `keynote_narrative` \| `status_report_qbr` | default `auto` (inferred from brief); re-parameterizes the planner persona/arc/labels |
| `design_language` | `auto` \| `editorial_serif` \| `modern_geometric` \| `bold_minimal` \| `warm_magazine` \| `technical_mono` \| `data_forward` | default `auto`; selects the HTML renderer's visual preset (freeform) |
| `run_visual_qa` | bool | default true |
| `plan_only` | bool | default false; generated modes only — stop at `planned` for plan review |
| `instructions` | text brief | |
| `documents` | uploaded files | ingested with provenance |

Other job endpoints: `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/preview[/{image}]`,
`GET /api/jobs/{id}/download?format=pptx|pdf`, `POST /api/jobs/{id}/regen/{slide_index}`.
Plan review: `POST /api/jobs/{id}/render` (render a `planned` job), `GET`/`PATCH /api/jobs/{id}/outline`,
`GET /api/jobs/{id}/planning/{artifact}` (story map, blueprint, spec-gate, editing-contract, …),
`GET /api/jobs/{id}/qa/rendered-slide-audit`.
Templates: `POST /api/templates/analyze`, `GET /api/templates[/{id}]`, `PATCH/DELETE /api/templates/{id}`,
`POST /api/templates/{id}/duplicate`, plus asset reads `GET /api/templates/{id}/{assets,thumbnail/{img},logo}`.

## Pydantic Gotchas

- Avoid `schema_json` as a field/param name — shadows `BaseModel.schema_json`.
- Don't use `from __future__ import annotations` with Pydantic — breaks runtime eval.
- Use `model_copy(update={...})` for immutable record updates (used heavily for deriving deep-planner/vision settings).
