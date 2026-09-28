"""Application settings, loaded from environment variables (or a .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM -------------------------------------------------------------
    # Any LangChain `init_chat_model` identifier, e.g.
    #   "anthropic:claude-sonnet-5", "openai:gpt-5", "google_genai:gemini-2.5-pro"
    llm_model: str = "anthropic:claude-sonnet-5"
    # Model used for vision OCR / structured extraction of scanned invoices.
    llm_vision_model: str | None = None
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192

    # --- Storage ---------------------------------------------------------
    storage_backend: Literal["s3", "local"] = "local"
    local_storage_root: Path = Path("./data/storage")
    s3_bucket: str = "accountant-maverick"
    s3_prefix: str = "workspaces"
    s3_region: str | None = None
    # Set for MinIO / R2 / other S3-compatible endpoints.
    s3_endpoint_url: str | None = None
    s3_presign_expiry_seconds: int = 3600
    max_upload_mb: int = 50

    # --- Live web (TinyFish) ---------------------------------------------
    tinyfish_api_key: str | None = None
    tinyfish_search_url: str = "https://api.search.tinyfish.ai/"
    tinyfish_fetch_url: str = "https://api.fetch.tinyfish.ai/"
    tinyfish_timeout_seconds: float = 60.0

    # --- Agent -----------------------------------------------------------
    # "memory" keeps chat threads in-process; "sqlite" persists them.
    checkpointer: Literal["memory", "sqlite"] = "sqlite"
    checkpoint_db: Path = Path("./data/checkpoints.sqlite")
    agent_recursion_limit: int = 80
    skills_dir: Path = Path(__file__).resolve().parent.parent / "skills"

    # --- API -------------------------------------------------------------
    # When set, every /api request must send `Authorization: Bearer <token>`.
    app_token: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]
    static_dir: Path = Path(__file__).resolve().parent / "static"


@lru_cache
def get_settings() -> Settings:
    # Export .env to the process environment too: provider SDKs (ANTHROPIC_API_KEY, OPENAI_API_KEY,
    # AWS_* for boto3) read os.environ, not our Settings object. Real env vars take precedence.
    from dotenv import load_dotenv

    load_dotenv(".env", override=False)
    return Settings()
