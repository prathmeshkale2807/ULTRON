"""
Configuration for the ULTRON core service.

Everything here is loaded from environment variables (via a local .env file
during development). Nothing in this module ever hard-codes a real secret --
only field *names* and safe defaults live here. See .env.example for the
full list of variables Phase 1 understands.

Later phases will extend this with AI provider keys, voice service keys,
and Android pairing configuration -- Phase 1 only needs enough to start
the service, talk to a local database, and answer a health check.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are read from (in order of precedence): real environment
    variables, then a `.env` file in the backend/ directory, then the
    defaults below. Defaults are intentionally safe for local dev only.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App identity -----------------------------------------------------
    app_name: str = "ULTRON Core Service"
    environment: str = Field(default="development")  # development | production
    debug: bool = Field(default=True)

    # --- Networking ---------------------------------------------------------
    # Bound to localhost only in Phase 1. Remote Mode (section 34 of the
    # spec) is explicitly out of scope until its own security review.
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8756)

    # --- Database -------------------------------------------------------
    # SQLite for Phase 1, per the approved architecture. The file lives
    # under the backend's local data directory, not inside source control.
    database_url: str = Field(default="sqlite:///./data/ultron.db")

    # --- Logging ----------------------------------------------------------
    log_level: str = Field(default="INFO")
    log_dir: str = Field(default="./data/logs")

    # --- Placeholders for later phases (intentionally unused in Phase 1) --
    # Declared now so .env.example documents the full eventual surface,
    # but Phase 1 code never reads these -- no AI provider calls, no voice,
    # no Android pairing happen yet. Real values are never committed.
    anthropic_api_key: str | None = Field(default=None)
    openai_api_key: str | None = Field(default=None)
    gemini_api_key: str | None = Field(default=None)

    @property
    def data_dir(self) -> Path:
        return Path(self.log_dir).parent

    def ensure_data_dirs(self) -> None:
        """Create local data/log directories if they don't exist yet."""
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        Path(self.database_url.replace("sqlite:///", "")).parent.mkdir(
            parents=True, exist_ok=True
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor -- import and call this, don't instantiate
    Settings() directly elsewhere, so the whole app shares one config."""
    return Settings()
