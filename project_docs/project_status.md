# Project Status

**Last updated:** 2026-06-23

## Current Reality

This repository currently contains a strong local SlideForge vertical slice, not
a finished production deck generation system.

What exists today:

- FastAPI backend scaffold with local storage, SQLite persistence, job queue,
  template routes, job routes, and preview/download endpoints.
- React frontend implementing the SlideForge design comp as a five-screen
  wizard (Mode → Setup → Brief → Generate → Review) plus a per-slide lightbox,
  wired to the live `/api` (job creation, status polling, preview images,
  QA/warnings, downloads, template analysis, and per-slide regeneration).
- The wizard also has a desktop Library rail for recent jobs and saved
  brand/strict templates, including strict schema override editing.
- Service implementations for template analysis, document ingestion, content
  planning, design planning, deterministic PPTX building, strict injection,
  hybrid assembly, rendering hooks, and visual QA.
- Backend service hotspots are now split behind stable public facades:
  `ContentPlanner` delegates to `app.services.planning`, the deterministic PPTX
  renderer delegates to `app.services.pptx_rendering`, and `VisualQAAgent`
  delegates to `app.services.visual_qa`.
- Python deterministic renderer for generated layouts, with the legacy
  PptxGenJS path no longer required for the tested freeform/brand flows.
- Strict schema validation for simple field values.
- Focused backend regression suite of 234 tests (`234 passed` on 2026-06-23).
- App coverage after the backend refactor is `78%` overall for `app/*`
  (`/private/tmp/slideagent-refactor-coverage-after`), up from the 76%
  pre-refactor baseline.
- `project_docs/style_guide.md`, the consulting quality guide that now drives
  planner prompts and ConsultingQA checks.
- Local OpenAI-compatible model integration for LM Studio or another compatible
  local endpoint using
  `qwen3.6-35b-a3b-mtp` with `reasoning_effort=none` and a longer local
  planning timeout.
- Optional slower planning path tested against a separate OpenAI-compatible
  local endpoint using `minimax-m2.7`.
- Jobs now accept `planner_profile=fast|deep`. Fast uses the default Qwen
  planner profile; deep uses the configured premium planner profile.
  VisualQA is configured separately from the planner and defaults to Qwen.
- Jobs also accept `quality_profile=fast|balanced|showcase` and
  `length_strategy=auto|concise|expanded` for generated decks.
- Deterministic generated-slide PPTX rendering for freeform and brand decks,
  including semantic icon rendering with optional `react-icons`/Sharp assets
  and a Pillow fallback, chart rendering from Qwen-style `data_points`, richer
  Claude-inspired layout archetypes, and a cleaner header motif without title
  underlines.
- `diagram_spec` support in generated slide specs for diagram-capable
  archetypes.
- Hermes-inspired deterministic SVG diagram rendering for dependency maps and
  framework cycles, with flat semantic shapes, arrow validation, safe label
  budgets, and brand-aware colors.
- Sharp/Node rasterization of validated SVG diagrams into PNG assets for
  Office-safe PPTX insertion.
- SVG, HTML preview, and PNG debug artifacts written next to generated decks in
  `<output_stem>-diagrams/`.
- Native PowerPoint shape diagram rendering remains as a fallback and emits
  explicit `diagram_render` build warnings if asset generation fails.
- Strict mode remains preserve-first and does not generate diagram assets.
- XML-level strict field injection for rigid templates.
- Strict template analysis now discovers PowerPoint table cells as structured
  fields, and the strict injector can update those table cells through OOXML
  without rebuilding the slide.
- Strict template analysis now discovers basic chart series names, categories,
  and cached values, and the strict injector can update those chart caches
  plus the embedded chart workbook through OOXML/openpyxl while preserving the
  chart frame and styling.
- Brand template analysis now extracts theme colors, theme fonts, reusable
  layout notes, the first detected logo image for generated decks, and an
  additive `layout_profile` covering common title, footer/source, logo, body,
  background, table-color, and chart-color cues.
- Document ingestion now assigns stable per-job source IDs to sections, tables,
  and metrics and carries a `source_index` for resolving generated
  `source_refs` into rendered section-level labels.
