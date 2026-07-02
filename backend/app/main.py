from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.clients.bedrock_client import BedrockClient
from app.clients.openai_compatible_client import OpenAICompatibleClient
from app.config import get_settings
from app.infra.local_storage import LocalStorage
from app.infra.sqlite_store import SQLiteStore
from app.routes.health import router as health_router
from app.routes.jobs import router as jobs_router
from app.routes.templates import router as templates_router
from app.services.content_planner import ContentPlanner
from app.services.design_agent import DesignAgent
from app.services.document_ingester import DocumentIngester
from app.services.job_queue import JobQueue
from app.services.orchestrator import JobOrchestrator
from app.services.pptx_builder import PptxBuilder
from app.services.template_analyzer import TemplateAnalyzer
from app.services.visual_qa_agent import VisualQAAgent
from app.workers.node_runner import NodePptxGenRunner


def create_app() -> FastAPI:
    settings = get_settings()
    store = SQLiteStore(settings)
    storage = LocalStorage(settings)
    bedrock = None
    llm_client = None

    if settings.llm_provider == "bedrock":
        bedrock = BedrockClient(settings)
    elif settings.llm_provider == "openai_compatible":
        llm_client = OpenAICompatibleClient(settings)

    if bedrock and settings.bedrock_validate_on_startup:
        bedrock.validate()

    template_analyzer = TemplateAnalyzer(bedrock=bedrock)
    ingester = DocumentIngester()
    planner = ContentPlanner(
        llm_client=llm_client,
        slide_generation_strategy="batched",
        decompose=settings.planner_decompose,
    )
    designer = DesignAgent()
    node_runner = NodePptxGenRunner(settings)
    builder = PptxBuilder(
        node_runner,
        renderer_engine=settings.renderer_engine,
        brand_layout_instantiation=settings.brand_layout_instantiation,
        brand_render_mode=settings.brand_render_mode,
    )
    vision_client = None
    if settings.llm_provider == "openai_compatible":
        vision_client = OpenAICompatibleClient(
            settings.model_copy(
                update={
                    "openai_compatible_base_url": settings.vision_base_url,
                    "openai_compatible_model": settings.vision_model,
                    "openai_compatible_timeout_seconds": settings.vision_timeout_seconds,
                    "openai_compatible_reasoning_effort": settings.vision_reasoning_effort,
                }
            )
        )
    qa_agent = VisualQAAgent(
        bedrock=bedrock,
        openai_client=vision_client,
        model_id=settings.sonnet_model_id,
        vision_max_slides=settings.vision_max_slides,
    )
    orchestrator = JobOrchestrator(
        settings=settings,
        store=store,
        storage=storage,
        ingester=ingester,
        planner=planner,
        designer=designer,
        builder=builder,
        qa_agent=qa_agent,
    )
    job_queue = JobQueue(
        store=store,
        orchestrator=orchestrator,
        worker_concurrency=getattr(settings, "job_worker_concurrency", 1),
    )

    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.store = store
    app.state.storage = storage
    app.state.template_analyzer = template_analyzer
    app.state.orchestrator = orchestrator
    app.state.job_queue = job_queue

    app.include_router(health_router, prefix="/api")
    app.include_router(templates_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")

    dist_dir = settings.frontend_dist_dir
    if dist_dir.exists():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")

    @app.on_event("startup")
    async def _startup() -> None:
        await store.init()
        await job_queue.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await job_queue.stop()

    return app


app = create_app()
