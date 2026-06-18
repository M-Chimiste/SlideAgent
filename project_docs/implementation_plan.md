# SlideAgent Three-Mode Implementation Plan

**Date:** 2026-06-17  
**Status:** Historical vertical-slice plan; see current status notes below

---

## 1. Objective

Bring the codebase in line with the updated product docs:

- Support three generation modes: `freeform`, `brand`, and `strict`.
- Use `project_docs/style_guide.md` as the operational quality rubric.
- Add an OpenAI-compatible local model path for LM Studio / Metis.
- Make generation produce structured slide specs before rendering.
- Verify all modes with automated tests and generated PPTX artifacts.

The immediate implementation target is a reliable vertical slice, not every
future advanced feature from the architecture doc.

## Current Status Note - 2026-06-18

This plan documents the original three-mode vertical-slice work. The current
codebase has implemented and tested the freeform, brand, and strict local
vertical slices described here, including deterministic generated-slide
rendering, strict XML injection, QA repair loops, and all-mode smoke tooling.

The subsequent backend cleanup split the main service hotspots into smaller
packages while preserving public facades:

- `ContentPlanner` delegates to `app.services.planning`.
- `DeterministicPptxRenderer` delegates to `app.services.pptx_rendering`.
- `VisualQAAgent` delegates to `app.services.visual_qa`.

Use [project_status.md](./project_status.md) for current capability and
verification evidence. Use [architecture.md](./architecture.md) for target and
actual module boundaries.

---

## 2. Implementation Phases

### Phase 1: Core Contracts and Local LLM Support

- Add canonical generation modes: `freeform | brand | strict`.
- Add slide-spec models with action titles, subheadings, content blocks, chart
  specs, sources, speaker notes, and QA metadata.
- Add an OpenAI-compatible client configured by:
  - `LLM_PROVIDER=openai_compatible|bedrock|none`
  - `OPENAI_COMPATIBLE_BASE_URL=http://metis.local:1240/v1`
  - `OPENAI_COMPATIBLE_MODEL=qwen3.6-35b-a3b-mtp`
  - `OPENAI_COMPATIBLE_REASONING_EFFORT=none`
  - `OPENAI_COMPATIBLE_TIMEOUT_SECONDS=120`
- Add separate planner and vision profiles:
  - `planner_profile=fast|deep` on jobs
  - `DEEP_PLANNER_BASE_URL=http://athena.local:1240/v1`
  - `DEEP_PLANNER_MODEL=minimax-m2.7`
  - `VISION_BASE_URL=http://metis.local:1240/v1`
  - `VISION_MODEL=qwen3.6-35b-a3b-mtp`
- Keep deterministic fallback generation available when no model endpoint is
  reachable.

### Phase 2: Consulting-Aware Planning

- Replace the heuristic `ContentPlanner` path with a `NarrativePlanner` style
  service that creates consulting slide specs.
- Enforce style-guide rules in code:
  - action title required
  - title must not be a generic topic label
  - one message per slide
  - source or inline `[source needed]` for numeric claims, with source-backed
    numeric tokens passed into the planner prompt
  - layout variety metadata
- Use the local LLM client when configured; validate and repair/fallback when
  the model returns malformed JSON.

### Phase 3: Deterministic Rendering

- Add a Python deterministic PPTX renderer for generated slides so freeform and
  brand mode do not depend on missing Node packages.
- Keep brand mode brand-aware by using extracted fonts/colors from the uploaded
  PPTX profile.
- Add a strict XML injection path for strict fields that avoids broad
  `python-pptx` rewriting of strict slides.
- Preserve existing hybrid assembly behavior for mixed strict/flexible decks,
  but prefer deterministic generated-slide rendering over LLM-generated code.

### Phase 4: API and Orchestration

- Update job creation to accept `generation_mode`.
- Allow `freeform` jobs without a template.
- Keep `brand` and `strict` jobs template-backed.
- Store generated slide specs/outlines and warnings in SQLite.
- Run consulting QA before rendering and visual QA after rendering.

### Phase 5: Tests and Verification

- Unit-test local LLM client JSON parsing with fake responses.
- Unit-test consulting QA and planner fallback behavior.
- Unit-test renderer output is a valid PPTX.
- Add API/orchestrator tests for:
  - freeform job
  - brand-template job
  - strict-template job with `[INSERT CONTENT HERE]`
- Add brand-template tests for flat brand-field compatibility, uploaded PPTX
  logo extraction, and generated-slide logo rendering.
- Add source-grounding tests so unsupported numeric claims receive
  `[source needed]` while source-supported numbers do not.
- Add strict placeholder tests for unmapped required fields.
- Add strict table-cell tests for analyzer extraction and XML-level injection.
- Add strict chart-cache tests for analyzer extraction and XML-level injection.
- Synchronize strict chart-cache updates into embedded chart workbooks to avoid
  stale data when Office refreshes a chart.