- Generated decks now treat `source_refs` as canonical citations and `sources`
  as human-readable footer labels. Invented model source labels and unsupported
  numeric claims normalize to `[source needed]`; prompt-only decks may not claim
  `Uploaded source`; unsupported numeric bullets are tagged inline.
- Source-aware fallback planning now selects richer blueprint archetypes from
  the uploaded material and uses `ExhibitCompiler` to build source-derived
  comparison/reference tables, KPI charts, native line charts, checklists,
  process exhibits, evidence inventories, and 2x2 matrices.
- Qwen-backed generated modes now have a clean output-polish smoke for the
  `data/Beyond Vibe Coding.docx` input: freeform, brand, and strict complete
  with no planner fallback, no planning warnings, no build warnings, and no
  visual-QA issues.
- Local DOCX ingestion fallback through `python-docx`.
- VisualQA now validates PPTX package structure, content-type declarations,
  internal relationship targets, text density, layout variety, source metadata,
  exact LibreOffice/Poppler-rendered slide images, and approximate preview
  images when exact render tools are unavailable. Approximate-preview vision
  findings are warnings, not hard blockers, and are not used as automatic
  repair triggers.
- Generated-slide jobs now run deterministic QA repair rounds for reliable
  actionable issues, persist repaired outlines back to SQLite, and stop when an
  actionable issue signature does not change after repair. ConsultingQA now
  also runs on outlines before the PPTX build and after each visual repair,
  repairing weak/duplicate titles, repeated bullets, missing exhibits, and
  missing source refs for generated slides. Strict slides remain preserve-only.
- Repeatable all-mode Qwen smoke runner:
  `python -m app.tools.all_mode_smoke --vision` from `backend/`.
- Automated tests covering freeform, brand, strict, local client parsing,
  strict field mapping, route mode validation, full orchestrator execution,
  brand template logo handling, semantic icon selection/rendering, unsupported
  numeric claims, strict placeholders, strict table cells, strict chart caches,
  warning-aware QA repair, and visual QA fallback behavior.

### Output polish pass (2026-06-18)

A second focused output-quality pass landed the five highest-leverage polish
themes identified for source-backed decks:

- **Source provenance contract:** `DocumentSection`, `DocumentTable`, and
  `DocumentMetric` now carry additive `source_id` fields, and
  `DocumentBundle.source_index` resolves those IDs to labels such as
  `Source Notes > External Brain`. Generated modes preserve legacy
  `sources: ["Uploaded source"]` compatibility but use `source_refs` as the
  canonical citation field.
- **ConsultingQA repair loop:** outline-level ConsultingQA now flags duplicate
  or weak action titles, overlong/compound titles, title/body mismatch,
  repeated or generic bullets, missing exhibits, missing source refs, and weak
  SCR/horizontal flow. `JobOrchestrator` runs this loop before build and after
  visual repair; repaired outlines are persisted.
- **Source-derived planning and exhibits:** fallback decks use a source-aware
  blueprint, avoid Beyond Vibe Coding demo-language leakage on unrelated
  sources, and compile exhibits from nearby sections/tables/metrics through
  `ExhibitCompiler`.
- **Renderer and VisualQA expansion:** deterministic rendering supports native
  line charts and 2x2 matrices; VisualQA flags metric charts without metrics,
  line charts with fewer than three points, and unlabeled 2x2 matrices as
  repairable exhibit issues.
- **Brand fidelity profile:** brand analysis extracts additive layout-profile
  cues for header/title, footer/source, logo, body bounds, background fill, and
  representative table/chart colors. Brand rendering uses those cues when
  present while keeping old deterministic defaults as fallback.

Important caveat: this is still a vertical slice, not a finished world-class
deck engine. The new provenance, consulting repair, exhibit compilation, and
brand-profile paths materially improve deck polish, but manual Office review,
broader diagram/chart families, richer brand-template interpretation, and more
non-demo source smokes remain the next quality frontier.

### Qwen production-polish pass (2026-06-23)

