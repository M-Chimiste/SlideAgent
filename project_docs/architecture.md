# SlideAgent / SlideForge Target Architecture

**Date:** 2026-06-17
**Status:** Implementation-ready architecture direction for the rebuild

---

## 1. Core Architecture Principles

1. **Structure before rendering:** Build and validate a ghost deck before
   generating full slide content or PPTX files.
2. **LLMs produce structured specs only:** Language models return validated
   JSON objects. They do not write files, mutate XML, or directly assemble PPTX
   packages.
3. **Deterministic services own PPTX work:** Rendering, XML injection, ZIP
   repackaging, and file validation are pure service responsibilities.
4. **The style guide is executable:** [style_guide.md](./style_guide.md)
   defines prompts, schema constraints, consulting QA checks, and visual QA
   expectations.
5. **Every deck passes two QA gates:** Consulting QA validates the argument;
   visual QA validates the rendered artifact.

---

## 2. Target Pipeline

```text
User brief + documents + optional template
  -> DocumentIngester
  -> TemplateAnalyzer (brand/strict only)
  -> NarrativePlanner
  -> ConsultingQA gate
  -> ContentGenerator
  -> DesignSpecGenerator
  -> Renderer / StrictXMLInjector / HybridAssembler
  -> VisualQA gate
  -> Repair loop
  -> PPTX + previews + warnings
```

### Pipeline contract

- `DocumentIngester` extracts structured source material and provenance.
- `NarrativePlanner` creates the ghost deck and action-title storyline.
- `ConsultingQA` validates the storyline before slide rendering.
- `ContentGenerator` fills evidence under approved action titles.
- `DesignSpecGenerator` selects slide archetypes and layout instructions.
- `Renderer` creates new generated slides from specs.
- `StrictXMLInjector` updates strict template fields through targeted XML edits.
- `VisualQA` renders the deck to images and checks visual/compatibility issues.
- Repair loops modify structured specs, not arbitrary PPTX output.

---

## 3. Mode-Specific Flows

### 3.1 Freeform Generation

```text
Brief + optional docs
  -> DocumentIngester
  -> NarrativePlanner (SCR/Pyramid ghost deck)
  -> ConsultingQA
  -> ContentGenerator
  -> DesignSpecGenerator
  -> FreeformRenderer
  -> VisualQA
  -> PPTX
```

Freeform mode uses built-in layout archetypes. It is the first target vertical
slice because it validates the core narrative/content/render/QA system without
template analysis complexity.

### 3.2 Brand / Master-Template Generation

```text
Brand PPTX + brief + docs
  -> TemplateAnalyzer extracts brand DNA
  -> DocumentIngester
  -> NarrativePlanner
  -> ConsultingQA
  -> ContentGenerator
  -> BrandAwareDesignSpecGenerator
  -> BrandRenderer
  -> VisualQA
  -> PPTX
```

Brand mode uses the uploaded PPTX as a visual reference. Existing template
content is illustrative. Generated slides are new and should follow brand DNA:
colors, fonts, logo rules, master/layout patterns, and chart/table styling.

### 3.3 Strict-Template Generation

```text
Strict PPTX + brief + docs
  -> TemplateAnalyzer extracts slide classifications and field schema
  -> User reviews strict/flexible classifications
  -> DocumentIngester
  -> NarrativePlanner maps content to strict fields and flexible slides
  -> ConsultingQA
  -> StrictXMLInjector updates strict fields
  -> Renderer creates flexible/generated slides when needed
  -> HybridAssembler combines strict + generated slides
  -> VisualQA
  -> PPTX
```

Strict mode preserves the uploaded PPTX structure. Existing strict slide
geometry, shape positions, and formatting must survive generation. Required
fields without source content receive `[INSERT CONTENT HERE]` and generate
warnings.

---

## 4. Service Responsibilities

### DocumentIngester

- Converts uploaded files to text/markdown and structured records.
- Extracts sections, tables, metrics, dates, entities, and source provenance.
- Marks claims and metrics with source identifiers.
- Does not summarize into slide content directly.

### TemplateAnalyzer

- For brand templates, extracts brand DNA and slide-layout fingerprints.
- For strict templates, renders thumbnails, classifies strict vs flexible
  slides, and extracts field schemas.
- Produces user-reviewable template profiles.
- Uses vision/LLM analysis as assistance, not as the only source of truth.

### NarrativePlanner

- Creates a ghost deck before rendering.
- Uses SCR, Pyramid Principle, MECE grouping, and horizontal flow.
- Produces action titles, slide intents, evidence needs, and source needs.
- Chooses whether each slide is strict, brand-generated, or freeform-generated.

### ConsultingQA

- Runs before rendering.
- Checks action-title quality, horizontal flow, SCR/Pyramid structure, MECE
  coverage, one-message-per-slide, and source coverage.
- Returns structured issues and repair instructions.
- Blocks rendering on critical storyline failures.

### ContentGenerator

