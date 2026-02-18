import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.routes import downloads, jobs, templates
from app.services.bedrock import BedrockClient
from app.services.coherence_check import CoherenceCheck
from app.services.content_generator import ContentGenerator
from app.services.deck_planner import DeckPlanner
from app.services.input_parser import InputParser
from app.services.pptx_pipeline import PPTXPipeline
from app.services.template_registry import TemplateRegistry
from app.services.xml_injector import XMLInjector
from app.storage.local import LocalStorage
from app.store.sqlite import SQLiteJobStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings

    # Ensure local directories exist
    Path(settings.staging_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.outputs_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    # Initialize services
    # Storage base is the parent of the templates directory so that
    # relative paths like "templates/..." resolve correctly
    templates_path = Path(settings.templates_dir).resolve()
    storage_base = str(templates_path.parent)
    storage = LocalStorage(base_path=storage_base)
    app.state.storage = storage

    job_store = SQLiteJobStore(db_path=settings.sqlite_path)
    await job_store.initialize()
    app.state.job_store = job_store

    registry = TemplateRegistry(templates_dir=settings.templates_dir)
    await registry.load_all()
    app.state.template_registry = registry

    # Bedrock client (None if credentials not available)
    bedrock: BedrockClient | None = None
    if settings.bedrock_region:
        try:
            import boto3

            session_kwargs: dict = {"region_name": settings.bedrock_region}
            if settings.aws_profile:
                session_kwargs["profile_name"] = settings.aws_profile
            session = boto3.Session(**session_kwargs)
            session.client("sts").get_caller_identity()
            bedrock = BedrockClient(
                region=settings.bedrock_region,
                profile_name=settings.aws_profile,
            )
            logger.info("Bedrock client initialized (region=%s, profile=%s)",
                        settings.bedrock_region, settings.aws_profile or "default")
        except Exception:
            logger.info("Bedrock unavailable (no AWS credentials), Mode 2 and LLM coercion disabled")

    # InputParser (strict mode when Bedrock unavailable)
    app.state.input_parser = InputParser(
        bedrock=bedrock, model_id=settings.haiku_model_id,
    )

    # Mode 2 services (only available when Bedrock is configured)
    if bedrock:
        app.state.deck_planner = DeckPlanner(
            bedrock_client=bedrock, model_id=settings.sonnet_model_id,
        )
        app.state.content_generator = ContentGenerator(
            bedrock_client=bedrock, model_id=settings.sonnet_model_id,
        )
        app.state.coherence_check = CoherenceCheck(
            bedrock_client=bedrock, model_id=settings.haiku_model_id,
        )
    else:
        app.state.deck_planner = None
        app.state.content_generator = None
        app.state.coherence_check = None

    # PPTXPipeline
    injector = XMLInjector()
    app.state.pipeline = PPTXPipeline(
        storage=storage,
        injector=injector,
        staging_base=settings.staging_dir,
    )

    logger.info(
        "SlideAgent started (templates=%d)",
        len(registry.list_templates()),
    )
    yield

    await job_store.close()
    logger.info("SlideAgent shutting down")


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = FastAPI(
        title="SlideAgent",
        version="0.1.0",
        description="AI-powered PowerPoint generation service",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(templates.router)
    app.include_router(jobs.router)
    app.include_router(downloads.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
