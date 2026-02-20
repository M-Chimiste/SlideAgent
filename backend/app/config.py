from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    bedrock_validate_on_startup: bool = Field(default=True, alias="BEDROCK_VALIDATE")
    bedrock_timeout_seconds: int = Field(default=20, alias="BEDROCK_TIMEOUT_SECONDS")

    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"],
        alias="CORS_ORIGINS",
    )

    qa_max_rounds: int = Field(default=2, alias="QA_MAX_ROUNDS")
    job_worker_concurrency: int = Field(default=1, alias="JOB_WORKER_CONCURRENCY")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
