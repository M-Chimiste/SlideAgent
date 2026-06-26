# Project Status

**Last updated:** 2026-06-25

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
- The frontend now includes an optional plan-preview path, `PlanReviewScreen`,
  lightweight outline editing for planned jobs, and a Review-screen
  "deck intelligence" cockpit for planning health, editing-contract status,
  template-frame mapping, clone/edit status, deviation logs, QA history, and
  rendered-slide audit findings.
- The wizard also has a desktop Library rail for recent jobs and saved
  brand/strict templates, including strict schema override editing.
- Service implementations for template analysis, document ingestion, content
  planning, design planning, deterministic PPTX building, strict injection,
  hybrid assembly, rendering hooks, and visual QA.
- Backend service hotspots are now split behind stable public facades:
  `ContentPlanner` delegates to `app.services.planning`, the deterministic PPTX
  renderer delegates to `app.services.pptx_rendering`, and `VisualQAAgent`
  delegates to `app.services.visual_qa`.
- Authored generated-slide renderer (`RENDERER_ENGINE=authored`, the fallback
  beneath the default `html` engine, with `legacy` retained as rollback) that
  wraps the proven deterministic PPTX renderer with an explicit
  composition-planning stage. It writes
  `composition_family`, `composition_signature`, `visual_intent`, and
  `render_engine` metadata into outlines, reduces visible composition cycling,
  keeps editable PPTX text for titles/body/source labels, and degrades weak
  diagram requests into safer non-diagram compositions.
- Python deterministic renderer remains the PPTX drawing layer for generated
  layouts, with the legacy PptxGenJS path no longer required for the tested
  freeform/brand flows.
- Strict schema validation for simple field values.
- Latest recorded full backend regression baseline was 234 tests
  (`234 passed` on 2026-06-23). Since then, focused regression checks cover
  the UX cockpit, plan checkpoint, authored renderer, rendered-slide audit,
  review-failed status, and template-following artifacts.
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
- Jobs now also support an optional planning checkpoint:
  `POST /api/jobs` accepts `plan_only=true`, terminal `planned` jobs persist
  outlines, planning artifacts, and the exact ingested source bundle, and
  `POST /api/jobs/{id}/render` resumes rendering from that persisted plan.
  `GET/PATCH /api/jobs/{id}/outline` exposes review-safe outline metadata and
  lightweight title/subheading edits before rendering.
- Rendered decks can now end in terminal `review_failed` instead of `done`
  when final QA or the editing contract still has unresolved actionable
  issues. Result files and previews remain available for review.
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
- Brand template setup now exposes template assets through API endpoints for
  thumbnails, extracted logo, and frame-map inventory, so the UI can show real
  source-deck thumbnails/logo and all schema-bearing slides.
- Brand mode now has a conservative Claude-style clone/edit path for suitable
  uploaded source decks. `BrandTemplateCloneRenderer` duplicates mapped source
  slides, edits inherited text/table/chart slots in place, preserves source
  chrome/media/relationships where safe, blocks weak template-frame mappings,
  and falls back to authored generated rendering only after recording the
  blocker.
- Brand clone/edit jobs now write template-following artifacts:
  `template-clone-edit.json`, a job-level `template-frame-map.json`,
  `template-deviation-log.json`, and placeholder/slot cleanup metadata. These
  artifacts record output-slide→source-slide mappings, edit targets, omitted
  source slides, closest viable source-frame alternatives, blocked weak
  matches, unsatisfied slot cleanup, unfilled inherited placeholders, and
  package cleanup.
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
- VisualQA and the rendered-slide audit now inspect full-slide text and PPTX
  XML for rendered content quality, generic/filler copy, raw markdown/table
  artifacts, generic diagram labels, composition rhythm, unfilled inherited
  placeholders, and Office package integrity. `GET
  /api/jobs/{id}/qa/rendered-slide-audit` exposes the audit payload.
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

### Config: root .env now loads regardless of cwd (2026-06-25)

`Settings.model_config` used `env_file=".env"` (cwd-relative), but the backend is
launched from `backend/`, so the repo-root `.env` was **never loaded** — every
LLM endpoint silently fell back to `config.py` defaults (notably `deep =
localhost:1240 / minimax-m2.7`). This is why a `planner_profile=deep` job errored
in the live UI test. Fixed by anchoring the env file to the repo root:
`env_file=str(BASE_DIR / ".env")` (Docker-safe — absent file → real env vars).
Verified from the `backend/` cwd that planner, deep planner, and vision all
resolve to `http://100.87.204.73:1240/v1` + `qwen3.6-35b-a3b-mtp`, a live call to
that endpoint returns, and no app code hardcodes an endpoint outside `config.py`.
Full suite still 395 passed (the one endpoint-asserting test overrides via
explicit init kwargs, which outrank the `.env`).

### Storytelling: decomposed generation + narrative title-ladder (2026-06-25)

With the HTML renderer polished, the quality ceiling moved to content. This pass
attacked it with two changes that also improve local-model reliability, wired to
the existing `planner_profile` toggle.

