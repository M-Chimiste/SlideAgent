# SlideAgent / SlideForge Product Requirements

**Version:** 0.4
**Date:** 2026-06-17
**Status:** Target product direction for the rebuild

---

## 1. Problem Statement

Creating executive-ready PowerPoint decks is still slow, fragile, and quality
inconsistent. Existing AI slide tools often produce generic topic slides, weak
storylines, repetitive layouts, and files that need substantial manual repair
before they are usable in Microsoft Office.

SlideAgent should solve three distinct presentation workflows:

1. **Freeform generation:** The user starts with a prompt and optional source
   documents. The system creates a complete deck without requiring a PPTX
   template.
2. **Brand/master-template generation:** The user provides a PPTX as a brand
   reference. The system extracts visual identity and generates new content and
   slides that feel native to that brand.
3. **Strict-template generation:** The user provides a rigid PPTX where
   existing slide structure must be preserved. The system updates designated
   fields from the prompt/source documents while keeping layout, shape geometry,
   and formatting intact.

The product must generate decks that are useful as standalone business
documents, not just decorative speaker aids.

---

## 2. Product Vision

SlideAgent is a local web application for generating consulting-quality
PowerPoint decks from prompts, documents, and optional templates. It combines
language-model planning with deterministic PPTX rendering and mandatory QA.

The product quality standard is defined by
[style_guide.md](./style_guide.md). That guide is not background reading; it is
the executable rubric for planning, generation, and QA.

**Non-negotiable quality principles:**

- **Structure before design:** Build a ghost deck/storyline before rendering
  any slide.
- **Action titles:** Every content slide title states a conclusion, not a
  topic label.
- **One message per slide:** Each slide has one clear claim and one primary
  exhibit or evidence block.
- **Source discipline:** Quantitative claims must trace to provided source
  documents or be marked `[source needed]`.
- **PPTX reliability:** Rendering and XML mutation are owned by deterministic
  services, not by free-form LLM output.
- **Mandatory QA:** Every deck passes consulting QA and visual/render QA before
  delivery.

---

## 3. Generation Modes

### 3.1 Freeform Generation

Freeform mode requires no PPTX template. The user provides:

- A topic or brief
- Audience and goal, when available
- Optional source documents
- Optional style preferences

The system produces a complete deck by:

1. Ingesting source material.
2. Building a ghost deck using SCR, Pyramid Principle, and MECE structure.
3. Validating the horizontal flow of action titles.
4. Generating structured slide content and design specs.
5. Rendering a PPTX from deterministic layouts.
6. Running consulting QA and visual QA with repair loops.

Freeform mode is the first vertical slice for the rebuild because it exercises
the core narrative, content, rendering, and QA pipeline without template
complexity.

### 3.2 Brand / Master-Template Generation

Brand mode uses a PPTX as a visual reference, not as a rigid content container.
The template provides brand DNA:

- Theme colors
- Fonts
- Slide masters and layouts
- Logo assets and placement rules
- Example composition patterns
- Chart and table styling cues

The system generates new slides and new content while respecting the extracted
brand identity. Template text is illustrative and should not constrain the
generated storyline unless the user explicitly asks for it.

Brand mode should preserve the feel of the uploaded deck while still enforcing
the consulting-quality rules from [style_guide.md](./style_guide.md).

### 3.3 Strict-Template Generation

Strict mode treats the uploaded PPTX as the artifact of record. Existing
slides, shapes, and field positions are preserved. The system updates content
only in designated fields and keeps the structure rigid.

Strict mode supports:

- Fixed title slides
- Status dashboards
- KPI scorecards
- RAG status grids
- Governance and approval decks
- Mixed decks with strict slides and flexible generated slides

Strict injection must use XML-level editing to preserve formatting. The runtime
pipeline must not rely on broad `python-pptx` write operations for strict
slides, because those can rewrite XML and alter formatting.

When a required strict field cannot be mapped from the prompt or source
documents, the system inserts `[INSERT CONTENT HERE]` and surfaces a warning.
This placeholder is intentional and should not fail visual QA.

---

## 4. Consulting-Quality Standard

The detailed standard lives in [style_guide.md](./style_guide.md). The product
must operationalize that guide through prompts, schemas, validators, and QA
checks.

### 4.1 Narrative Requirements

- Use SCR for the macro story: Situation, Complication, Resolution.
- Use Pyramid Principle for argument structure.
- Group supporting arguments with MECE logic.
- Build a ghost deck before generating full slide content.
- Validate horizontal flow: slide titles alone must tell the complete story.

### 4.2 Slide Requirements

Each generated slide should have:

- One action title, ideally 15 words or fewer.
- One subheading that explains the evidence or data context.
- One primary exhibit or structured evidence block.
- A source line for any data-backed claim.
- No irrelevant content that fails the "so what" test.

### 4.3 Visual Requirements

- Use fixed title/header/footer zones.
- Use consistent margins and title position across slides.
- Use restrained color palettes and accent color only for emphasis.
- Use whitespace instead of decorative clutter.
- Split slides instead of shrinking fonts to fit content.
- Avoid text walls, 3D charts, generic stock decoration, and excessive bullets.

---

## 5. Target System Architecture

See [architecture.md](./architecture.md) for implementation detail. At a
product level, every mode follows the same core pipeline:

```text
Prompt + docs + optional template
  -> Document ingestion
  -> Narrative planning / ghost deck
  -> Consulting QA gate
  -> Slide content specs
  -> Slide design specs
  -> Deterministic PPTX rendering / XML injection
  -> Visual QA gate
  -> Repair loop
  -> Downloadable PPTX + previews + warnings
```