This pass moved the local Qwen E2E path from "mechanically valid" toward
production-grade generated decks for the Beyond Vibe Coding source document,
while keeping the deterministic title/layout rules generic rather than
hard-coding demo-specific copy.

- **Style-guide alignment:** planner prompts, consulting QA, spec-gate repair,
  and visual QA now enforce sharper action titles, title/body support, exhibit
  fit, evidence grounding, no repeated slide frames, and stronger
  slide-to-slide narrative rhythm in line with `project_docs/style_guide.md`.
- **Qwen planning robustness:** the OpenAI-compatible client and planner path
  handle Qwen JSON/schema behavior more reliably, including structured-response
  parsing, repair retries, and local-model token/timeout expectations.
- **No repeated-slide feel:** design selection and VisualQA now cap repeated
  heavy visual treatments across the full deck, not just adjacent slides. The
  system preserves genuinely source-specific repeats when justified, while
  diversifying comparison tables, reference tables, dependency maps, cycles,
  code panels, charts, and other high-salience layouts.
- **Source/exhibit grounding:** source labels and source refs are normalized
  more strictly; prompt-only decks cannot claim uploaded material; model-added
  `[source needed]` markers are retained for unsupported numeric claims but
  removed from source-backed nonnumeric metadata that would not render into the
  PPTX.
- **Fallback quality:** deterministic fallback planning now preserves a core
  exhibit mix for source-rich decks and re-runs duplicate-title repair after
  spec-gate changes, so the safety path does not collapse into repeated
  checklist/callout slides.
- **Renderer polish:** generated cover, table/reference, dependency map,
  framework/cycle, matrix, quote/sidebar, and closing layouts received spacing,
  text fitting, chrome, and shape-treatment improvements to better match the
  reference deck's authored rhythm.
- **Smoke reporting:** `app.tools.all_mode_smoke` now separates final planning
  warnings from consulting repair history, so fixed issues do not masquerade as
  acceptance failures.

Latest acceptance artifact:

- `/private/tmp/slideagent-polish-qwen-allmodes-v9/all-mode-qwen-allmodes-fast-v9-smoke-report.json`
- Freeform: 12 slides, no planner fallback, no planning warnings, no build
  warnings, zero final visual-QA issues.
- Brand: 12 slides, no planner fallback, no planning warnings, no build
  warnings, zero final visual-QA issues.
- Strict: 1 slide, no planner fallback, no planning warnings, no build
  warnings, zero final visual-QA issues.
- Freeform and brand contact sheets were visually inspected for repeated slide
  patterns, wrapping, empty slides, and layout rhythm.

### Frontend wizard + preview/regen fixes (2026-06-18)

The frontend was rebuilt from the earlier tabbed scaffold into the SlideForge
design comp (imported from Claude Design, `SlideForge.dc.html`), and two
supporting backend gaps it exposed were fixed:

- **Wizard UI:** a five-screen flow — Mode (freeform/brand/strict) → Setup
  (brand/strict only) → Brief → Generate → Review — plus a slide lightbox.
  Ported the warm "paper" design system with light/dark themes and the
  Newsreader / Hanken Grotesk / IBM Plex Mono type stack. All screen data is
  live API data, not comp placeholders: the Generate screen maps backend job
  status (`queued→analyzing→planning→generating→qa→done`) onto an eight-stage
  pipeline with the real progress value; Review renders real preview images, QA
  stat cards (from `qa_summary`/warnings), warnings, and PPTX/PDF download
  links; the Setup screen uploads a PPTX to `POST /api/templates/analyze` and
  renders the extracted Brand DNA (colors/fonts/logo/layout notes) or strict
  field schema; the lightbox regenerates a slide via
  `POST /api/jobs/{id}/regen/{i}`. Layout shapes are stored under
  `frontend/src/components/` with shared tokens in `frontend/src/ui.ts`.
- **Freeform regenerate fix:** the regen route looked the template up via
  `store.get_template(job.template_id)`, which returns `None` for freeform jobs
  (they use the in-memory `__freeform__` sentinel), so per-slide regeneration
  404'd for every freeform deck. The route now resolves the freeform template
  the same way `run_job` does; `_freeform_template` was promoted to a public
  `JobOrchestrator.freeform_template()`.