- **Decomposed slide generation.** The planner no longer asks the model for the
  entire deck in one JSON call (the thing that truncated/failed). It now authors
  slides in smaller units scaffolded by the existing per-slide `StoryBeat`s:
  **batched** (~4 slides/call) for the `fast` profile, **per-slide** (one focused
  call) for the `deep` profile. New `_generate_deck_slides` dispatcher +
  `_plan_with_llm_batched` / `_plan_with_llm_per_slide` / `_generate_slide_batch`
  in `planning/llm.py`; strategy is set per `ContentPlanner` instance
  (`main.py` default `batched`, `orchestrator._build_deep_planner` `per_slide`).
  A whole-deck-shaped batch response aborts decomposition and falls back to the
  intact monolithic `_plan_with_llm`; a short deck is backfilled per-slide from
  the deterministic fallback. Kill-switch: `PLANNER_DECOMPOSE=false`.
- **Narrative editor pass (the title ladder).** New `planning/narrative.py`
  mixin: one small LLM call rewrites the deck's action titles so they read
  top-to-bottom as a Situation→Complication→Resolution argument, seeded by the
  story map's thesis/arc. Each rewrite is run back through the existing
  deterministic polishers + weak-title gate and de-dup, so a bad rewrite can
  never degrade the deck; with no client (or any failure) it is a graceful
  no-op. Runs for all strategies, after spec-gate, before consulting QA.
  Persists a `narrative-pass.json` artifact (before/after titles) for the review
  cockpit. The Fast/Deep UI control gained helper copy describing the behavior.

Verification:
- Full suite **395 passed** (7 new decomposition/narrative tests in
  `tests/test_planning_decomposition.py`); ruff clean; frontend typecheck clean.
  Two qwen tests that asserted the monolithic call count were pinned to
  `decompose=False` (the path they validate, kept as the fallback).
- **Live qwen `fast`/batched** smoke **passed the full acceptance gate** (no
  truncation, `qa_passed`, `deck_quality.passed`) and produced a **coherent
  title ladder** on the Beyond Vibe Coding deck: reproducibility gap → context
  rot → Memory Bank → tool-agnostic principles → rules file → current vs target
  → mindset shift → commit to persistent context. The deck rendered with real
  variety (cover, callout-list, bar chart, card grids, comparison, quote,
  closing) in the dark/light rhythm.
- **Live qwen `deep`/per-slide** smoke (via the new `all_mode_smoke
  --slide-strategy per_slide` flag) **also passed the full gate** (9 slides, no
  fallback, `qa_passed`, `deck_quality.passed`) with an even sharper, fully
  sentence-case title ladder: reproducibility gap → quantify context limits →
  Memory Bank → tool-agnostic principles → rules files cut ambiguity → stop
  marathon sessions → not the final state → commit to persistent context.

Follow-up landed: removed the generic deterministic fallback title
`"Use {X} to guide evidence, ownership, and execution"` (3 sites in
`planning/repairs.py`/`outlines.py`) that produced awkward titles like "Use the
case for implicit ground truth to guide evidence, ownership, and execution" when
the LLM title and its narrative rewrite were both rejected. Replaced with
`"Ground the next decision in {subject}"` plus a `_clean_title_subject` helper
that strips leading framing ("the case for …", articles). Verified on the
benchmark paper: a fresh fast/batched run and a deep/per-slide run both passed
the gate cleanly (9 slides, no fallback/warnings, 0 gate issues) through the
pure `.env`→metis/qwen path; the deep run's title ladder matched the reference
`Bootstrapping_Benchmarks_Executive.pptx` concepts (five harness layers, six
contract questions, model contracts).

Casing follow-up landed: qwen sometimes returns Title-Cased titles (the
deterministic helpers preserve casing, so the inconsistency came straight from
the model). Added `_sentence_case_title` (`planning/repairs.py`) applied to all
non-cover titles in the narrative pass. It only converts titles that are
*mostly* capitalized (a styling artifact) and leaves sentence-case titles with a
few proper-noun caps alone — so "Memory Bank" / "Agentic Coding" survive, while
"Unstructured AI Prompting Creates Context Rot" → "Unstructured AI prompting
creates context rot". Acronyms incl. plurals (AI, APIs, KPIs) and internal-caps
names (GitHub, iOS) are preserved. Covered by a unit test; full suite 396 passed.

Deck-length range widened (`planning/blueprint.py`, `_adaptive_slide_count`):
the LENGTH control now spans a real range instead of the old narrow 9–14. Per a
content-rich source: **Concise≈7, Auto≈12, Expanded≈22** (thinner sources scale
down: source 6/10/16, prompt-only 5/7/11). The brief can also name an exact
count ("make a 6-slide deck", "20 slides"), now matching single digits and
clamped to 3–30, which overrides the toggle. The decomposition fills to the
blueprint target even when the LLM story map returns fewer beats, so a requested
length is honored.

