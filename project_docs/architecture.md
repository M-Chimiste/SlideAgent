# SlideAgent — Architecture Diagrams

## System Architecture

```mermaid
graph TB
    subgraph Client["Client (Browser)"]
        UI[React Frontend<br/>Vite + TypeScript]
    end

    subgraph AWS["AWS"]
        subgraph CDN["CloudFront + S3"]
            STATIC[Static Frontend Build]
        end

        subgraph AppRunner["App Runner"]
            API[FastAPI Backend<br/>Uvicorn / Gunicorn]
        end

        subgraph Storage["S3"]
            TMPL_BUCKET[Templates Bucket<br/>versioned]
            OUT_BUCKET[Outputs Bucket<br/>24h lifecycle]
        end

        subgraph Compute["Serverless"]
            BEDROCK[Amazon Bedrock<br/>Claude claude-sonnet-4-6 / Haiku]
        end

        subgraph Data["Data"]
            DYNAMO[DynamoDB<br/>Job Records]
        end
    end

    UI -->|HTTPS REST| API
    UI -->|Presigned URL| OUT_BUCKET
    STATIC -->|Serves| UI
    API -->|Read template| TMPL_BUCKET
    API -->|Write output| OUT_BUCKET
    API -->|Job state| DYNAMO
    API -->|Converse API| BEDROCK
```

---

## Backend Service Architecture

```mermaid
graph TD
    subgraph Routes["FastAPI Routes"]
        R1[POST /jobs]
        R2[GET /jobs/:id]
        R3[POST /jobs/:id/approve]
        R4[GET /templates]
        R5[POST /templates]
    end

    subgraph Orchestration["Job Orchestration"]
        ORCH[Job Runner<br/>asyncio BackgroundTask]
    end

    subgraph Services["Core Services"]
        IP[InputParser<br/>field mapping + coercion]
        CV[ConstraintValidator<br/>pure Python]
        DP[DeckPlanner<br/>outline generation]
        CG[ContentGenerator<br/>per-slide content]
        CC[CoherenceCheck<br/>review pass]
        XI[XMLInjector<br/>lxml manipulation]
        PP[PPTXPipeline<br/>unzip → edit → rezip]
    end

    subgraph LLM["LLM Client"]
        BC[BedrockClient<br/>boto3 converse]
    end

    subgraph Storage["Storage"]
        ST[StorageInterface]
        SL[LocalStorage]
        SS[S3Storage]
    end

    subgraph JobStore["Job Store"]
        JS[JobStoreInterface]
        SQ[SQLiteStore]
        DY[DynamoDBStore]
    end

    R1 --> ORCH
    R2 --> JS
    R3 --> ORCH
    R4 --> ST
    R5 --> ST

    ORCH --> IP
    ORCH --> CV
    ORCH --> DP
    ORCH --> CG
    ORCH --> CC
    ORCH --> XI
    ORCH --> PP
    ORCH --> JS

    IP --> BC
    DP --> BC
    CG --> BC
    CC --> BC

    PP --> ST
    ST --> SL
    ST --> SS
    JS --> SQ
    JS --> DY
```

---

## Mode 1: Template Population Flow

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as FastAPI
    participant IP as InputParser
    participant CV as ConstraintValidator
    participant XI as XMLInjector
    participant PP as PPTXPipeline
    participant BC as BedrockClient
    participant S3

    User->>FE: Select template, fill form
    FE->>API: POST /jobs {template_id, mode:1, input_data}
    API->>API: Schema validation (sync)
    alt Validation fails
        API-->>FE: 422 with field errors
    else Validation passes
        API-->>FE: 202 {job_id}
        API->>API: Queue background job

        Note over API,S3: Background job starts
        API->>IP: Parse + map fields
        IP->>BC: Coerce ambiguous fields (if any)
        BC-->>IP: Coerced field values
        IP-->>API: Mapped field values

        API->>CV: Validate all fields
        CV-->>API: Validated values + warnings

        API->>S3: Fetch template.pptx
        S3-->>API: template bytes

        API->>PP: Unpack template
        PP-->>API: Staging dir path

        API->>XI: Inject all fields into XML
        XI-->>API: Modified XMLs

        API->>PP: Repack to output.pptx
        PP-->>API: output bytes

        API->>S3: Write output.pptx
        S3-->>API: Presigned URL

        API->>API: Update job status → complete
    end

    FE->>API: GET /jobs/{id} (polling)
    API-->>FE: {status: complete, output_url}
    FE-->>User: Show thumbnail + download button
