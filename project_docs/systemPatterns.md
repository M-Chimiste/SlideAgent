# SlideAgent — System Patterns

## Core Architectural Principle
**The LLM generates content strings. Python services handle all file I/O, XML manipulation, and constraint enforcement.** These concerns are never mixed. An LLM call never directly touches a file. A Python service never generates creative content. Every LLM call has a defined input schema and a defined output schema (Pydantic models). If a service needs LLM output, it calls the LLM client and receives structured data — it does not prompt-engineer inside the service.

## PPTX as XML
PPTX files are ZIP archives containing XML. SlideAgent works at the XML level at runtime — never through python-pptx's write API. python-pptx is used only for template introspection during schema authoring (one-time, dev-time operation).

**Runtime pipeline:**
```
template.pptx
  → unzip to staging dir
  → parse slide{N}.xml with lxml
  → navigate to target elements by shape ID
  → replace <a:t> content in <a:r> runs
  → validate output XML is well-formed
  → rezip to output.pptx
  → cleanup staging dir
```

**Why not python-pptx for writes:** The python-pptx write API reconstructs XML and does not preserve all template formatting attributes. Direct XML manipulation preserves every attribute the template author set.

**Why lxml over defusedxml for manipulation:** defusedxml is used for parsing untrusted input. lxml is used for manipulation because it provides full XPath and element tree editing. Both can be used together: parse with defusedxml, pass the tree to lxml-compatible operations.

## Template Schema Pattern
Every template in the registry has an associated JSON schema that maps human-readable field names to XML locations. This schema is the contract between the input data model and the PPTX pipeline.

```json
{
  "template_id": "novartis-status-weekly-v2",
  "slides": {
    "2": {
      "fields": {
        "project_name":    {"shape_id": 3, "type": "text", "max_chars": 80},
        "status":          {"shape_id": 7, "type": "enum", "values": ["Green","Amber","Red"]},
        "summary":         {"shape_id": 9, "type": "text", "max_chars": 320},
        "owner":           {"shape_id": 12, "type": "text", "max_chars": 50},
        "report_date":     {"shape_id": 14, "type": "date", "format": "%d %b %Y"}
      }
    }
  }
}
```

Shape IDs are stable within a template version. Template versions are immutable once registered — a new upload creates a new version.

## Agent Workflow Patterns

### Mode 1: Sequential Deterministic Pipeline
No LLM planning step. The pipeline is fixed:
```
InputParser → FieldMapper → ConstraintValidator → XMLInjector → QAValidator → Output
```
LLM is invoked only if `InputParser` encounters ambiguous or verbose fields that need coercion to schema constraints. All other steps are pure Python.

### Mode 2: Plan-then-Execute
A two-phase agentic pattern:
```
Phase 1 (Planning):   BriefParser → DeckPlanner (LLM) → OutlineValidator → [User Approval Gate]
Phase 2 (Execution):  ContentGenerator (LLM, per slide) → CoherenceCheck (LLM) → ConstraintValidator → XMLInjector → QAValidator → Output
```
The approval gate between phases is a hard stop — content generation does not begin until the outline is confirmed. This prevents wasted LLM calls on rejected plans and gives users meaningful control.

### LLM Call Isolation
Every LLM call is encapsulated in a dedicated function with:
- A typed input model (Pydantic)
- A system prompt constant (not built dynamically)
- A typed output model (Pydantic) that Bedrock is instructed to conform to
- Retry logic with exponential backoff (max 3 attempts)
- Token budget enforcement (max_tokens set per call type)

LLM functions are never called inside loops without explicit batching logic. The ContentGenerator calls are parallelizable (each slide is independent) and should be executed concurrently with asyncio.gather.

## Job Model
All generation tasks are modeled as async jobs, even in local development. This decouples the HTTP request lifecycle from the generation pipeline and allows the frontend to poll for status.

```
POST /jobs → returns job_id immediately
GET  /jobs/{id} → returns {status, progress, error, output_url}
```

Job states: `queued → planning → awaiting_approval → generating → packaging → complete | failed`

Jobs are stored in a lightweight SQLite database locally.

## Error Handling Hierarchy
1. **Schema validation errors** (missing required fields, type mismatches): return 422 with field-level detail before job is created
2. **Constraint violations** (text too long, invalid enum): surface as named warnings in job status; generation proceeds with truncation or flags for user review depending on severity config
3. **LLM failures** (timeout, malformed output): retry up to 3 times, then fail the job with a structured error indicating which stage failed
4. **XML errors** (malformed output after injection): fail the job, preserve the staging directory for debugging, log the diff
5. **Pipeline errors** (disk, permissions, zip failures): fail fast, surface as 500 with correlation ID

## File Handling
- Templates are stored on the local filesystem and referenced by template_id
- Staging directories for in-flight jobs use a temp dir scoped to job_id, cleaned up on completion or failure
- Output PPTX files are written to the outputs directory and served as file downloads
- No user data persists beyond job TTL (24 hours default, configurable)

## Frontend State Machine
The React frontend models each job as a state machine matching backend job states. UI transitions are driven by polling `GET /jobs/{id}` every 2 seconds during active states. The outline approval step renders as a blocking modal with editable outline before Phase 2 begins.