Source-aware cap added so Expanded does not pad a thin source: the toggle target
is capped at roughly `section_count + 1 + min(tables+metrics, 4)` (prompt-only
decks are uncapped/generative; an explicit brief count is honored literally).
Calibration: the benchmark paper (14 sections) had padded to 22 with ~6
generic/duplicate "closing remarks" slides and failed the gate; it now caps to
~16. A genuinely large source (Beyond Vibe, 40 sections) still reaches 22.
Verified live: the capped Expanded benchmark run produced **16 slides with a
single consulting warning** (down from 22 slides with ~6 padding slides, generic
titles, and 16 warnings) — a clean, varied deck. Count-pinned test fixtures
updated; a cap test added; full suite 398 passed.

Two edge-of-range content polish fixes (the warnings the capped Expanded deck
still tripped). **Root cause** (found by instrumenting the pipeline — plan() and
`apply_design` output were clean): both came from `_unique_consulting_title` in
the consulting-repair loop (`repair_outlines_for_consulting`, which runs on the
outlines *after* plan). Its fallback alternatives were
`"Use {subject} to sharpen the next operating choice"` /
`"Tie {subject} to source-backed execution"` /
`"Address {subject} before it shapes delivery"` — awkward, and all leading with
the same `{subject}`, so two slides on similar sections collided on a shared
subject prefix.
- Replaced those templates with varied-leading-verb alternatives
  ("Ground the next decision in {subject}", "Turn {subject} into …", …).
- Made the rewrite path **prefix-aware**: `_unique_consulting_title` now rejects
  a candidate whose four-word subject prefix is already taken, and
  `repair_outlines_for_consulting` threads a `seen_prefixes` set and triggers a
  rewrite on prefix collision (not just exact-title collision).