```

---

## Mode 2: Branded Content Generation Flow

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as FastAPI
    participant DP as DeckPlanner
    participant CG as ContentGenerator
    participant CC as CoherenceCheck
    participant CV as ConstraintValidator
    participant XI as XMLInjector
    participant PP as PPTXPipeline
    participant BC as BedrockClient
    participant S3

    User->>FE: Select branding template, write brief
    FE->>API: POST /jobs {template_id, mode:2, input_data}
    API-->>FE: 202 {job_id}

    Note over API,BC: Phase 1 - Planning
    API->>DP: Generate deck outline from brief
    DP->>BC: DeckPlanner prompt (claude-sonnet-4-6)
    BC-->>DP: DeckOutline JSON
    DP-->>API: Validated DeckOutline

    API->>API: Update job status → awaiting_approval
    FE->>API: GET /jobs/{id} (polling)
    API-->>FE: {status: awaiting_approval, outline: DeckOutline}
    FE-->>User: Show editable outline

    alt User edits and approves
        User->>FE: Edit outline, click Approve
        FE->>API: POST /jobs/{id}/approve {revised_outline}
    else User rejects with instructions
        User->>FE: Add revision notes, click Re-plan
        FE->>API: POST /jobs/{id}/approve {approved:false, revision_instructions}
        API->>DP: Re-plan with revision instructions
        DP->>BC: Revised DeckPlanner prompt
        BC-->>DP: Revised DeckOutline
        API->>API: Update status → awaiting_approval again
    end

    Note over API,BC: Phase 2 - Content Generation
    API->>API: Update status → generating

    par Generate all slides concurrently
        API->>CG: Generate slide 1 content
        CG->>BC: ContentGenerator prompt
        BC-->>CG: SlideContent
    and
        API->>CG: Generate slide N content
        CG->>BC: ContentGenerator prompt
        BC-->>CG: SlideContent
    end

    API->>CC: Coherence check all slide content
    CC->>BC: CoherenceCheck prompt (claude-haiku-4-5)
    BC-->>CC: CoherenceCheckOutput
    CC-->>API: Issues + corrections applied

    API->>CV: Validate all field content
    CV-->>API: Validated values + warnings

    API->>S3: Fetch branding template.pptx
    API->>PP: Unpack template
    API->>XI: Inject all slide content
    API->>PP: Repack output.pptx
    API->>S3: Write output

    API->>API: Update job status → complete
    FE-->>User: Show thumbnail + download button
```

---

## PPTX Pipeline Detail

```mermaid
flowchart TD
    A[template.pptx from S3/disk] --> B[Unzip to staging_dir/job_id/]
    B --> C[Parse presentation.xml<br/>Build slide index map]
    C --> D{For each InjectionTarget}
    D --> E[Open slide{N}.xml with lxml]
    E --> F[XPath to shape by shape_id]
    F --> G{Shape found?}
    G -->|No| H[Log warning: shape_id missing<br/>Continue]
    G -->|Yes| I[Find all a:t elements in shape]
    I --> J[Replace text content<br/>Preserve a:rPr attributes]
    J --> K[Validate XML well-formed]
    K --> L{Valid?}
    L -->|No| M[Fail job<br/>Preserve staging dir]
    L -->|Yes| N[Write modified slide{N}.xml]
    N --> D
    D -->|All slides done| O[Run clean pass<br/>Remove orphaned rels]
    O --> P[Rezip to output.pptx<br/>Preserve original theme/media]
    P --> Q[Verify output opens<br/>No XML parse errors]
    Q --> R[Upload to S3<br/>Generate presigned URL]
    R --> S[Cleanup staging dir]
    S --> T[Return PipelineResult]
```

---

## Frontend State Machine

```mermaid
stateDiagram-v2
    [*] --> TemplateSelect
    TemplateSelect --> InputForm : template selected
    InputForm --> Submitting : form submitted
    Submitting --> Polling : job_id received
    Submitting --> InputForm : 422 validation error

    state Polling {
        [*] --> queued
        queued --> parsing
        parsing --> planning : mode 2 only
        planning --> AwaitingApproval : mode 2 only
        parsing --> generating : mode 1
        AwaitingApproval --> generating : approved
        AwaitingApproval --> planning : rejected / re-plan
        generating --> packaging
        packaging --> complete
    }

    Polling --> Failed : any → failed
    Polling --> Complete : complete

    state AwaitingApproval {
        [*] --> ShowOutline
        ShowOutline --> EditOutline : user edits
        EditOutline --> ShowOutline : edits saved
        ShowOutline --> Approving : approve clicked
        ShowOutline --> Rejecting : reject clicked
    }

    Complete --> [*] : download PPTX
    Failed --> InputForm : retry
```
