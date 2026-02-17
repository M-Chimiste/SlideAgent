# SlideAgent — Product Requirements Document

## Overview
SlideAgent is an internal web application that generates PowerPoint presentations via two agent-driven modes: structured template population from input data (Mode 1), and branded content generation from a topic brief (Mode 2). It runs in AWS, uses Amazon Bedrock for LLM inference, and produces PPTX output compatible with Microsoft PowerPoint.

---

## Functional Requirements

### FR-1: Template Registry

**FR-1.1** The system shall maintain a registry of available templates, each identified by a unique template_id, display name, version, and mode compatibility (Mode 1, Mode 2, or both).

**FR-1.2** Each Mode 1 template shall have an associated JSON schema defining injectable fields, their slide and shape ID locations, data types, constraints (max_chars, allowed enum values, date formats), and whether they are required.

**FR-1.3** Each Mode 2 template shall have an associated layout library defining available slide layouts, their names, suitable content types, and field structure.

**FR-1.4** Templates shall be versioned. A new template upload creates a new version. Prior versions remain accessible. Jobs reference a specific version at time of creation.

**FR-1.5** A developer-facing CLI tool (`scripts/analyze_template.py`) shall accept a `.pptx` file and output a candidate JSON schema mapping shape IDs to their current text content, to accelerate schema authoring.

---

### FR-2: Job Lifecycle

**FR-2.1** The system shall accept job creation requests specifying: template_id, mode (1 or 2), and input payload.

**FR-2.2** Job creation shall perform synchronous schema validation before accepting the job. Invalid payloads return 422 with field-level error detail. No job record is created for invalid requests.

**FR-2.3** Accepted jobs shall be queued and processed asynchronously. Job creation returns a job_id immediately.

**FR-2.4** Job status shall be queryable and return: job_id, status, progress percentage, current stage name, error details (if failed), and output URL (if complete).

**FR-2.5** Job states shall follow this sequence:
- `queued` → `parsing` → `generating` → `packaging` → `complete`
- Mode 2 inserts `planning` between `parsing` and `generating`, and `awaiting_approval` between `planning` and `generating`
- Any state may transition to `failed`

**FR-2.6** Completed jobs shall produce a downloadable PPTX accessible via presigned URL for 1 hour (configurable).

**FR-2.7** Job records and output files shall be deleted after 24 hours (configurable TTL).

---

### FR-3: Mode 1 — Template Population

**FR-3.1** The system shall accept structured input as JSON matching the template's field schema. Future versions may accept CSV or Excel, normalized to JSON internally.

**FR-3.2** The InputParser shall map input fields to template schema fields. Exact name matches are direct. Near-matches (e.g., "project_lead" → "owner") shall trigger an LLM coercion call.

**FR-3.3** The ConstraintValidator shall enforce: required field presence, enum value membership, text length within max_chars, and date format validity. Violations shall be categorized as errors (blocking) or warnings (non-blocking with truncation).

**FR-3.4** Long text that exceeds max_chars shall be truncated by the LLM with a preference for preserving complete sentences. Truncation shall be logged in the job record.

**FR-3.5** The XMLInjector shall inject all validated field values into the correct XML elements identified by slide index and shape ID. Existing XML attributes and sibling elements shall be preserved.

**FR-3.6** Output PPTX shall be verified to: open without XML errors, contain no unfilled placeholder markers, and have all required fields present.

---

### FR-4: Mode 2 — Branded Content Generation

**FR-4.1** The system shall accept a topic brief as freeform text and/or a structured JSON object containing: title, audience, key messages (list), tone, desired slide count range (min/max), and any sections to include or exclude.

**FR-4.2** The DeckPlanner shall produce a deck outline as structured JSON specifying: slide count, per-slide layout name, per-slide title, per-slide content summary (1-2 sentences), and narrative arc summary.

**FR-4.3** The outline shall be returned to the client as part of the job status response when the job enters `awaiting_approval` state. The client may modify the outline and submit approval, or reject and provide revision instructions.

**FR-4.4** Upon outline approval, the ContentGenerator shall generate full content for each slide concurrently. Each slide generation call shall receive: the layout definition (field names, types, constraints), the slide's outline entry, the full deck outline for context, and the topic brief.

**FR-4.5** The CoherenceCheck shall receive all generated slide content and the original brief, and return a list of flagged issues (inconsistencies, repetition, tonal drift) with suggested corrections. Corrections shall be applied automatically for minor issues; major issues shall be surfaced as warnings in the job record.

**FR-4.6** Content shall then pass through the same ConstraintValidator and XMLInjector as Mode 1.

---

### FR-5: Frontend

**FR-5.1** The UI shall present a template selection step with template name, description, mode compatibility, and version.

**FR-5.2** Mode 1 shall render a dynamic input form generated from the template schema, with appropriate input types (text, select for enums, date picker for dates), required field indicators, and character count feedback.

**FR-5.3** Mode 2 shall render a brief input form with all fields from FR-4.1, plus a layout preference option (auto / content-heavy / visual-heavy).

**FR-5.4** During generation, the UI shall display a progress indicator with the current stage name, updated by polling GET /jobs/{id} every 2 seconds.

**FR-5.5** For Mode 2, when the job enters `awaiting_approval`, the UI shall render the deck outline in an editable format. The user shall be able to: modify slide titles, reorder slides, change layout assignments (from available layouts), add slides, delete slides, and provide revision text for the planner. Approving the outline submits it and transitions the job to `generating`.

**FR-5.6** Upon job completion, the UI shall display a thumbnail grid of generated slides and a download button for the PPTX.

**FR-5.7** Errors shall be displayed with the failed stage, error message, and a retry option (for transient failures) or a correction prompt (for validation failures).

---

## Non-Functional Requirements

### NFR-1: Performance
- Mode 1 generation: under 30 seconds for a 20-slide deck
- Mode 2 generation (post-approval): under 90 seconds for a 15-slide deck
- API response time for job creation: under 500ms
- Status polling endpoint: under 100ms

### NFR-2: Security
- All processing occurs within AWS boundary; no data transmitted to external APIs
- Bedrock access via IAM role (no hardcoded credentials)
- Uploaded templates and input data stored only for job TTL duration
- Input data treated as untrusted; XML parsing uses defusedxml for template files
- Presigned S3 URLs for output download (no persistent public URLs)

### NFR-3: Reliability
- LLM calls: retry up to 3 times with exponential backoff before failing job
- Failed jobs preserve staging artifacts for 48 hours for debugging
- Storage writes are atomic (write to temp path, rename on success)

### NFR-4: Observability
- All jobs emit structured log events at each state transition
- LLM call logs include: model, token counts, latency, stage name
- Failed jobs log full error with stack trace and job context
- CloudWatch metrics for: job volume by mode, failure rate by stage, p50/p95 generation latency

### NFR-5: Extensibility
- Storage backend is abstracted (local / S3) with no service-layer changes required to switch
- Job store is abstracted (SQLite / DynamoDB)
- New LLM call types are added by defining a Pydantic I/O schema and a prompt constant — no changes to orchestration logic
- Designed for extraction as a module into Ariadne: the backend services have no UI coupling

---

## Out of Scope (v1)
- User authentication (internal tool, single user or trusted internal network)
- Multi-tenant template isolation
- Version history of generated decks
- Side-by-side diff of input vs output
- Real-time collaborative outline editing
- Image generation or automatic image sourcing
- Non-PPTX output formats