- Supporting near-dup detection (shared four-word prefix) and awkward-opener
  detection were also added to `_repair_repeated_action_titles`,
  `_finalize_action_titles` (new final planning guard), `spec_gate`, and
  `consulting_qa` so the issue is caught at every stage. Also added `ground`/`bind`/`act` to
  the consulting QA `ACTION_VERBS` set (so the new "Ground the next decision in
  …" replacements read as conclusions with a verb) and cleaned the interpolated
  subject of leading framing ("the case for …"). Covered by unit tests; full
  suite 400 passed. Verified live on the capped Expanded benchmark deck: both
  the near-duplicate subject and the awkward opener are gone across runs. (A
  separate, transient "repeated evidence bullet" body-content warning can still
  appear on the last stretched slide — inherent to pushing a source to its
  capacity — but that is not a title issue.)

### Polished HTML rendering engine — codex-skill/Gamma direction (2026-06-25)

This pass introduced a new rendering path that targets the core quality gap:
the prior generated decks (sparse cards with tiny floating text, weak
scattered-box "diagrams", repeated layouts, dead whitespace) come from
hand-positioning EMU shapes across ~7,700 LOC of python-pptx — an approach that
structurally cannot deliver auto-fit text, flexbox/grid distribution, shadows,
or content-fitted cards. The reference deck the user supplied
(`data/Bootstrapping_Benchmarks_Executive.pptx`) renders the *same content*
dramatically better; the gap is the **design system + storytelling**, not the
content.

Decision: emulate the codex-ppt-skill / Gamma "image-first" approach, but —
because there is no local image-generation model — author each slide as
**HTML/CSS** and rasterize with **headless Chrome → PDF → images → PPTX**. The
model's job is unchanged (it still emits the same structured specs), so this
stays reliable with the small local model; only the *rendering* changes. Slides
embed full-bleed as high-resolution images with speaker notes preserved as real
text.

- **New package `app/services/html_rendering/`**:
  - `design_system.py` — palette/typography tokens seeded from `BrandDNA` with
    a refined editorial house style (deep ink, cool teal, warm gold, cool-light
    surfaces) plus the deliberate **dark/light rhythm** (cover/statements/quotes/
    dividers/closing go dark; working content goes light) with run-smoothing.
  - `css.py` — one cohesive stylesheet; variety comes from *which* primitive a
    slide uses, never per-slide restyling. `.slide.dark`/`.slide.light` swap the
    working palette automatically.
  - `icons.py` — ~45 inline Feather-style SVG icons in circular badges with a
    keyword→icon resolver and safe default.
  - `templates.py` — ~11 layout primitives (cover, statement+ticks, quote,
    cards grid, rows, numbered steps, from→to split, comparison table,
    callout+mini-rows, metrics/bars, closing) dispatched by composition family +
    exhibit type + content shape. Derives a short bold **lead** from each plain
    sentence so flat bullets become reference-style titled cards. Defensively
    strips model-emitted meta-layout prefixes ("Left Column:", "Panel 2 -", …).
  - `renderer.py` — `HtmlSlideRenderer.render(outlines, brand, output_path)`
    matching the existing renderer interface. Discovers Chrome/poppler across
    platforms; **poll-and-kill** around headless Chrome (it writes the PDF in
    ~3s then hangs on exit on macOS, so we wait for a size-stable PDF and kill
    the process rather than waiting on exit).
- **Wired into `PptxBuilder` and made the default (`RENDERER_ENGINE=html`)**
  alongside `authored`/`legacy`. `_render_generated()` tries the HTML engine and
  **falls back to the authored renderer** on `HtmlRenderError` (missing
  Chrome/poppler), so the pipeline never hard-fails on a missing dependency
  (e.g. a minimal container). The config default was flipped from `authored` to
  `html`; the test suite is unaffected because tests construct
  `PptxBuilder(node_runner=...)` directly (authored `__init__` default) rather
  than from settings, so the running app is polished-by-default while the
  deterministic tests keep exercising the authored path.
- **QA interplay verified clean.** Concern: image slides carry no extractable
  PPTX text, so text-based QA could misfire. Empirically it does not — running
  the full `VisualQAAgent.inspect_deck` (structure + rule + rendered-slide-audit)
  on a 13-slide HTML deck produced **0 CRITICAL** issues and a single
  pre-existing outline-based `layout_repetition` warning. The structure/geometry
  checks handle a single full-bleed picture shape cleanly (no text frame → no
  false density/scanability flags; blank layout → no unfilled placeholders), and
  the rule/exhibit/narrative checks read the outlines, not the PPTX. Content-
  quality QA for HTML decks is therefore outline-driven (plus the vision pass
  when a vision client is configured); the audit's text-extraction checks become
  harmless no-ops on image slides rather than false failures.
- **Standalone visual-iteration harness** `app/tools/html_render_preview.py`
  (`--job <id>` or `--render-input <path>`) renders persisted outlines and
  builds a Pillow contact sheet — fast visual iteration without invoking the
  model.

Soft dependency: Google Chrome (found at
`/Applications/Google Chrome.app/...`; override with `SLIDEFORGE_CHROME_BINARY`)
and poppler `pdftoppm` (already required for previews). Raster DPI via
`SLIDEFORGE_HTML_DPI` (default 160).

Verification (this loop):
- Full suite **388 passed** with `RENDERER_ENGINE=html` as the default
  (8 new HTML-renderer tests incl. a Chrome-gated full render, plus JSON-salvage
  client tests). Ruff clean on the new/changed files.
- `VisualQAAgent.inspect_deck` on the HTML deck: 0 CRITICAL, 1 pre-existing
  WARNING (see QA interplay above).
- Rendered two real **local-model** decks (the planner specs were produced by
  `qwen3.6-35b-a3b-mtp` in prior jobs): the 13-slide Bootstrapping deck and an
  18-slide deck spanning 10+ composition families. Both render cohesively and
  approach the reference deck's quality — a categorical improvement over the
  prior `claim-gate-*`/`slideagent-*-replay` outputs.
- `metis.local:1240` was unreachable this session, so a live end-to-end model
  run is deferred; verification used real model-authored specs (replay), which
  exercises the exact planner→renderer contract.

Done in a follow-up pass this session:
- QA interplay verified clean (above); `RENDERER_ENGINE` default flipped to
  `html`; full suite 388 passed; end-to-end orchestrator test with the
  HTML engine added (`test_orchestrator_freeform_job_with_html_engine`).
- **Smoke acceptance gate made image-deck-aware.** `app/tools/all_mode_smoke.py`
  computed deck-quality metrics by introspecting PPTX *shape fills/fonts*, which
  are degenerate for an image-based HTML deck (0 fill colors, 0 font runs) — so
  a genuinely polished deck failed with "palette uses too few distinct rendered
  colors". The gate now detects image-based decks, skips the shape-color checks,
  and re-derives the text-quality checks (placeholder/meta-text, rendered-text
  defects) from the *outline content* so the gate stays meaningful. The smoke
  builder also now honors `settings.renderer_engine` instead of hardcoding
  `authored`.
- **Live `qwen3.6-35b-a3b-mtp` freeform run through the HTML engine** (against
  `metis.local:1240`) produced a cohesive 9-slide "Beyond Vibe Coding" deck —
  cover, executive-summary with a big metric callout, icon rows, card grids, a
  spotlight quote, and a closing with the accent ask-band, in the dark/light
  rhythm — a categorical improvement over the prior authored output. It **passed
  the full smoke acceptance gate cleanly**: no planner fallback, 0 build
  warnings, `qa_passed`, `deck_quality.passed` with an empty issue list,
  `image_based` correctly detected, layout diversity 0.889, every slide carrying
  a visual, and zero generic-title / placeholder / rendered-text defects (the
  text checks re-derived from outlines). qwen action titles were on-topic and
  specific (e.g. "Untracked decisions create a reproducibility gap for teams",
  "Unstructured prompting creates context rot"). Remaining rough edges
  (occasional off-topic decision-ask, jumbled comparison rows) are *planner
  storytelling* issues for the next loop, not rendering.

Storytelling fix this session:
- **Removed demo-language leakage in closing asks.** Four fallback `decision_ask`
  defaults were hardcoded to "Approve the first governed benchmark pilot." (the
  *benchmark* demo doc), so an unrelated deck (e.g. the vibe-coding deck) closed
  with an off-topic ask. Replaced the planning-path defaults
  (`planning/specs.py`, `planning/exhibits.py`, `content_planner.py` ×2) with a
  generic topic-agnostic ask. (A few benchmark-specific strings remain in the
  authored/legacy renderer's `immersive_layouts`/`drawing`, now fallback-only.)

Local-model reliability fix this session:
- **Hardened JSON extraction against truncated local-model output.** A live
  qwen run failed with "model response did not contain a JSON object" — with a
  configured LLM client there is *no* deterministic fallback (by design, for the
  acceptance gate), so one unparseable response = a failed job. Root cause: the
  verbose deck JSON occasionally exceeds the planner token budget and truncates,
  and `OpenAICompatibleClient.extract_json` (a) early-returned `None` on the
  first failed parse instead of trying the remaining strategies, and (b) used a
  *non-greedy* fenced-block regex (`\{.*?\}`) that broke on nested objects. It
  now tries all extraction strategies in sequence and, as a last resort,
  **salvages a truncated/unbalanced object** by closing open strings/arrays/
  objects (and trimming to the last complete element) — a salvaged partial deck
  is then completed by the existing small-model fallback-fill path. Also raised
  the `fast` planner token budget (`target_slide_count * 1400`, up to 16k) to
  reduce truncation at the source. Covered by new `extract_json` salvage tests.
- **Verified with 3 consecutive live qwen runs.** All 3 planned successfully
  with **no JSON-extraction failure** (the crash is fixed); 2/3 passed the full
  strict smoke gate, and the 1 that did not was *not* a crash — qwen emitted an
  unsupported "25%" statistic and source-grounding **correctly** caught and
  tagged it `[source needed]`, which the strict smoke gate counts as an
  unresolved warning (the app surfaces these as advisories, not job failures).
  That residual content variance — a small model occasionally inventing a stat —
  is the source-grounding frontier for the storytelling loop, not a reliability
  bug. Net: the hard intermittent failure the user hit is resolved.

Known follow-ups (next loops), in priority order:
1. **Storytelling depth** — the planner still emits weak/awkward titles, some
   meta-layout language as content ("Left Column:"), and thin comparison tables.
   Move toward codex-skill's outline-first + per-slide quality gates so the
   *content* matches the new rendering quality. (The renderer now sanitizes the
   worst meta-layout leaks defensively, but the source should stop emitting
   them.)
2. **Docker/CI parity** — add Chromium + poppler to the container image so
   deployed decks are polished rather than falling back to authored. Optionally
   reuse the HTML renderer's own crisp PDF/PNGs for previews to skip the
   redundant soffice re-render.
3. Bundle real web fonts (Newsreader/Hanken Grotesk) for closer typographic
   fidelity (network fetch was blocked this session; system Georgia/Helvetica
   stack is the current fallback) and tune the house gold. (Partly addressed by
   selectable design languages — see "Slide variety & multi-style generation".)
4. Increase layout variety — addressed by the "Slide variety & multi-style
   generation" pass (five new HTML primitives + family-complete, history-aware
   selection so card grids no longer dominate longer decks).

### Slide variety & multi-style generation (2026-06-25)

This pass attacks the HTML section's two open follow-ups — typographic/visual
sameness and card-grid dominance — by giving the deck an explicit, selectable
**presentation style** and **design language**, generating freeform palettes
instead of selecting from a fixed keyword cascade, and broadening the layout
primitive set with history-aware selection. The model contract is unchanged; the
new dimensions are resolved deterministically and threaded through the existing
pipeline.

- **Presentation styles.** Seven styles registered in
  `app/services/presentation_styles.py` (`STYLES`): `consulting` (default),
  `investor_pitch`, `sales`, `academic_lecture`, `technical_deep_dive`,
  `keynote_narrative`, `status_report_qbr`. Each re-parameterizes the planner
  persona/arc/title-rule/section-labels/exhibit-emphasis.
  `build_planner_system_prompt('balanced', 'consulting')` reproduces the existing
  `PLANNER_SYSTEM_PROMPT` **byte-for-byte** (`planning/constants.py`), so the
  default planning path is unchanged.
- **Design languages.** Six languages registered in
  `app/services/design_languages.py` (`LANGUAGES`): `editorial_serif` (default),
  `modern_geometric`, `bold_minimal`, `warm_magazine`, `technical_mono`,
  `data_forward`. Each is a preset of type scale / geometry / gradient angles /
  decorative motif / font stacks injected into `html_rendering/css.py`. The
  `editorial_serif` language reproduces the original CSS literals exactly
  (`card_radius=16`, `slide_padding='70px 84px 60px'`, `dark_angle=155`), so the
  default rendered house style is unchanged.
- **Generated freeform palette.** `app/services/freeform_theme.py` now
  **generates** the palette (primary, secondary, accent, bg_light, bg_dark)
  seeded from the deck topic's base hue + the design language's palette strategy
  (`_generate_palette`), replacing the old hand-tuned five-palette keyword
  cascade. The previously-dead `BrandDNA.background_dark` is now consumed by
  `resolve_theme` to feed the dark gradient base.
- **HTML layout primitives + selection.** Five new primitives — `matrix`,
  `timeline`, `layers`, `columns`, `big_stat` — registered in
  `html_rendering/templates._PRIMITIVES` (16 total). Selection is now
  **family-complete and history-aware**: `_natural_primitive` maps composition
  families/roles/exhibit types to specific primitives with no silent collapse of
  distinct families into `cards`, and `_choose_primitive` takes a `history`
  argument, applies a soft repetition cap, and rotates among compatible
  alternatives so one primitive no longer dominates a deck. Non-consulting styles
  also get exhibit-budget headroom (`exhibit_selection`), and the batched planner
  is shown prior slide archetypes to vary across batches (`planning/llm`).
- **Plumbing + UI.** `routes/jobs.py` accepts, validates (against
  `VALID_STYLES`/`VALID_LANGUAGES`), and stores `presentation_style` and
  `design_language` (both default `auto`) in `config_json`. The orchestrator
  resolves `auto` **once** (`infer_style` / `resolve_design_language`), persists
  the resolved values back to `config_json`, and threads `presentation_style`
  into `planner.plan()` and both values into `_template_for_generation` /
  `derive_freeform_brand`. Frontend wired end to end: `BriefScreen` dropdowns,
  `App.tsx` state/`FormData`/`applyJobConfig`, `types.ts` unions, and the
  resolved values surfaced in the `PlanReviewScreen`/`ReviewScreen` cockpit.

Brand-frame spreading (refinement, not a new renderer):
`generation_editing_contract.template_slide_for`/`_template_slide_for` accept an
optional `used_counts` dict (default `None`, preserving prior behavior) and
prefer the least-used viable source frame instead of a cyclic
`slide_index % len` fallback; `pptx_builder._attach_template_frames` threads a
per-deck `used_counts` counter, spreading brand template-frame reuse across the
uploaded deck on the existing clone/edit path.

Verification (this session):
- Full backend suite **419 passed**; `ruff check app/ tests/` clean; frontend
  `npx tsc --noEmit` and `npm run build` clean. New/updated tests:
  `test_presentation_styles.py`, `test_design_languages.py`, rewritten
  `test_freeform_theme.py`, structural-variety/design-language cases in
  `test_html_renderer.py`, a brand-spreading case in
  `test_generation_editing_contract.py`, and `test_brand_layout_renderer.py`.
- No-LLM / no-Chrome variety check: `derive_freeform_brand` + `resolve_theme`
  across four different topics produced four distinct
  (design-language, palette, card-radius, type-scale) signatures, and
  `render_slide_html` (HTML-string generation, no Chrome) confirmed the new
  family primitives render and the history-aware selector breaks card monotony
  (six same-family slides → multiple distinct primitives).
- The full live-model end-to-end run (HTML→Chrome→images render + vision QA,
  `app.tools.all_mode_smoke --vision`) was subsequently completed on both docx
  files against `qwen3.6-35b-a3b-mtp` — see "Live qwen e2e + content-fit polish
  (2026-06-26)" below.

Brand layout-library instantiation (Phase 2, behind a default-off flag): brand
mode can now build a deck by instantiating **new** slides from the uploaded
template's slide-LAYOUT library (`prs.slides.add_slide(layout)` + placeholder
fill) instead of duplicating its authored slides — removing the "capped at the
file's slide count" ceiling. New `app/services/brand_layout_renderer.py`
(`BrandLayoutInstantiationRenderer` + `role_for_layout`); `TemplateProfile` gains
a `layout_library` (`LayoutSpec`/`PlaceholderSpec`) captured by the analyzer, and
`SlideSpec` gains `layout_index`. Gated by `BRAND_LAYOUT_INSTANTIATION` (default
**false**); when on, `PptxBuilder` tries instantiation first and falls back to
the clone path, then generated rendering, so flag-off behavior is unchanged. Each
slide is matched to a role (cover/section/comparison/two_content/content/
title_only) with least-used spreading; picture/blank layouts are excluded (no
image assets). Covered by `tests/test_brand_layout_renderer.py`; an adversarial
multi-agent review of the implementation found no confirmed defects.