- **Preview-image format consistency:** preview images are now uniformly
  `slide-*.jpg` across the real LibreOffice/Poppler renderer, the Pillow
  no-tools fallback (previously `slide-*.png`), the job/preview API routes
  (which only globbed `.jpg`), and the frontend. Previously the fallback wrote
  `.png` while the routes globbed `.jpg`, so a render-tool-less environment
  would have returned an empty preview list to the UI. Two stale tests that
  assumed render tools were absent (`test_orchestrator_modes` preview glob,
  `test_brand_template_support` thumbnail assertion) were corrected/made
  environment-robust; the suite is now genuinely `172 passed` in this
  tools-present environment.

### UI regression and container alignment pass (2026-06-19)

The post-overhaul UI review identified three non-mobile regressions plus stale
container assumptions. Those were addressed without changing the mobile layout
scope:

- **Truthful QA review state:** `GET /api/jobs/{id}` now returns
  `qa_issues` from the latest QA round in addition to the existing
  `qa_summary` and pipeline `warnings`. The Review screen and slide lightbox
  derive pass/warning state from both latest QA issues and pipeline warnings,
  replacing the earlier optimistic hard-coded horizontal-flow pass message.
- **Recovered saved work access:** the new desktop Library rail lists recent
  jobs and saved brand/strict templates. Users can reopen completed jobs in
  Review, inspect active/error jobs in the Generate status screen, use saved
  templates for new jobs, and edit strict schema overrides (`required`,
  `max_chars`, allowed `values`) through a modal backed by `PATCH
  /api/templates/{id}`.
- **Visible regeneration failures:** slide regeneration errors now surface
  inline in the lightbox using backend `detail` messages where available,
  instead of being swallowed.
- **Docker/runtime alignment:** Docker now builds the frontend with `npm ci`,
  installs backend Node worker dependencies from `backend/package-lock.json`,
  serves the built frontend from `/app/frontend/dist`, and persists SQLite,
  templates, and job artifacts under `/app/data`, matching
  `docker-compose.yml`'s `./data:/app/data` volume. Compose now passes through
  the local planner, deep planner, vision, AWS/Bedrock, QA, and worker
  concurrency environment knobs from `.env`, and `.dockerignore` excludes
  local caches, build artifacts, generated data, `node_modules`, and `.env`
  secrets from the build context.

## Historical Context

The old implementation preserved in git history at commit `ade041c` had useful
patterns worth recovering:

- Structured Bedrock calls with Pydantic output models.
- LLM-backed deck planning, content generation, and coherence checks.
- XML-level text injection for template preservation.
- A broader backend/frontend test suite.

However, that implementation was organized around an obsolete two-mode product
model. The rebuild should borrow its service discipline and tests, not restore
its product assumptions wholesale.

## Target Direction

The product direction is now three first-class modes:

- `freeform`: generate a complete deck from a prompt and optional documents.
- `brand`: use a PPTX as a brand/master-template reference while generating new
  slides.
- `strict`: preserve a rigid PPTX structure and update designated fields through
  XML-level injection.

The quality source of truth is [style_guide.md](./style_guide.md). The
architecture target is documented in [architecture.md](./architecture.md).

## Next Milestones

1. **Docs alignment**
   - Keep PRD, architecture, and status docs aligned around the three-mode
     target.
   - Keep current-vs-target status honest for future agents.
   - Keep `implementation_plan.md` marked as historical where completed
     vertical-slice work has moved into current implementation status.

2. **Source and exhibit depth**
   - Broaden source-reference use in speaker notes and future frontend review
     surfaces.
   - Add more deterministic exhibit choices for richer tables, multi-series
     metrics, and source-derived diagrams.
   - Expand clean Qwen no-warning smokes beyond the Beyond Vibe Coding source
     document.

3. **Diagram expansion**
   - Add more deterministic diagram kinds, starting with hub-spoke, layered
     system, and process flow.
   - Improve diagram/content label QA so diagrams avoid weak, copied, or
     fragmentary model labels.

