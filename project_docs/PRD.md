# SlideForge — AI Presentation Generation Agent

## Product Requirements Document

**Codename:** SlideForge  
**Version:** 0.3 — Final Draft  
**Date:** 2026-02-20

---

## 1. Problem Statement

Creating polished, consultant-grade presentations is one of the most time-consuming knowledge-work tasks. Two recurring patterns emerge:

1. **Brand-templated decks** — You have branded master templates with color palettes, fonts, and slide masters, but building a compelling deck from source documents still takes hours. The results are often text-heavy walls of bullets that nobody wants to read.

2. **Structured reporting decks** — Standardized slide formats (project status dashboards, investment requests, governance reviews) have rigid layouts where specific data points must be placed in exact positions, while other slides in the same deck are flexible and need creative content generation.

No existing tool handles both modes well.

---

## 2. Vision

A local Docker-based web application where you upload a template (brand or structured), upload source documents, and receive a polished McKinsey-quality presentation — complete with visual hierarchy, data callouts, icons, and vibrant design — in minutes rather than hours.

**Non-negotiable quality principles:**
- **Zero text walls.** Every slide has visual elements. A slide with just title + bullets is a failure.
- **Visual elements on every deck.** Icons, charts, shapes, data callouts — the deck must feel designed, not typed.
- **Visual QA is mandatory.** Every generated deck is rendered to images and inspected by an AI agent before delivery. Broken layouts, overlaps, and ugly slides get caught and fixed automatically.

---

## 3. Core Concepts

### 3.1 Template Types

**Brand Template** — A reference PPTX that provides visual identity: color palette, fonts, slide masters/layouts, logo placement, and design language. The template's content is illustrative. SlideForge extracts the *style DNA* and generates entirely new slides conforming to it.

**Strict Template** — A PPTX where specific slides have fixed structure that must be preserved. The system analyzes each slide and classifies it as either:

- **Strict Slide** — Layout, shapes, and data positions are fixed. Content is injected into designated placeholders. Examples: title slide, project status dashboard, KPI scorecards, RAG status grids.
- **Flexible Slide** — The slide contains guidance about *what kind* of content belongs there (e.g., "Project Requirements" or "Key Risks") but the structure is not dictated. SlideForge generates the layout and content freely using the template's brand DNA.

A single deck template might have slides 1-2 as strict (title + dashboard), slides 3-8 as flexible (narrative sections), and slide 9 as strict (approval/sign-off).

### 3.2 Source Documents

Any office document format serves as content input, all parsed via MarkItDown:

| Format | Notes |
|--------|-------|
| `.docx`, `.doc` | Structure, tables, embedded images |
| `.pptx`, `.ppt` | Existing slide content as markdown |
| `.xlsx`, `.csv`, `.tsv` | Tabular data; numeric data identified for charts/callouts |
| `.pdf` | Text and basic structure extraction |
| `.txt`, `.md` | Direct ingestion |

Multiple documents can be uploaded simultaneously. The system fuses content intelligently.

### 3.3 The McKinsey Standard

Every generated deck must satisfy these principles. The Visual QA agent enforces them.

