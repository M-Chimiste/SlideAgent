from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Anchor the .env to the repo root (next to data/) so it loads no matter the
    # process cwd — the backend is usually launched from backend/, where a plain
    # relative ".env" would silently miss the root file. In Docker the file is
    # absent and pydantic falls back to real environment variables.
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    app_name: str = "SlideForge"
    environment: str = "dev"

    data_dir: Path = BASE_DIR / "data"
    sqlite_path: Path = BASE_DIR / "data" / "slideforge.db"
    templates_dir: Path = BASE_DIR / "data" / "templates"
    jobs_dir: Path = BASE_DIR / "data" / "jobs"

    frontend_dist_dir: Path = BASE_DIR / "frontend" / "dist"

    aws_profile: str | None = Field(default=None, alias="AWS_PROFILE")
    aws_region: str = Field(default="us-east-1", alias="AWS_DEFAULT_REGION")

    sonnet_model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-20250514", alias="SONNET_MODEL_ID"
    )
    haiku_model_id: str = Field(
        default="us.anthropic.claude-haiku-4-5-20251001", alias="HAIKU_MODEL_ID"
    )

    llm_provider: str = Field(default="openai_compatible", alias="LLM_PROVIDER")
    openai_compatible_base_url: str = Field(
        default="http://localhost:1240/v1", alias="OPENAI_COMPATIBLE_BASE_URL"
    )
    openai_compatible_model: str = Field(
        default="qwen3.6-35b-a3b-mtp", alias="OPENAI_COMPATIBLE_MODEL"
    )
    openai_compatible_api_key: str = Field(
        default="lm-studio", alias="OPENAI_COMPATIBLE_API_KEY"
    )
    openai_compatible_reasoning_effort: str | None = Field(
        default="none", alias="OPENAI_COMPATIBLE_REASONING_EFFORT"
    )
    openai_compatible_timeout_seconds: int = Field(
        default=900, alias="OPENAI_COMPATIBLE_TIMEOUT_SECONDS"
    )
    deep_planner_base_url: str = Field(
        default="http://localhost:1240/v1", alias="DEEP_PLANNER_BASE_URL"
    )
    deep_planner_model: str = Field(
        default="minimax-m2.7", alias="DEEP_PLANNER_MODEL"
    )
    deep_planner_timeout_seconds: int = Field(
        default=900, alias="DEEP_PLANNER_TIMEOUT_SECONDS"
    )
    deep_planner_reasoning_effort: str | None = Field(
        default=None, alias="DEEP_PLANNER_REASONING_EFFORT"
    )
    vision_base_url: str = Field(
        default="http://localhost:1240/v1", alias="VISION_BASE_URL"
    )
    vision_model: str = Field(
        default="qwen3.6-35b-a3b-mtp", alias="VISION_MODEL"
    )
    vision_timeout_seconds: int = Field(
        default=60, alias="VISION_TIMEOUT_SECONDS"
    )
    vision_max_slides: int = Field(default=4, alias="VISION_MAX_SLIDES")
    vision_reasoning_effort: str | None = Field(
        default="none", alias="VISION_REASONING_EFFORT"
    )

    bedrock_validate_on_startup: bool = Field(default=False, alias="BEDROCK_VALIDATE")
    bedrock_timeout_seconds: int = Field(default=20, alias="BEDROCK_TIMEOUT_SECONDS")

    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"],
        alias="CORS_ORIGINS",
    )

    qa_max_rounds: int = Field(default=2, alias="QA_MAX_ROUNDS")
    job_worker_concurrency: int = Field(default=1, alias="JOB_WORKER_CONCURRENCY")
    # Default to the polished *native* (editable) renderer — real python-pptx
    # shapes/text reproducing the design-system look, so generated decks can be
    # tweaked in PowerPoint. `authored` / `legacy` are the older flat native
    # renderers (opt-in; they may insert icon/diagram PNGs). Any other value —
    # including the removed image-based `html` engine — resolves to `native`.
    renderer_engine: str = Field(default="native", alias="RENDERER_ENGINE")

    # Decompose deck planning into smaller LLM calls (batched for the fast
    # profile, per-slide for the deep profile) instead of one monolithic
    # deck-JSON call. Kill-switch back to the single call when False.
    planner_decompose: bool = Field(default=True, alias="PLANNER_DECOMPOSE")

    # Brand mode: when True, instantiate new slides from the uploaded template's
    # *layout library* (unbounded variety, real master/theme reuse) instead of
    # duplicating its authored slides. Default off until validated on real
    # templates; falls back to the clone path when instantiation yields nothing.
    brand_layout_instantiation: bool = Field(
        default=False, alias="BRAND_LAYOUT_INSTANTIATION"
    )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