4. **Model and visual smoke coverage**
   - Run Minimax structural smoke against the new diagram path.
   - Run Qwen vision smoke against the new diagram path for freeform and brand.
   - Keep no-fallback behavior as the default acceptance gate for generated
     modes.

5. **Office and brand fidelity**
   - Add manual Microsoft Office compatibility checks for generated PPTX files.
   - Deepen brand-template fidelity analysis beyond the current colors, fonts,
     logo reuse, and layout-profile cues.
   - Broaden strict schema extraction for additional charts, status indicators,
     and other complex PowerPoint objects.

## Verification Evidence

- Backend tests: `cd backend && python -m pytest tests/ -q` passed
  (`234 passed`) on 2026-06-23.
- Backend lint: `cd backend && ruff check app/ tests/` passed on 2026-06-23.
- Backend coverage after refactor:
  - App total: `78%`.
  - `ContentPlanner` facade: `92%`; extracted planning modules range from
    `71%` to `96%`.
  - `DeterministicPptxRenderer` facade: `97%`; extracted rendering modules
    range from `65%` to `95%`.
  - `VisualQAAgent` facade: `92%`; extracted VisualQA modules range from `81%`
    to `92%`.
- Frontend typecheck (`npx tsc --noEmit`) and production build (`npm run build`)
  pass for the wizard UI on 2026-06-19.
- Docker Compose config validation (`docker-compose config`) passed on
  2026-06-19. A full Docker image build was not run because the local Docker
  daemon/Colima socket was unavailable in this environment.
- Local model list endpoint returned `qwen3.6-35b-a3b-mtp`.
- Local Qwen text generation works through `/v1/chat/completions`.
- Local Qwen vision accepts OpenAI-style `image_url` messages.
- Local render tools are available:
  - LibreOffice 26.2.4.2 via `/opt/homebrew/bin/soffice`
  - Poppler 26.06.0 via `/opt/homebrew/bin/pdftoppm`
- Direct reasoning check showed `enable_reasoning: false` still emitted
  reasoning tokens, while `reasoning_effort: "none"` returned answer content
  with `reasoning_tokens: 0`.
- Direct Athena check showed `minimax-m2.7` ignores `reasoning_effort: "none"`,
  `enable_reasoning: false`, and `chat_template_kwargs.enable_thinking: false`
  on the current server, but returns usable answer content when given enough
  completion budget.
- `data/Beyond Vibe Coding.docx` generated valid PPTX smoke artifacts with
  exact rendered slide images:
  - Latest Qwen production-polish all-mode smoke
    (`/private/tmp/slideagent-polish-qwen-allmodes-v9`) passed with no planner
    fallback, no planning warnings, no build warnings, and clean final visual
    QA in all modes:
    - Freeform: 12 slides, zero final QA issues.
    - Brand: 12 slides, zero final QA issues.
    - Strict: 1 slide, zero final QA issues.
    - Report:
      `/private/tmp/slideagent-polish-qwen-allmodes-v9/all-mode-qwen-allmodes-fast-v9-smoke-report.json`.
  - Latest post-refactor exact-code Qwen all-mode smoke
    (`/private/tmp/slideagent-refactor-smoke`) passed with no planner fallback,
    no build warnings, and clean final QA:
    - Freeform: 14 slides, zero final QA issues.
    - Brand: 14 slides, zero final QA issues after 1 repair round.
    - Strict: 1 slide, zero final QA issues, no diagram assets.
    - Freeform and brand each produced 2 SVG/HTML/PNG diagram artifacts in
      `<output_stem>-diagrams/`; strict produced none.
    - PPTX package validation passed for all three generated decks.
    - Report:
      `/private/tmp/slideagent-refactor-smoke/all-mode-refactor-qwen-smoke-report.json`.
  - Previous Hermes diagram smoke evidence remains available at
    `/private/tmp/slideagent-hermes-diagram-smoke-final`.
  - Qwen remains the fast default and works well for development iteration.
    The latest output-polish local-model vision smoke
    (`output-polish-local-final`, using an OpenAI-compatible local endpoint)
    produced
    freeform, brand, and strict PPTX artifacts with no planner fallback, no
    build warnings, no duplicate titles, and zero critical findings after
    repair. The source-backed generated decks rendered section-level source
    footers. Vision still emits warning/info notes because the smoke keeps
    non-critical advisory findings visible for review.
  - The generated renderer now uses semantic real-icon artwork in colored
    circles when backend Node dependencies are installed, falls back to
    deterministic Pillow icons otherwise, and renders generated charts from
    both `metrics` and Qwen-style `data_points`.
  - Generated layouts now include a broader set of archetypes inspired by the
    Claude reference deck: anti-pattern cards, quote/sidebar, dependency maps,
    framework/cycle diagrams, checklists, code/reference panels, section
    dividers, charts, callouts, and comparison grids. A design-agent
    diversification pass prevents QA repair from collapsing decks back into
    repeated two-column or icon-grid slides.
  - Planner and renderer cleanup strips model-emitted placeholder text such as
    `[Diagram Description: ...]` and avoids instructional meta-copy in rendered
    slides.
  - Minimax structural exact-render smoke produced valid freeform, brand, and
    strict decks. Brand and strict had zero structural QA issues; freeform had
    one source-placeholder warning from unsupported numeric claims.
  - Strict smoke artifacts preserve a rigid one-slide template through XML
    injection and render successfully.
