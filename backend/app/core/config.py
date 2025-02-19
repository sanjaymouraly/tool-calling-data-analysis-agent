"""Centralised application configuration.

All runtime knobs live here so that deployment behaviour is auditable from a
single place.  Values may be overridden with environment variables (or a
``.env`` file) using the exact same names, e.g. ``MAX_UPLOAD_SIZE_MB=100``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Runtime settings.

    ``extra="ignore"`` keeps deployment environments from crashing the app
    because of unrelated variables that happen to be present.
    """

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", str(REPO_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application identity -------------------------------------------------
    app_name: str = "Tool-Calling Data Analysis Agent"
    app_slug: str = "tool-using-data-analyst"
    version: str = "1.0.0"
    environment: Literal["local", "docker", "production", "test"] = "local"
    debug: bool = False

    # --- storage --------------------------------------------------------------
    data_dir: Path = Field(default=REPO_ROOT / "data")
    upload_dir: Path = Field(default=REPO_ROOT / "data" / "uploads")
    artifact_dir: Path = Field(default=REPO_ROOT / "data" / "artifacts")
    demo_dir: Path = Field(default=REPO_ROOT / "data" / "demo")
    export_dir: Path = Field(default=REPO_ROOT / "data" / "exports")
    database_url: str = ""

    # --- limits ---------------------------------------------------------------
    max_upload_size_mb: int = Field(default=50, ge=1, le=2048)
    max_rows_ingested: int = Field(default=1_000_000, ge=1)
    max_preview_rows: int = Field(default=200, ge=1, le=5000)
    max_tool_result_rows: int = Field(default=2000, ge=1)
    max_tool_result_bytes: int = Field(default=512_000, ge=1024)
    max_tool_rounds: int = Field(default=8, ge=1, le=32)
    tool_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    max_filters: int = Field(default=20, ge=1, le=100)
    max_group_keys: int = Field(default=4, ge=1, le=10)
    max_metrics: int = Field(default=12, ge=1, le=50)
    max_datasets_per_request: int = Field(default=4, ge=1, le=10)

    # --- agent budgets --------------------------------------------------------
    max_llm_calls_per_request: int = Field(default=6, ge=1, le=32)
    max_prompt_chars: int = Field(default=24_000, ge=500)
    request_token_budget: int = Field(default=120_000, ge=1000)
    request_cost_budget_usd: float = Field(default=0.50, ge=0.0, le=100.0)

    # --- security -------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    allow_credentialed_cors: bool = False
    secret_key: str = ""
    encrypt_provider_keys: bool = True

    # --- providers ------------------------------------------------------------
    default_provider: str = "free"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-3-5-sonnet-latest"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"
    custom_api_key: str = ""
    custom_base_url: str = ""
    custom_model: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:1b"
    ollama_timeout_seconds: float = Field(default=120.0, gt=0, le=600)

    # --- behaviour ------------------------------------------------------------
    seed_demo_data_on_startup: bool = True
    redact_cell_samples: bool = True
    log_level: str = "INFO"

    @field_validator("data_dir", "upload_dir", "artifact_dir", "demo_dir", "export_dir", mode="before")
    @classmethod
    def _expand(cls, v: str | Path) -> Path:
        return Path(str(v)).expanduser().resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'app.db'}"

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.artifact_dir, self.demo_dir, self.export_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


settings = get_settings()
