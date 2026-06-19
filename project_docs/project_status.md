# Project Status

**Last updated:** 2026-06-18

## Current Reality

This repository currently contains a strong local SlideForge vertical slice, not
a finished production deck generation system.

What exists today:

- FastAPI backend scaffold with local storage, SQLite persistence, job queue,
  template routes, job routes, and preview/download endpoints.
- React frontend scaffold for template setup, generation, review, and download.
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
- Focused backend regression suite of 172 tests (`172 passed` on 2026-06-18).
- App coverage after the backend refactor is `78%` overall for `app/*`
  (`/private/tmp/slideagent-refactor-coverage-after`), up from the 76%
  pre-refactor baseline.
- `project_docs/style_guide.md`, the consulting quality guide that now drives
  planner prompts and ConsultingQA checks.
- Local OpenAI-compatible model integration for LM Studio / Metis using
  `qwen3.6-35b-a3b-mtp` with `reasoning_effort=none` and a longer local
  planning timeout.
- Optional slower planning path tested against Athena
  (`http://athena.local:1240/v1`) using `minimax-m2.7`.
- Jobs now accept `planner_profile=fast|deep`. Fast uses the default Qwen
  planner profile; deep uses the configured Minimax/Athena planner profile.
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
  (`172 passed`) on 2026-06-18.
- Backend lint: `cd backend && ruff check app/ tests/` passed on 2026-06-18.
- Backend coverage after refactor:
  - App total: `78%`.
  - `ContentPlanner` facade: `92%`; extracted planning modules range from
    `71%` to `96%`.
  - `DeterministicPptxRenderer` facade: `97%`; extracted rendering modules
    range from `65%` to `95%`.
  - `VisualQAAgent` facade: `92%`; extracted VisualQA modules range from `81%`
    to `92%`.
- Frontend production build: `npm run build` passes.
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
    The latest output-polish Metis/Qwen vision smoke
    (`output-polish-metis-final`, using `http://metis.local:1240/v1`) produced
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
  metrics, and unmapped strict fields emit
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
  `python -m app.tools.all_mode_smoke --vision` from `backend/`.
- Current Minimax structural smoke:
  `python -m app.tools.all_mode_smoke --base-url http://athena.local:1240/v1 --model minimax-m2.7 --label minimax-m27`
  from `backend/`.
- Current frontend build requires dependencies to be installed first.
- Documentation should not claim the target architecture is already
  implemented until code and tests catch up.
