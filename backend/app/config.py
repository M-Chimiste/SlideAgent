from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # AWS / Bedrock
    bedrock_region: str = "us-east-1"
    aws_profile: str = ""
    sonnet_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    haiku_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    # Storage & jobs
    sqlite_path: str = ".data/jobs.db"
    max_job_ttl_hours: int = 24
    templates_dir: str = "templates"
    staging_dir: str = ".data/staging"
    outputs_dir: str = ".data/outputs"

    log_level: str = "INFO"