- Repeatable all-mode smoke command writes a machine-readable report to
  `${TMPDIR:-/tmp}/slideagent-beyond-vibe/all-mode-<label>-smoke-report.json`,
  including `qa_rounds` and `qa_history` for each mode. It now supports
  `--base-url`, `--model`, `--timeout-seconds`, `--vision-base-url`,
  `--vision-model`, `--vision-timeout-seconds`, and `--label` for model
  comparisons.
- App-level orchestrator tests now run freeform, brand, and strict jobs through
  temp SQLite/local storage and verify completed job records, generated PPTX
  files, outlines, and strict XML field replacement.
- Orchestrator repair tests verify actionable warning-level QA issues trigger a
  generated-slide repair round, repaired outlines are persisted, and QA logs are
  saved for round 0 and subsequent repair rounds.
- API/orchestrator tests verify `planner_profile` validation and deep planner
  selection.
- Brand template tests verify flat brand-field compatibility, logo extraction
  from uploaded PPTX files, generated-slide logo rendering, embedded icon
  artwork in generated slides, and placeholder cleanup in rendered dependency
  diagrams.
- Design tests verify card-level semantic icon selection, distinct failure-mode
  icons, word-boundary matching so terms like `prototype` do not accidentally
  trigger `rot`, and deck-level layout diversification before and after QA
  repair.
- Planner tests verify unsupported numeric claims receive `[source needed]`,
  source-supported numeric claims pass without that placeholder, allowed
  numeric tokens are shown to the LLM, invented LLM source labels are
  normalized, missing source labels are repaired, prompt-only decks cannot
  claim `Uploaded source`, Qwen-style chart `data_points` become renderable
  metrics, source-backed nonnumeric placeholder metadata is stripped before
  spec-gate acceptance, and unmapped strict fields emit
  `[INSERT CONTENT HERE]` plus a warning.
- Strict-template tests verify table-cell field extraction and XML-level table
  cell injection while preserving neighboring cells.
- Strict-template tests verify chart series/category/value extraction plus
  XML-level cached chart and embedded workbook updates while preserving the
  chart frame.
- Office-compatibility tests verify VisualQA catches missing internal
  relationship targets and PPTX parts without content-type declarations.

## Verification Notes

- Current backend tests: `python -m pytest tests -q` from `backend/`.
- Current repeatable local-Qwen smoke:
  `python -m app.tools.all_mode_smoke --doc ../data/'Beyond Vibe Coding.docx' --modes freeform,brand,strict --quality-profile fast --length-strategy concise --label qwen-allmodes-fast`
  from `backend/`.
- Current Minimax structural smoke:
  `python -m app.tools.all_mode_smoke --base-url http://localhost:1240/v1 --model minimax-m2.7 --label minimax-m27`
  from `backend/`.
- Current frontend build requires dependencies to be installed first.
- Documentation should not claim the target architecture is already
  implemented until code and tests catch up.
