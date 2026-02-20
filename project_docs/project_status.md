# Project Status

## Implemented
- Scaffolded backend FastAPI service with config, storage, and SQLite persistence.
- Added Bedrock client, template analyzer, document ingester, content planner, design agent, PPTX builder, strict injector, hybrid assembler, and visual QA pipeline.
- Implemented API routes for templates, jobs, preview images, regeneration, and downloads (PPTX/PDF).
- Added PptxGenJS runner and Node-based icon pipeline for flexible slide generation.
- Built React frontend scaffold with template setup, deck generation, and review/download flows.
- Added Dockerfile and docker-compose for single-container deployment.
- Implemented in-process job queue/worker with startup recovery of queued/running jobs.
- Added strict schema constraint inference and strict value validation for injection.
- Hardened QA parsing with structured JSON extraction and schema validation fallback.
- Added template schema editor UI for strict-slide field overrides and validation hints.
- Added warnings rendering in review UI and focused backend regression tests.

## Next To Implement
- Extend strict field extraction beyond text frames to chart/table placeholders.
- Add worker metrics/telemetry (queue depth, average latency, retry counts).
- Add end-to-end tests covering queue resume with real persistence and API lifecycle.
- Improve per-slide warning badges with thumbnails and quick-jump UX.

## Debug Log
- Initialized backend/frontend scaffolds and verified configuration paths.
- Implemented service layer modules and wired orchestrator flow end-to-end.
- Added hybrid PPTX assembly with media/charts copying and content type updates.
- Built frontend pages and connected to API endpoints for MVP workflow.
- Added PDF export and retry logic for Bedrock calls.
- Replaced direct `asyncio.create_task` job launches with queue-based worker execution.
- Added strict validator normalization for enum, list, text, and numeric fields.
- Implemented deterministic QA JSON parsing with fenced-block extraction fallback.
- Verified new backend tests pass (`5 passed`) via `python -m pytest tests -q`.