- Generates slide-level evidence under approved action titles.
- Keeps quantitative claims source-grounded.
- Uses `[source needed]` where provided material does not support a claim.
- Produces concise content blocks, not positioned shapes.

### DesignSpecGenerator

- Chooses consulting slide archetypes from the style guide.
- Produces structured design specs: layout archetype, chart/table/callout
  choices, emphasis color, annotations, and source/footer needs.
- Enforces one primary exhibit per slide and layout variety across the deck.

### Renderer

- Converts slide specs into PPTX slides.
- Owns positioning, sizing, fonts, colors, charts, icons, tables, and footer
  rendering.
- Uses deterministic layout rules and validates generated slide dimensions.
- Never accepts arbitrary executable slide code from an LLM as the source of
  truth.

### StrictXMLInjector

- Unpacks PPTX files and edits specific XML targets.
- Preserves run/paragraph/shape formatting wherever possible.
- Updates text, fills, status indicators, and supported table/chart fields.
- Validates XML and ZIP integrity before returning an output PPTX.

### HybridAssembler

- Combines strict template slides and generated flexible slides.
- Preserves relationships, media, charts, masters, layouts, and content types.
- Validates the final package before VisualQA.

### VisualQA

- Renders PPTX to PDF/images.
- Checks overlap, overflow, low contrast, text walls, layout repetition, missing
  previews, and obvious compatibility warnings.
- Allows `[INSERT CONTENT HERE]` on strict slides but highlights it in the UI.
- Produces targeted repair instructions for generated slides.

---

## 5. Target Data Contracts

### Generation mode

```text
freeform | brand | strict
```

### Planner profile

```text
fast | deep
```

- `fast`: default low-latency planner profile for iteration.
- `deep`: higher-latency planner profile for stronger narrative/content
  planning.
- Visual QA should be configured separately from planner selection so a
  vision-capable model can inspect rendered slides even when the planner model
  is text-only or slow.

### Deck plan

```json
{
  "deck_title": "string",
  "audience": "string",
  "goal": "string",
  "narrative_arc": "situation|complication|resolution summary",
  "slides": []
}
```

### Slide spec

```json
{
  "slide_number": 1,
  "slide_type": "executive_summary|content|chart|comparison|matrix|waterfall|process|gantt|framework|appendix",
  "action_title": "Complete sentence stating the conclusion",
  "subheading": "Evidence context, units, period, or segment",
  "content_blocks": [
    {
      "type": "bullets|chart|table|callout|framework|text",
      "body": [],
      "annotations": [],
      "callouts": []
    }
  ],
  "chart_spec": null,
  "sources": ["source-id or [source needed]"],
  "speaker_notes": "string",
  "qa": {
    "consulting_status": "pending",
    "visual_status": "pending",
    "issues": []
  }
}
```

### Strict field mapping

```json
{
  "slide_index": 0,
  "field_id": "overall_rag",
  "location": "shape:StatusIndicator or xpath",
  "type": "text|number|date|enum|text_list|status_color|chart_data|table_data",
  "required": true,
  "constraints": {},
  "value": "[INSERT CONTENT HERE]"
}
```

---

## 6. QA Gates and Repair

### Consulting QA gate

Runs on deck plans and slide specs before rendering. Critical failures include:

- Topic-label titles instead of action titles.
- No coherent horizontal flow.
- Multiple messages on one slide.
- Unsupported quantitative claims.
- Missing Resolution weight in the deck narrative.
- Non-MECE breakdowns where structure is central to the slide.

Repairs should update the deck plan or slide specs, then re-run ConsultingQA.

### Visual QA gate

Runs after rendering. Critical failures include:

- PPTX cannot render.
- Text overlaps, clips, or becomes illegible.
- Generated slide is a text wall.
- Primary exhibit does not support the action title.
- Layout repetition makes adjacent generated slides visually redundant.

Repairs should update generated slide specs or renderer parameters. Strict
template slides should only be changed through approved strict field mappings.

---

## 7. Implementation Milestones

### Milestone 1: Freeform vertical slice

- Generate a 5-slide deck from a short brief.
- Produce action-title ghost deck and pass ConsultingQA.
- Render deterministic PPTX and preview images.
- Run VisualQA and surface warnings.

### Milestone 2: Source-grounded content

- Ingest documents with provenance.
- Require source references or `[source needed]` for quantitative claims.
- Add consulting QA checks for unsupported metrics.

### Milestone 3: Brand templates

- Extract theme colors, fonts, logo, and layout patterns.
- Render generated slides using brand-aware specs.
- Validate brand consistency in VisualQA.

### Milestone 4: Strict templates

- Extract strict schemas and flexible slide intents.
- Implement XML-level strict field injection.
- Preserve formatting and validate package integrity.

### Milestone 5: Hybrid assembly and repair

- Combine strict and generated slides safely.
- Add targeted repair loops for ConsultingQA and VisualQA.
- Improve per-slide regeneration and warning review.