Still future work: per-slide mixing of clone + instantiation within one deck,
image-placeholder fill for picture layouts, and removing the now-superseded dead
`_layout_with_variety` cycle in `planning/grounding.py`.

### Live qwen e2e + content-fit polish (2026-06-26)

Ran the full pipeline end-to-end on the real local model (`qwen3.6-35b-a3b-mtp`)
for **both** source docx files (`Beyond Vibe Coding`, `Bootstrapping Benchmarks`)
through the default HTML engine (Chrome→PDF→images). Servers exercised:
`athena.local:1240` (freeform confirmation on both docs — it loads the model on
demand, so the first call is slow but completes cleanly) and `metis.local:1240`
(comprehensive: freeform + brand, `--vision`).

The pipeline works end-to-end with **no planner fallback and zero build warnings**
on every run, and variety is strong and consistent:
- 10–12 distinct layouts per 12-slide deck, layout-diversity 0.75–1.0, no layout
  repeated more than once in a row, every slide carries a visual, and the
  image-based HTML deck is correctly detected. The athena no-vision freeform runs
  were fully clean (0 QA issues).
- New variety knobs confirmed on the live model: `investor_pitch`
  (→ `bold_minimal`) vs `academic_lecture` (→ `editorial_serif`) produced distinct
  design languages **and** distinct title framings; `BRAND_LAYOUT_INSTANTIATION`
  against an 11-layout template instantiated a deck across 4 distinct
  role-appropriate layouts with real qwen content.

