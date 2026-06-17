# Project Status

**Last updated:** 2026-06-17

## Current Reality

This repository currently contains a SlideForge scaffold, not a production-ready
deck generation system.

What exists today:

- FastAPI backend scaffold with local storage, SQLite persistence, job queue,
  template routes, job routes, and preview/download endpoints.
- React frontend scaffold for template setup, generation, review, and download.
- Service implementations for template analysis, document ingestion, content
  planning, design planning, deterministic PPTX building, strict injection,
  hybrid assembly, rendering hooks, and visual QA.
- Python deterministic renderer for generated layouts, with the legacy
  PptxGenJS path no longer required for the tested freeform/brand flows.
- Strict schema validation for simple field values.
- Focused backend regression tests currently passing: `74 passed`.
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
- Deterministic generated-slide PPTX rendering for freeform and brand decks,
  including semantic icon rendering with optional `react-icons`/Sharp assets
  and a Pillow fallback, chart rendering from Qwen-style `data_points`, richer
  Claude-inspired layout archetypes, and a cleaner header motif without title
  underlines.
- XML-level strict field injection for rigid templates.
- Strict template analysis now discovers PowerPoint table cells as structured
  fields, and the strict injector can update those table cells through OOXML
  without rebuilding the slide.
- Strict template analysis now discovers basic chart series names, categories,
  and cached values, and the strict injector can update those chart caches
  plus the embedded chart workbook through OOXML/openpyxl while preserving the
  chart frame and styling.
- Brand template analysis now extracts theme colors, theme fonts, reusable
  layout notes, and the first detected logo image for generated decks.
- Generated decks now normalize model-emitted source labels to `Uploaded source`
  or `[source needed]`, mark unsupported numeric claims with `[source needed]`
  when the number does not appear in uploaded source sections, inventory, or
  extracted metrics, and tag unsupported numeric bullets inline.
- Local DOCX ingestion fallback through `python-docx`.
- VisualQA now validates PPTX package structure, content-type declarations,
  internal relationship targets, text density, layout variety, source metadata,
  exact LibreOffice/Poppler-rendered slide images, and approximate preview
  images when exact render tools are unavailable. Approximate-preview vision
  findings are warnings, not hard blockers, and are not used as automatic
  repair triggers.
- Generated-slide jobs now run deterministic QA repair rounds for reliable
  actionable issues, persist repaired outlines back to SQLite, and stop when an
  actionable issue signature does not change after repair. Strict slides remain
  preserve-only.
- Repeatable all-mode Qwen smoke runner:
  `python -m app.tools.all_mode_smoke --vision` from `backend/`.
- Automated tests covering freeform, brand, strict, local client parsing,
  strict field mapping, route mode validation, full orchestrator execution,
  brand template logo handling, semantic icon selection/rendering, unsupported
  numeric claims, strict placeholders, strict table cells, strict chart caches,
  warning-aware QA repair, and visual QA fallback behavior.

Important caveat: this is still a vertical slice, not a finished world-class
deck engine. Exact rendered visual QA now runs locally after installing
LibreOffice (`soffice`) and Poppler (`pdftoppm`), and it is exposing the next
quality frontier: generated layouts still need broader visual systems,
document-level provenance, and exact-render repair behavior. Some advanced
template analysis, broader chart-type coverage, and brand fidelity analysis
also remain future work.

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

2. **Freeform vertical slice**
   - Generate a 5-slide deck from a short brief.
   - Add ghost deck/storyline planning with action titles.
   - Render deterministic PPTX and previews.
   - Run consulting QA and basic visual QA.

3. **Source-grounded content**
   - Improve document ingestion and provenance tracking.
   - Require numeric claims to cite source material or show `[source needed]`.
   - Move from generic `Uploaded source` labels to stable document/section
     source IDs once ingestion exposes that provenance.

4. **Brand-template support**
   - Extract brand DNA from uploaded PPTX files.
   - Generate new slides that follow brand colors, fonts, logos, and layout
     patterns.

5. **Strict-template hardening**
   - Replace high-level strict slide writes with targeted XML-level injection.
   - Extend schema extraction beyond text frames to tables, charts, and status
     indicators.
   - Preserve formatting and validate package integrity.

6. **QA and repair loop**
   - Add ConsultingQA for action titles, horizontal flow, SCR/Pyramid, MECE,
     one-message-per-slide, and source coverage.
   - Add VisualQA for rendered overlap, overflow, contrast, layout variety, and
     Office compatibility warnings.
   - Feed QA issues back into structured spec repair loops.

## Verification Evidence

- Backend tests: `74 passed`.
- Backend lint: `ruff check app/ tests/` passes.
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
  - Qwen remains the fast default and works well for development iteration.
    The latest quick exact-render Qwen smoke
    (`qwen-clean-placeholders`, using `http://192.168.50.93:1240/v1` because
    Python in this sandbox cannot resolve `metis.local`) produced freeform,
    brand, and strict PPTX artifacts with zero final structural/visual-rule
    issues after repair.
  - The latest Qwen vision smoke (`qwen-clean-placeholders-vision`) passed
    freeform and brand with zero critical findings after repair. Strict mode
    also passed structurally; Qwen vision still emits expected warning/info
    notes because strict mode intentionally preserves the supplied template
    rather than redesigning it.
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