LLMs generate structured JSON/specs only. They do not write PPTX files, mutate
XML, or directly position arbitrary visual elements. Renderer services own file
I/O, PPTX construction, XML manipulation, validation, and repackaging.

---

## 6. Target Interfaces

### 6.1 Generation Mode

```text
generation_mode = freeform | brand | strict
```

### 6.2 Planner Profile

```text
planner_profile = fast | deep
```

- `fast` uses the default local OpenAI-compatible planner, currently Qwen on
  Metis, for rapid iteration.
- `deep` uses the premium local planner profile, currently Minimax on Athena,
  for higher-quality narrative planning at higher latency.
- Visual QA can use a separate vision-capable model from the planner.

### 6.3 Slide Spec

The target slide spec should be structured and validated before rendering:

```json
{
  "slide_number": 1,
  "slide_type": "title|executive_summary|content|chart|comparison|matrix|waterfall|process|gantt|framework|appendix",
  "action_title": "Complete sentence stating the conclusion",
  "subheading": "Data description, units, segment, or time period",
  "content_blocks": [
    {
      "type": "bullets|chart|table|callout|framework|text",
      "body": [],
      "annotations": [],
      "callouts": []
    }
  ],
  "chart_spec": null,
  "sources": ["Source document or [source needed]"],
  "speaker_notes": "Optional presenter notes",
  "qa": {
    "consulting_status": "pending|pass|warning|fail",
    "visual_status": "pending|pass|warning|fail",
    "issues": []
  }
}
```

### 6.4 Template Profile

Brand and strict templates should produce a reusable profile:

- Template type: `brand` or `strict`
- Brand DNA: colors, fonts, logos, layout patterns
- Slide inventory and thumbnails
- Strict field schema, when applicable
- Flexible slide guidance, when applicable
- User overrides for classification and field mappings

### 6.5 QA Gates

**Consulting QA** checks structured specs before rendering:

- Action titles are conclusions, not topic labels.
- Titles form a coherent horizontal flow.
- Deck follows SCR/Pyramid structure.
- Breakdowns are plausibly MECE.
- Each slide has one message.
- Claims are supported by sources or marked `[source needed]`.

**Visual QA** checks rendered output:

- PPTX renders to preview images.
- No obvious overlap, cut-off text, or illegible contrast.
- No text walls on generated slides.
- Layouts are varied and professionally spaced.
- Office compatibility warnings are surfaced.
- Strict placeholders are allowed but highlighted.

---

## 7. Web Application Flow

### 7.1 Create or Select Generation Mode

The user chooses:

- Freeform
- Brand/master template
- Strict template

The user also chooses planning depth:

- Fast
- Deep

Freeform requires only a brief and optional source documents. Brand and strict
modes require template setup before generation.

### 7.2 Template Setup

For brand templates:

- Upload PPTX.
- Extract brand DNA.
- Render thumbnails.
- Summarize usable layout patterns.
- Allow user to edit brand notes.

For strict templates:

- Upload PPTX.
- Render thumbnails.
- Classify slides as strict or flexible.
- Extract strict field schemas.
- Allow user review and override of classifications and field mappings.

### 7.3 Generate Deck

The user supplies source documents and optional instructions. The system runs
the job asynchronously and reports status through planning, generation, QA,
repair, and completion.

### 7.4 Review and Download

The user can:

- Review rendered slide previews.
- See warnings and `[INSERT CONTENT HERE]` placeholders.
- Download PPTX and optionally PDF.
- Regenerate or repair individual generated slides when supported.

---

## 8. Success Metrics

| Metric | Target |
| --- | --- |
| Freeform vertical slice | 5-slide deck from brief renders successfully |
| Action title pass rate | > 90% after consulting QA |
| Text wall rate | < 5% of generated slides after QA |
| Strict field preservation | Existing shape geometry and formatting preserved |
| Source coverage | All numeric claims cite source or show `[source needed]` |
| Office compatibility | Generated PPTX opens cleanly in Microsoft Office |
| QA rounds | <= 2 average repair rounds for common decks |

---

## 9. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| LLM output is generic | Require audience, goal, action-title planning, and source-grounded specs |
| Slides are repetitive | Validate layout variety and use archetype selection from the style guide |
| LLM invents data | Require source tracking and `[source needed]` placeholders |
| Strict XML editing corrupts PPTX | Use XML-level targeted edits, validate ZIP/XML, render previews |
| LibreOffice differs from PowerPoint | Treat render QA as necessary but not sufficient; surface Office compatibility warnings |
| Template analysis is wrong | Provide user review and override for strict/flexible classification and schema |

---

## 10. Roadmap

### Phase 1: Documentation and Architecture Alignment

- Align PRD, architecture, and project status around the three-mode model.
- Treat [style_guide.md](./style_guide.md) as the generation and QA rubric.
- Mark current scaffold limitations clearly.

### Phase 2: Freeform Vertical Slice

- Implement document ingestion and narrative planning.
- Generate ghost decks with action titles.
- Render a deterministic 5-slide PPTX.
- Add consulting QA and basic visual QA.

### Phase 3: Brand Template Support

- Extract brand DNA from PPTX files.
- Render generated slides using brand-aware design specs.
- Validate layout variety and brand consistency.

### Phase 4: Strict Template Hardening

- Replace high-level strict writes with XML-level field injection.
- Improve strict schema extraction and user overrides.
- Add shape/table/chart placeholder support.

### Phase 5: QA and Repair Loop

- Add targeted repair prompts for consulting QA failures.
- Add rendered slide repair for visual issues.
- Improve Office compatibility validation and warning surfacing.
