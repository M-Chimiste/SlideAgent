from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.clients.bedrock_client import BedrockClient
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
    bedrock = BedrockClient(settings)

    if settings.bedrock_validate_on_startup:
        bedrock.validate()

    template_analyzer = TemplateAnalyzer(bedrock=bedrock)
    ingester = DocumentIngester()
    planner = ContentPlanner()
    designer = DesignAgent()
    node_runner = NodePptxGenRunner(settings)
    builder = PptxBuilder(node_runner)
    qa_agent = VisualQAAgent(bedrock=bedrock, model_id=settings.sonnet_model_id)
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