Content-fit polish — the qwen vision pass surfaced real fit defects on dense
slides (verified by viewing the rendered images, then fixed):
- `_lead_body` no longer splits on idiomatic verbs ("in turn") or inside an
  unbalanced bracket/quote, so derived leads are never dangling fragments
  ("Three files, in"; "Tests pass (or there").
- New `_fit` helper trims every card/row/list body to a complete first sentence
  (or a clean word boundary) instead of a mid-sentence CSS ellipsis.
- `.body-area { overflow: hidden }` + tighter row metrics + `MAX_ROWS 5→4` /
  `MAX_STEPS 10→8` stop dense lists overflowing the slide / colliding with the footer.
- Covered by new `test_html_renderer.py` cases; full suite **422 passed**, ruff clean.

These removed the rendering-defect classes (overflow/footer-collision, fragment
leads, bracket-splits, mid-sentence truncation). The CRITICAL findings that remain
are almost entirely **planner content-quality**, not rendering: title↔exhibit
count mismatches ("claims 'five harness layers' but shows one"), occasional
grammatically-incomplete bullets, and misleading chart data/labels — the
pre-existing "storytelling depth" planner frontier, not the variety/rendering work.

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

### UX cockpit, authored renderer, and Claude editing alignment pass (2026-06-25)