1. **No text walls** — Every flexible slide has a visual element: chart, icon, shape, or data callout. Title + bullets alone is a **failure state** that QA must catch and force a redesign.
2. **Visual hierarchy** — Clear title → subtitle → body progression with strong size contrast (36pt+ titles, 14-16pt body).
3. **Data-forward** — Numbers are large callouts (60-72pt), not buried in sentences.
4. **Layout variety** — No two consecutive slides use the same layout pattern.
5. **White space** — Generous margins (0.5" minimum) and breathing room.
6. **Icons and visual elements** — react-icons rendered as crisp PNGs, placed in colored circles, used as section markers, category indicators, and visual anchors throughout.
7. **Color discipline** — One dominant color (60-70%), supporting tones, one accent. Never equal weight.
8. **No accent lines under titles** — Hallmark of AI-generated slides. Use whitespace or background color instead.

---

## 4. System Architecture

### 4.1 High-Level Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│              SlideForge (Docker Container)                       │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  React Frontend (:3000 → proxied through :8080)           │  │
│  │  Upload Template │ Upload Docs │ Configure │ Generate      │  │
│  └────────┬─────────┴──────┬──────┴─────┬─────┴──────┬───────┘  │
│           │                │            │            │           │
│           ▼                ▼            ▼            ▼           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  FastAPI Backend (:8080)                                   │  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │  │
│  │  │ Template      │  │ Document     │  │ Orchestrator    │  │  │
│  │  │ Analyzer      │  │ Ingester     │  │                 │  │  │
│  │  │               │  │              │  │ • Plan          │  │  │
│  │  │ • Classify    │  │ • MarkItDown │  │ • Generate      │  │  │
│  │  │   strict/flex │  │ • Structure  │  │ • QA ← ──┐     │  │  │
│  │  │ • Schema      │  │ • Fuse docs  │  │ • Fix     │     │  │  │
│  │  │ • Brand DNA   │  │              │  │ • Re-QA ──┘     │  │  │
│  │  └──────────────┘  └──────────────┘  │ • Deliver       │  │  │
│  │                                       └─────────────────┘  │  │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │  Generation Engine                                   │  │  │
│  │  │                                                      │  │  │
│  │  │  Content     Design      PPTX Builder                │  │  │
│  │  │  Planner     Agent       (PptxGenJS for flex,        │  │  │
│  │  │              + Icons     XML edit for strict)         │  │  │
│  │  │                                                      │  │  │
│  │  │  Visual QA Agent                                     │  │  │
│  │  │  soffice → PDF → pdftoppm → LLM inspect → fix loop  │  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  │                                                            │  │
│  │  SQLite DB │ Local File Storage (./data volume)            │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Details

#### Template Analyzer

**Purpose:** Ingest a PPTX template and produce a reusable Template Profile stored in SQLite.

**For Brand Templates:**
- Extract color palette (theme colors from `theme1.xml`)
- Extract font families (heading + body from theme)
- Catalog slide layouts with visual fingerprints
- Extract logo assets and placement rules
- Render each slide to image via `soffice → pdftoppm` for LLM visual analysis
- LLM classifies each layout by type: title, content, two-column, image+text, section divider, etc.

**For Strict Templates:**
- All of the above, plus:
- **Per-slide classification** — LLM vision analysis of each slide image alongside its XML/markdown content to label it `strict` or `flexible` with reasoning
- **Strict slide schema extraction** — For each strict slide, identify every placeholder with:
  - Semantic label (e.g., "project_name", "rag_status", "milestone_date")
  - Content type (text, number, date, status-color, chart-data)
  - Location in the XML (shape name or XPath)
  - Constraints (max characters, allowed enum values)
- **Flexible slide intent extraction** — Topic guidance and content category
- User can review and override all classifications in the UI

#### Document Ingester

**Purpose:** Convert uploaded docs to structured content using MarkItDown.

**Pipeline:**
1. MarkItDown converts all formats to markdown (handles docx, pptx, xlsx, csv, pdf, etc.)
2. LLM-driven structural analysis:
   - Heading hierarchy and section boundaries
   - Section summarization
   - Metadata extraction (title, author, date, key terms)
   - Table detection and structured extraction
   - Numeric data identification (KPIs, metrics, percentages)
3. Multi-document fusion when >1 doc uploaded:
   - Unified content inventory with provenance
   - Complementary vs. redundant content identification

**Output:** `DocumentBundle` stored in SQLite — sections, subsections, tables, metadata, content inventory.

#### Content Planner

**Purpose:** Given a TemplateProfile and DocumentBundle, produce a slide-by-slide outline.

**For Brand Templates:**
- Determine optimal slide count based on content volume
- Allocate content sections to slides
- Select layout type per slide (enforcing variety)
- Identify data callout opportunities, chart candidates, icon placements
- Ensure narrative flow

**For Strict Templates:**
- Map content to strict slide fields
- Plan flexible slides as above
- **For unmappable fields:** mark as `[INSERT CONTENT HERE]` — obvious, easy to find-and-replace in PowerPoint

**Output:** `SlideOutline` — each slide specifies: type (strict/flexible), content allocation, layout choice, visual element plan (which icons, charts, shapes).

#### Design Agent

**Purpose:** For flexible slides, produce polished visual designs.

- Select and vary layouts: two-column, icon+text rows, stat callouts, 2x2 grids, half-image+text, timeline/process flow
- **Reject text-only designs** — every flexible slide must include at least one of: icons, chart, data callout, or decorative shapes
- Choose icons from react-icons that match the content semantics
- Apply brand palette with dominance hierarchy
- Maintain spacing rules (0.3-0.5" between blocks, 0.5" margins)
- Track used layouts to avoid consecutive repeats

#### Icon Pipeline

Icons are the primary visual element for slide art. The pipeline:

```
LLM selects icon name     →  react-icons component lookup
(e.g., "FaChartLine")        (react-icons/fa, /md, /hi, /bi)
                                      │
                                      ▼
                              ReactDOMServer.renderToStaticMarkup()
                                      │
                                      ▼
                              sharp() rasterize SVG → PNG at 256px+
                                      │
                                      ▼
                              Base64 encode → PptxGenJS addImage()
                              (w: 0.4-0.6", placed in colored circles)
```

Available icon sets:
- `react-icons/fa` — Font Awesome (business, status, categories)
- `react-icons/md` — Material Design (clean, modern)
- `react-icons/hi` — Heroicons (outlined style)
- `react-icons/bi` — Bootstrap Icons (utility)

The Design Agent LLM prompt includes the icon set catalog so it can select semantically appropriate icons for each content section.

#### PPTX Builder

**Dual-mode construction using PptxGenJS + python-pptx:**

- **Flexible slides** → PptxGenJS (JavaScript). Full creative control over layout, shapes, charts, icons, text. The LLM generates the JavaScript code, which is executed by Node.js.

- **Strict slides** → python-pptx XML editing. Unpack template → locate placeholders in slide XML → inject content values → repack. Preserves exact positioning, shapes, and formatting.

- **Hybrid assembly:**
  1. Start from the template PPTX (preserving theme, masters, layouts)
  2. Update strict slides in-place via XML editing (python-pptx)
  3. Generate flexible slides via PptxGenJS as a separate PPTX
  4. Merge: extract flexible slide XML from PptxGenJS output, insert into template PPTX at correct positions
  5. Validate and repack

**PptxGenJS code generation rules** (enforced in the LLM prompt):
- No `#` prefix on hex colors (corrupts file)
- No 8-char hex colors (corrupts file) — use `opacity` property
- `bullet: true` not unicode `•` symbols
- `breakLine: true` between text array items
- Fresh option objects per call (no reuse — PptxGenJS mutates them)
- `RECTANGLE` not `ROUNDED_RECTANGLE` when using accent bars
- `charSpacing` not `letterSpacing` (silently ignored)
- `margin: 0` on text boxes that must align precisely with shapes

#### Visual QA Agent (Mandatory — Every Generation)

**Philosophy:** The first render is almost never correct. QA is a bug hunt, not a confirmation step.

**Pipeline:**

```
Step 1: Render slides to images
  soffice --headless --convert-to pdf output.pptx
  pdftoppm -jpeg -r 150 output.pdf slide
  → slide-01.jpg, slide-02.jpg, ...

Step 2: LLM visual inspection (each slide image sent to Claude Sonnet vision)

  LAYOUT ISSUES:
  • Overlapping elements (text through shapes, stacked elements)
  • Text overflow or cut off at box boundaries
  • Elements too close (< 0.3" gaps) or nearly touching
  • Uneven spacing (large gap in one area, cramped in another)
  • Insufficient margin from slide edges (< 0.5")
  • Columns or elements not aligned consistently
  • Text boxes too narrow causing excessive wrapping

  VISUAL QUALITY:
  • Low-contrast text (light gray on cream, etc.)
  • Low-contrast icons (dark on dark backgrounds)
  • TEXT WALL DETECTED — flexible slide has no visual elements besides text
  • Accent line under title (AI hallmark — reject)
  • Same layout as previous slide (monotonous)

  CONTENT:
  • Leftover placeholder text ("Lorem ipsum", "XXXX", "Click to add")
  • Missing content that should be present per the outline
  • [INSERT CONTENT HERE] placeholders are EXPECTED on strict slides
    with unmapped fields — do NOT flag these as errors

Step 3: Triage
  • CRITICAL: Overlaps, text overflow, missing content, text walls → must fix
  • WARNING: Alignment, spacing, contrast → fix if possible
  • INFO: Minor improvements → log, don't block delivery

Step 4: Fix and re-render affected slides
  Regenerate PptxGenJS code (flex) or adjust XML (strict)
  Re-render only affected slides:
    pdftoppm -jpeg -r 150 -f N -l N output.pdf slide-fixed

Step 5: Re-inspect fixed slides
  One fix often creates another. Re-inspect until clean pass on criticals.

Step 6: Content verification
  python -m markitdown output.pptx | grep -iE "lorem|ipsum|xxxx|click.to.add"
  (Note: [INSERT CONTENT HERE] is intentional and NOT flagged)

Step 7: Deliver with preview images
```

---

## 5. Deployment

### 5.1 Docker Compose

```yaml
version: "3.8"

services:
  slideforge:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ~/.aws:/root/.aws:ro          # AWS creds (read-only)
      - ./data:/app/data               # SQLite DB + generated files
    environment:
      - AWS_PROFILE=${AWS_PROFILE:-default}
      - AWS_DEFAULT_REGION=${AWS_REGION:-us-east-1}
    restart: unless-stopped
```

Single container. No Redis, no Celery — generation runs in-process with async. SQLite handles the modest concurrency of a single-user app. Files stored on a local Docker volume.

### 5.2 AWS Credentials

Inherits credentials from the host via mounted `~/.aws` directory and `AWS_PROFILE` environment variable. Boto3 default credential chain picks it up automatically.

```python
import boto3

session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"))
bedrock = session.client(
    "bedrock-runtime",
    region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
)
```

- **Local dev:** Uses your configured AWS profile (SSO, static creds, etc.)
- **No secrets in code, env files, or Docker images**
- Startup validates the boto3 session can reach Bedrock before accepting requests

### 5.3 Bedrock Models

```python
MODELS = {
    "primary": "us.anthropic.claude-sonnet-4-20250514",    # Most tasks
    "vision":  "us.anthropic.claude-sonnet-4-20250514",    # QA, template analysis
    "fast":    "us.anthropic.claude-haiku-4-5-20251001",   # Simple extraction
}
```

| Task | Model |
|------|-------|
| Template analysis & slide classification | Sonnet (vision) |
| Document structuring | Sonnet |
| Content planning & outlining | Sonnet |
| Slide content + PptxGenJS code generation | Sonnet |
| Visual QA inspection | Sonnet (vision) |
| Simple metadata extraction, captioning | Haiku |

### 5.4 Container Dependencies

```dockerfile
FROM python:3.12-slim

# System
RUN apt-get update && apt-get install -y \
    libreoffice-impress \
    poppler-utils \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Python
RUN pip install \
    fastapi uvicorn \
    boto3 \
    "markitdown[pptx]" \
    python-pptx \
    Pillow \
    defusedxml \
    aiosqlite

# Node (global)
RUN npm install -g \
    pptxgenjs \
    react-icons react react-dom \
    sharp
```

---

## 6. Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Frontend | React + TypeScript + Tailwind | Component-based, rapid iteration |
| Backend | Python FastAPI (async) | Integrates with boto3, python-pptx, MarkItDown |
| Database | SQLite (via aiosqlite) | Simple, zero-config, single-user appropriate |
| File Storage | Local filesystem (`./data` volume) | Templates, generated decks, preview images |
| LLM | AWS Bedrock (Anthropic Claude) | Credential inheritance via AWS profile |
| PPTX (flexible) | PptxGenJS (Node.js) | Full creative control, charts, icons, shapes |
| PPTX (strict) | python-pptx + XML editing | Preserve exact template structure |
| Document Parsing | MarkItDown | Handles all office formats → markdown |
| Icons | react-icons + sharp | SVG → PNG rasterization for PPTX embedding |
| Rendering | LibreOffice + Poppler | PPTX → PDF → slide images for QA |

---

## 7. Data Model (SQLite)

```sql
-- Template profiles (reusable across generations)
CREATE TABLE templates (
    id TEXT PRIMARY KEY,              -- UUID
    name TEXT NOT NULL,
    type TEXT NOT NULL,               -- 'brand' or 'strict'
    brand_json TEXT NOT NULL,         -- BrandDNA as JSON
    slides_json TEXT NOT NULL,        -- SlideSpec[] as JSON
    source_file TEXT NOT NULL,        -- path to original .pptx
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Generation jobs
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,              -- UUID
    template_id TEXT NOT NULL REFERENCES templates(id),
    instructions TEXT,                -- optional user instructions
    config_json TEXT,                 -- GenerationConfig as JSON
    status TEXT NOT NULL DEFAULT 'queued',
        -- queued → analyzing → planning → generating → qa → fixing → done | error
    progress REAL NOT NULL DEFAULT 0.0,
    qa_rounds INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT,               -- Warning[] as JSON
    result_file TEXT,                 -- path to generated .pptx
    preview_dir TEXT,                 -- path to slide preview images
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

-- Uploaded source documents per job
CREATE TABLE job_documents (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,          -- path to uploaded file
    markdown_content TEXT,            -- MarkItDown output
    structured_json TEXT,             -- LLM-extracted structure
    created_at TEXT NOT NULL
);

-- Slide outlines (generated per job)
CREATE TABLE slide_outlines (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    slide_index INTEGER NOT NULL,
    mode TEXT NOT NULL,               -- 'strict' or 'flexible'
    label TEXT NOT NULL,
    content_json TEXT NOT NULL,       -- content allocation, field mappings
    layout_json TEXT NOT NULL,        -- layout choice, visual elements
    pptxgenjs_code TEXT,             -- generated JS code (flexible only)
    qa_status TEXT,                   -- 'pass', 'fail', 'fixed'
    qa_issues_json TEXT,             -- issues found by QA
    created_at TEXT NOT NULL
);
```

### File System Layout

```
./data/
├── templates/
│   ├── {template_id}/
│   │   ├── source.pptx              # Original uploaded template
│   │   ├── unpacked/                 # Unpacked XML (for strict editing)
│   │   ├── thumbnails/               # Slide thumbnail images
│   │   └── profile.json              # Cached template profile
│   └── ...
├── jobs/
│   ├── {job_id}/
│   │   ├── documents/                # Uploaded source docs
│   │   ├── markdown/                 # MarkItDown output per doc
│   │   ├── outline.json              # Generated slide outline
│   │   ├── slides/                   # Per-slide PptxGenJS scripts
│   │   ├── output.pptx               # Final generated deck
│   │   ├── preview/                  # Slide images for UI + QA
│   │   │   ├── slide-01.jpg
│   │   │   ├── slide-02.jpg
│   │   │   └── ...
│   │   └── qa/                       # QA inspection logs
│   │       ├── round-1.json
│   │       └── round-2.json
│   └── ...
└── slideforge.db                     # SQLite database
```

---

## 8. Template Profile Schema

```json
{
  "id": "uuid",
  "name": "Q4 Project Review Template",
  "type": "strict",
  "brand": {
    "colors": {
      "primary": "1E2761",
      "secondary": "CADCFC",
      "accent": "FF6B35",
      "background_dark": "1E2761",
      "background_light": "F5F7FA",
      "text_dark": "1E2761",
      "text_light": "FFFFFF"
    },
    "fonts": {
      "heading": "Calibri",
      "body": "Calibri Light"
    },
    "logo": {
      "path": "media/logo.png",
      "placement": "top-right",
      "size": { "w": 1.2, "h": 0.4 }
    },
    "design_notes": "Dark navy backgrounds on title/closing slides, light backgrounds for content. Clean, corporate aesthetic with ice blue accents."
  },
  "slides": [
    {
      "index": 0,
      "mode": "strict",
      "label": "Title Slide",
      "layout_name": "Title Slide",
      "schema": {
        "fields": [
          {
            "id": "project_title",
            "type": "text",
            "location": "shape:Title1",
            "max_chars": 60,
            "required": true
          },
          {
            "id": "project_date",
            "type": "date",
            "format": "MMMM YYYY",
            "location": "shape:DatePlaceholder",
            "required": true
          }
        ]
      }
    },
    {
      "index": 1,
      "mode": "strict",
      "label": "Status Dashboard",
      "schema": {
        "fields": [
          {
            "id": "overall_rag",
            "type": "enum",
            "values": ["green", "amber", "red"],
            "location": "shape:RAGIndicator",
            "render": "fill_color",
            "color_map": {
              "green": "00B050",
              "amber": "FFC000",
              "red": "FF0000"
            }
          },
          {
            "id": "key_risks",
            "type": "text_list",
            "location": "shape:RisksBox",
            "max_items": 4,
            "max_chars_per_item": 80
          }
        ]
      }
    },
    {
      "index": 2,
      "mode": "flexible",
      "label": "Project Requirements",
      "intent": "Present the key requirements and scope.",
      "content_category": "requirements",
      "visual_guidance": "Icon rows or two-column layout. Not bullets."
    }
  ]
}
```

---

## 9. Web Application

### 9.1 UI Flow

**Step 1: Template Setup** (one-time per template)
- Upload PPTX template
- System analyzes → shows thumbnail grid of all slides
- Each slide labeled strict or flexible with reasoning
- Click any slide to override classification or edit schema
- Save as reusable Template Profile

**Step 2: Generate Deck**
- Select a saved Template Profile from dropdown
- Upload one or more source documents (drag-and-drop)
- Optional: text box for additional instructions
- Click Generate → progress bar with status updates

**Step 3: Review & Download**
- View generated deck as slide thumbnail grid (the QA-inspected images)
- Warnings displayed for any `[INSERT CONTENT HERE]` placeholder slides
- Download PPTX button
- Per-slide "Regenerate" button for individual slide redo

### 9.2 API Endpoints

```
POST   /api/templates/analyze          Upload and analyze template PPTX
GET    /api/templates                   List saved templates
GET    /api/templates/{id}              Get template profile + thumbnails
PATCH  /api/templates/{id}              Update slide classifications/schema
DELETE /api/templates/{id}              Remove template

POST   /api/jobs                        Start generation job
GET    /api/jobs/{id}                   Get job status + progress
GET    /api/jobs/{id}/preview           Get slide preview images
GET    /api/jobs/{id}/download          Download generated PPTX
POST   /api/jobs/{id}/regen/{slide}     Regenerate a specific slide

GET    /api/jobs                        List recent jobs
```

---

## 10. Visual Asset Strategy

### Icons (Primary Visual Element)

Every flexible slide uses icons as visual anchors. The LLM selects semantically appropriate icons from the react-icons catalog.

**Pipeline:** LLM picks icon name → `react-icons` component → `ReactDOMServer.renderToStaticMarkup()` → `sharp` rasterize to PNG at 256px → base64 embed in PptxGenJS `addImage()`.

**Presentation patterns:**
- **Icon + text rows** — Icon in a colored circle (brand accent), bold header, description below. 3-4 rows per slide.
- **Icon grid** — 2x2 or 2x3 grid, each cell has an icon + label. Good for categories, features, capabilities.
- **Section marker** — Large icon (0.8-1.0") at top of slide as a visual anchor for the topic.
- **Inline accents** — Small icons (0.3-0.4") next to headers or key points.

### Charts

PptxGenJS native charting from extracted numeric data:
- Bar/column charts for comparisons
- Line charts for trends
- Pie/doughnut for composition
- Brand-consistent colors: `chartColors` matches template palette
- Clean styling: subtle gridlines, data labels, no chart junk

### Data Callouts

Large numbers (60-72pt) with small descriptive labels below (12-14pt). Arranged in a row of 3-4 across the slide. The fastest way to make a slide look "designed."

### Decorative Shapes

- Colored rectangles for card backgrounds
- Accent bars (thin rectangles in accent color) as section dividers
- Circles as icon containers
- Semi-transparent overlays for visual depth

---

## 11. Unmappable Strict Fields

When the system can't find content in the source documents for a required strict-slide field:

- Insert `[INSERT CONTENT HERE]` as the field value
- This text is intentional, obvious, and easy to Ctrl+H in PowerPoint
- The QA agent is told NOT to flag these as errors
- The UI preview highlights slides containing these placeholders with a yellow warning badge
- The API response includes a `warnings` array listing all placeholder fields

---

## 12. Phase Plan

### Phase 1: Foundation (Weeks 1-3)
- Docker setup with Bedrock credentials
- FastAPI + React scaffold with SQLite
- MarkItDown document ingestion (all formats)
- Brand template analysis (color/font/layout extraction via LLM vision)
- PptxGenJS slide generation for flexible slides (LLM generates JS code)
- Icon pipeline (react-icons → sharp → base64 → PptxGenJS)
- **Visual QA pipeline** (soffice → pdftoppm → LLM inspect → fix loop)
- End-to-end: upload brand template + doc → get QA'd deck → download

### Phase 2: Strict Templates (Weeks 4-6)
- Strict/flexible slide classification via LLM vision
- Schema extraction for strict slides
- python-pptx XML editing for strict slide content injection
- Hybrid assembly (strict XML + flexible PptxGenJS in one deck)
- Template Profile management UI (review/override classifications)
- `[INSERT CONTENT HERE]` placeholder handling

### Phase 3: Polish (Weeks 7-9)
- Chart generation from numeric data
- Multi-document fusion
- Layout variety enforcement (no consecutive repeats)
- Data callout generation (big numbers + labels)
- Text wall detection hardened in QA
- Per-slide regeneration
- Generation history in UI

### Phase 4: Refinement (Weeks 10+)
- Template library (browse, duplicate saved templates)
- Improved icon selection (LLM learns which icons work best)
- Performance optimization (parallel slide generation)
- PDF export option
- Better error recovery and retry logic

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| XML editing corrupts strict slides | Validate via python-pptx after every edit; fallback to recreating from layout |
| LLM hallucinates content not in source docs | Constrain to DocumentBundle; user review step |
| PptxGenJS output doesn't match template look | Extract precise brand DNA; Visual QA catches mismatches |
| QA agent misses issues | "Assume problems exist" prompt; text wall detector as explicit check |
| LibreOffice rendering ≠ PowerPoint rendering | Known limitation; focus QA on layout/overlap issues that render consistently |
| AWS creds not available in container | Validate boto3 session on startup with clear error message |
| PptxGenJS code generation has bugs | QA catches visual bugs; common pitfalls list in LLM prompt |

---

## 14. Success Metrics

| Metric | Target |
|--------|--------|
| Generation time | < 2 min for 10-slide deck |
| Text wall rate | < 5% of flexible slides after QA |
| Strict field accuracy | > 95% correctly populated |
| QA rounds needed | ≤ 2 on average |
| Usability | Decks usable after minor edits, not major rework |