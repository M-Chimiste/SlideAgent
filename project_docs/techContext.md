# SlideAgent — Tech Context

## Stack

### Frontend
| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | React 18 + TypeScript | Production-grade, extensible, avoids Streamlit limitations |
| Build tool | Vite | Fast dev server, native ESM, simple config |
| Styling | Tailwind CSS | Utility-first, consistent design system, no CSS file sprawl |
| UI components | shadcn/ui | Headless, accessible, copy-owned components (not a locked dependency) |
| State management | Zustand | Lightweight, no boilerplate, sufficient for job state machine |
| API client | TanStack Query | Polling, caching, loading states handled declaratively |
| File upload | react-dropzone | Drag-and-drop template + data upload |

### Backend
| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | FastAPI | Async-native, Pydantic-first, auto OpenAPI docs, Python-native |
| ASGI server | Uvicorn (dev) / Gunicorn+Uvicorn (prod) | Standard FastAPI deployment |
| LLM client | boto3 (Bedrock) | No third-party API keys, stays within AWS boundary |
| XML manipulation | lxml | Full XPath, fastest Python XML library |
| XML parsing (untrusted) | defusedxml | Security-safe parsing for user-uploaded templates |
| PPTX introspection | python-pptx | Dev-time only: template schema authoring |
| Job store | SQLite via aiosqlite | Lightweight async job persistence |
| File store | Local filesystem | Atomic writes via tmp+rename |
| Task queue | asyncio + BackgroundTasks (v1) / Celery + SQS (if needed) | Start simple, scale when job volume warrants it |

### Infrastructure (AWS)
| Component | Service | Notes |
|-----------|---------|-------|
| Backend API | AWS App Runner | Container-based, auto-scaling, IAM role for Bedrock access, no VPC required for v1 |
| Frontend | Vite dev server | Static build served locally |
| File storage | Local filesystem | Templates directory (versioned), outputs directory (24h TTL) |
| LLM | Amazon Bedrock | Claude via Bedrock API. Model: claude-sonnet-4-6 or claude-haiku-4-5 depending on call type |
| Secrets | AWS Secrets Manager | Any config that isn't IAM role-derivable |
| Logs | CloudWatch | App Runner streams logs automatically |
| Container registry | ECR | Backend Docker image |

### Local Development
```
backend/    → uvicorn app.main:app --reload --port 8000
frontend/   → npm run dev (Vite, port 5173, proxied to :8000)
storage/    → local filesystem under .data/
jobs/       → SQLite at .data/jobs.db
```

No Docker required for local dev. Docker Compose available for full-stack integration testing.

## Bedrock Configuration

### Model Selection by Call Type
| Agent Call | Model | Rationale |
|------------|-------|-----------|
| InputParser (field coercion) | claude-haiku-4-5 | Simple mapping task, low latency needed |
| DeckPlanner (outline generation) | claude-sonnet-4-6 | Needs reasoning about narrative structure |
| ContentGenerator (per slide) | claude-sonnet-4-6 | Quality content, run concurrently |
| CoherenceCheck | claude-haiku-4-5 | Light review pass, cost-sensitive |

### Invocation Pattern
All Bedrock calls use the `converse` API (not `invoke_model`) for consistent message formatting and tool use compatibility. Structured output is enforced via tool use — the LLM is given a single tool definition matching the desired Pydantic output schema and is required to call it.

```python
response = bedrock.converse(
    modelId="anthropic.claude-sonnet-4-6",
    system=[{"text": SYSTEM_PROMPT}],
    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
    toolConfig={"tools": [output_tool_definition], "toolChoice": {"tool": {"name": "output"}}},
    inferenceConfig={"maxTokens": 2048, "temperature": 0.3}
)
```

## Key Dependencies and Versions
```
# Backend
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.0
boto3>=1.34
lxml>=5.0
defusedxml>=0.7
python-pptx>=1.0        # dev-time template analysis only
python-multipart>=0.0.9 # file uploads

# Frontend
react@18
typescript@5
vite@5
tailwindcss@3
@tanstack/react-query@5
zustand@4
shadcn/ui (via CLI)
react-dropzone@14
```

## Project Structure
```
slideagent/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, route registration
│   │   ├── config.py                # Settings (env vars, Pydantic BaseSettings)
│   │   ├── routes/
│   │   │   ├── jobs.py              # POST /jobs, GET /jobs/{id}
│   │   │   ├── templates.py         # GET /templates, POST /templates
│   │   │   └── downloads.py         # GET /jobs/{id}/download
│   │   ├── services/
│   │   │   ├── bedrock.py           # LLM client wrapper
│   │   │   ├── pptx_pipeline.py     # Unpack → inject → repack
│   │   │   ├── xml_injector.py      # lxml-based XML manipulation
│   │   │   ├── constraint_validator.py
│   │   │   ├── input_parser.py      # Mode 1: field mapping + LLM coercion
│   │   │   ├── deck_planner.py      # Mode 2: outline generation
│   │   │   ├── content_generator.py # Mode 2: per-slide content
│   │   │   └── coherence_check.py   # Mode 2: final review pass
│   │   ├── models/
│   │   │   ├── jobs.py              # Job state machine
│   │   │   ├── templates.py         # Template schema models
│   │   │   └── schemas.py           # Pydantic I/O models for all LLM calls
│   │   └── storage/
│   │       └── local.py             # LocalStorage (filesystem + atomic writes)
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── TemplateSelector.tsx
│   │   │   ├── InputForm.tsx        # Dynamic form generated from template schema
│   │   │   ├── OutlineEditor.tsx    # Mode 2: plan approval step
│   │   │   ├── JobProgress.tsx      # Polling status display
│   │   │   └── SlidePreview.tsx     # Thumbnail grid
│   │   ├── stores/
│   │   │   └── jobStore.ts          # Zustand job state machine
│   │   └── api/
│   │       └── client.ts            # TanStack Query hooks
├── templates/                       # Template registry (dev)
│   └── {template_id}/
│       ├── template.pptx
│       └── schema.json
├── Dockerfile
├── docker-compose.yml
└── scripts/
    └── analyze_template.py          # Dev tool: introspect a .pptx and print shape map
```

## Environment Variables
```
# Backend
BEDROCK_REGION=us-east-1
AWS_PROFILE=
SONNET_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
HAIKU_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
SQLITE_PATH=.data/jobs.db
MAX_JOB_TTL_HOURS=24
LOG_LEVEL=INFO

# Frontend (build-time)
VITE_API_BASE_URL=http://localhost:8000
```