This pass shifted the current work from pure one-click generation toward a
reviewable "ghost deck" workflow and made the brand/template path more explicit
about when it is truly following a source deck versus falling back to generated
layouts.

- **Optional plan checkpoint:** job creation accepts additive `plan_only`; the
  orchestrator stops after ingestion, planning, design, consulting repair, and
  outline persistence with terminal status `planned`. Planned jobs persist the
  exact `DocumentBundle` as a source artifact so source IDs remain stable when
  rendering later. `POST /api/jobs/{id}/render` resumes rendering from the
  persisted bundle and outlines.
- **Outline review APIs:** `GET /api/jobs/{id}/outline` returns review-safe
  slide metadata including action title, subheading, narrative role,
  composition family/signature, visual intent/degradation, exhibit type,
  source refs, QA status/issues, and template-frame metadata. `PATCH
  /api/jobs/{id}/outline` supports planned-job edits to action title and
  subheading only.
- **Frontend cockpit:** Brief now has a secondary plan-preview path while
  normal "Generate deck" remains the default. `PlanReviewScreen` exposes the
  title ladder, source labels, composition metadata, template-frame mapping,
  slot-plan warnings, and render action. Review now has a compact deck
  intelligence cockpit for source coverage, story/spec gates, editing
  contract, visual review, clone/edit, frame map, deviation log, QA history,
  rendered audit, and composition rhythm. The slide lightbox shows per-slide
  outline/template metadata.
- **Authored renderer:** generated freeform/brand decks default to
  `AuthoredPptxRenderer`, which keeps the deterministic PPTX drawing layer but
  adds composition planning, visible rhythm repair, card-ratio checks, source-
  specific diagram gating, and metadata needed by the review UI and audit
  harness.
- **Editing contract:** `GenerationEditingContract` captures Claude-style
  requirements as machine-readable planning artifacts: varied visible
  compositions, no adjacent visible repeats, reduced card-grid defaults,
  grounded/sparse diagram use, template source-frame mapping, structural
  operations before content edit, slot-fit cleanup/split decisions, Unicode
  bullet sanitation, and separated multi-item content.
- **Terminal review failure:** final QA/editing-contract failures now produce
  `review_failed` instead of an optimistic `done`. The job remains terminal and
  downloadable/reviewable, but status responses include `final_qa_passed`,
  `final_review_passed`, unresolved issue counts, QA history, visual-review
  summary, and rendered-slide audit links/counts.
- **Rendered-slide audit:** every generated deck can persist
  `qa/rendered-slide-audit.json`, including extracted full slide text, issue
  markers, diagram labels, composition signatures, source coverage, layout
  diagnostics, visual rhythm, and final pass/fail status. The audit catches
  generic/filler copy, malformed fragments, raw markdown/table artifacts,
  unresolved placeholders, generic diagram labels, clipping/occlusion, and
  repeated visible rhythm.
- **Template assets:** template APIs now expose thumbnail names, individual
  rendered thumbnails, extracted logo, and frame-map inventory without changing
  the template DB schema. Setup uses those assets to show real template
  thumbnails/logo and all schema-bearing slides.