- Add Office-compatibility tests for dangling package relationships and missing
  content-type declarations.
- Add deterministic generated-slide repair for reliable QA issues, including
  warning-level text-density/layout findings, outline persistence, QA round
  logs, and loop guards for unchanged actionable issue signatures.
- Add a repeatable all-mode local-Qwen smoke runner that generates freeform,
  brand, and strict PPTX artifacts from `data/Beyond Vibe Coding.docx` and
  writes a machine-readable QA report with QA round history.
- Run backend tests and, when dependencies are installed, frontend build.

---

## 3. Acceptance Criteria

- `project_docs/` contains PRD, architecture, status, style guide, and this
  implementation plan.
- Backend tests cover all three modes.
- A freeform deck can be generated without uploading a PPTX template.
- A brand deck can be generated using an uploaded/template-derived brand profile.
- A strict deck can update rigid fields and emit placeholder warnings for
  unmapped content.
- Jobs can select `planner_profile=fast|deep`; deep planning uses the configured
  premium local planner while VisualQA uses the configured vision model.
- The code can use `metis.local:1240` through OpenAI-compatible endpoints when
  the server is available.
- The smoke runner can compare local OpenAI-compatible models by overriding
  base URL, model, timeout, vision model, and report label.
- If the local model is unavailable, tests still pass through deterministic
  fallbacks/fakes.

---

## 4. Local Model Verification

`http://metis.local:1240/v1/models` and `http://athena.local:1240/v1/models`
are reachable when network access is approved for the local host.

Verified local models:

- `qwen3.6-35b-a3b-mtp`
- `minimax-m2.7`

Important request setting:

- `reasoning_effort: "none"` disables reasoning-token output for this LM Studio
  endpoint. `enable_reasoning: false` and `chat_template_kwargs.enable_thinking`
  did not disable reasoning in this environment.
- Local OpenAI-compatible calls use a separate 120-second timeout because deck
  planning can exceed the shorter Bedrock validation timeout.
- Direct endpoint check on 2026-06-17:
  - no reasoning flag: response spent all completion tokens in
    `reasoning_content`
  - `enable_reasoning: false`: same reasoning-token behavior
  - `reasoning_effort: "none"`: returned answer content with
    `reasoning_tokens: 0`
- Athena `minimax-m2.7` currently ignores `reasoning_effort: "none"`,
  `enable_reasoning: false`, and `chat_template_kwargs.enable_thinking: false`.
  It is usable with larger completion budgets, but should be treated as a
  slower premium planner until the serving stack exposes a no-reasoning mode.

Smoke artifacts:

- `${TMPDIR:-/tmp}/slideagent-beyond-vibe/freeform-beyond-vibe-qwen.pptx`
- Source document: `data/Beyond Vibe Coding.docx`
- Latest result: 7 Qwen-planned slides, varied layouts, valid PPTX parse, one
  reliable structural repair round, and VisualQA passed with no critical
  issues.

Additional smoke artifacts:

- `${TMPDIR:-/tmp}/slideagent-beyond-vibe/brand-beyond-vibe-qwen.pptx`
  - Latest result: 6 Qwen-planned slides, varied layouts, valid PPTX parse, and
    VisualQA passed with no critical issues.
- `${TMPDIR:-/tmp}/slideagent-beyond-vibe/strict-beyond-vibe.pptx`
  - Latest result: 1 strict template slide updated through XML injection,
    valid PPTX parse, and VisualQA passed with no critical issues.

Repeatable smoke command:

- `python -m app.tools.all_mode_smoke --vision` from `backend/`
- Report path:
  `${TMPDIR:-/tmp}/slideagent-beyond-vibe/all-mode-<label>-smoke-report.json`
- Report includes per-mode `qa_rounds` and `qa_history`.
- Model comparison flags:
  `--base-url`, `--model`, `--timeout-seconds`, `--vision-base-url`,
  `--vision-model`, `--vision-timeout-seconds`, and `--label`.
- Minimax structural comparison command:
  `python -m app.tools.all_mode_smoke --base-url http://athena.local:1240/v1 --model minimax-m2.7 --label minimax-m27`

Vision smoke:

- A generated JPEG slide image was sent through the OpenAI-compatible image
  message format and Qwen returned `{"issues": []}`.

Render-tool status:

- `soffice` and `pdftoppm` are installed locally via Homebrew:
  - LibreOffice 26.2.4.2
  - Poppler 26.06.0
- VisualQA now sends exact rendered slide images to the local
  OpenAI-compatible vision endpoint when render tools are available.
- If exact render tools are unavailable or fail, VisualQA degrades to a warning,
  generates approximate PPTX preview images, runs PPTX-structure checks, and
  excludes approximate-preview vision findings from automatic repair because
  they are not exact rendered evidence.