- **Source-deck clone/edit path:** brand mode attempts conservative
  duplicate-slide editing when the uploaded PPTX has usable source frames. It
  rewrites inherited text/table/chart slots, deletes planned excess inherited
  slots/media placeholders, preserves source chrome/media/relationships, and
  blocks weak mappings instead of forcing an unsafe template fit.
- **Template-following artifacts:** clone/edit writes
  `template-clone-edit.json`, job-level `template-frame-map.json`, and
  `template-deviation-log.json`. These record output-slide→source-slide
  mapping, edit targets, omitted source slides, weak/blocked frame matches,
  closest viable source-frame alternatives, slot cleanup, package cleanup, and
  intentional deviations from exact clone/edit.
- **PPTX XML placeholder audit:** clone/edit and VisualQA inspect final slide
  XML for empty inherited `<p:ph>` placeholders, including `sldNum`, `dt`, and
  `ftr`, because rendered PNGs can hide them. Unfilled placeholders appear in
  clone/edit mappings, deviation logs, job status, and the review cockpit.
- **Responsive UX and browser coverage:** frontend types cover the new status
  and outline payloads; route-mocked Playwright coverage exercises the
  optional plan preview flow, review cockpit, setup asset display, and
  mobile/tablet overflow checks.

Current caveat: this is not yet a complete artifact-tool clone/edit engine.
The current brand path uses conservative OOXML/source-slide duplication and
blocks weak mappings with evidence. Exact source-deck following still needs
deeper artifact-tool parity, stronger edit-target planning from source layout
inspection, and more full-deck real-template acceptance runs.

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

1. **Polished HTML rendering rollout (current focus)**
   - Land the QA interplay so image-slide decks are scored correctly, then flip
     `RENDERER_ENGINE` default to `html` for freeform/brand.
   - Run a live `qwen3.6-35b-a3b-mtp` end-to-end smoke through the HTML engine
     against `metis.local:1240` and visually accept the contact sheets.
   - Improve storytelling to match the rendering: outline-first planning,
     sharper action titles, no meta-layout language leaking into content.
     (Layout variety / fewer plain card-grid fallbacks landed via the "Slide
     variety & multi-style generation" pass — five new HTML primitives +
     family-complete, history-aware selection.)
   - Bundle Newsreader/Hanken Grotesk web fonts for typographic fidelity.
     (Selectable design languages now cover palette/visual variety; bundled
     web fonts are still outstanding.)

2. **Docs alignment**
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

5. **Claude/template-following fidelity**
   - Move brand clone/edit closer to the Claude template-following reference by
     using source-deck layout inspection and validated element IDs to build
     stronger edit target maps before rendering.
   - Produce human-readable `template-audit.txt`, `deviation-log.txt`, and
     source notes alongside the current JSON artifacts.
   - Deepen exact source-deck fidelity checks against the generated
     `template-frame-map.json`, including starter/final layout comparisons and
     required logo/chrome visibility.

6. **Office and brand fidelity**
   - Add manual Microsoft Office compatibility checks for generated PPTX files.
   - Deepen brand-template fidelity analysis beyond the current colors, fonts,
     logo reuse, layout-profile cues, and conservative clone/edit path.
   - Broaden strict schema extraction for additional charts, status indicators,
     and other complex PowerPoint objects.

## Verification Evidence

- Backend tests: `cd backend && python -m pytest tests/ -q` passed
  (`234 passed`) on 2026-06-23.
- Backend lint: `cd backend && ruff check app/ tests/` passed on 2026-06-23.
- Focused backend regression checks for the 2026-06-25 cockpit/authored
  renderer/template-following work passed, including:
  - plan-only orchestration and render-from-plan tests in
    `tests/test_orchestrator_modes.py`;
  - `review_failed` final QA/editing-contract tests in
    `tests/test_orchestrator_modes.py`;
  - authored renderer and editing-contract tests in
    `tests/test_generation_editing_contract.py`;
  - brand clone/edit, frame-map, deviation-log, media cleanup, chart/table
    rewrite, and unfilled-placeholder regressions in
    `tests/test_brand_template_support.py`;
  - job-status cockpit summaries in `tests/test_jobs_api_modes.py`.
- Focused backend lint for touched files passed on 2026-06-25, including
  `app/services/brand_template_renderer.py`,
  `app/services/generation_editing_contract.py`,
  `app/services/template_analyzer.py`, `app/routes/jobs.py`, and related
  tests.
- Backend coverage after refactor:
  - App total: `78%`.
  - `ContentPlanner` facade: `92%`; extracted planning modules range from
    `71%` to `96%`.
  - `DeterministicPptxRenderer` facade: `97%`; extracted rendering modules
    range from `65%` to `95%`.
  - `VisualQAAgent` facade: `92%`; extracted VisualQA modules range from `81%`
    to `92%`.
- Frontend typecheck (`npx tsc --noEmit`) passed for the cockpit/status payload
  updates on 2026-06-25. Frontend typecheck and production build
  (`npm run build`) passed for the wizard UI baseline on 2026-06-19.
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
