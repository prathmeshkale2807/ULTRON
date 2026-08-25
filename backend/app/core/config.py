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

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

def get_default_data_dir() -> Path:
    if getattr(sys, 'frozen', False):
        appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return Path(appdata) / "ULTRON" / "data"
    return Path("./data").resolve()

def get_default_log_dir() -> str:
    if getattr(sys, 'frozen', False):
        appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return str(Path(appdata) / "ULTRON" / "logs")
    return "./data/logs"

def get_default_db_url() -> str:
    db_path = get_default_data_dir() / "ultron.db"
    return f"sqlite:///{db_path}"

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
    max_concurrent_tasks: int = Field(default=16, le=64)
    max_task_queue_size: int = Field(default=1000)
    environment: str = Field(default="development")  # development | production
    debug: bool = Field(default=True)

    # --- Phase 10: Google OAuth -------------------------------------------
    google_client_id: str = Field(default="mock-client-id")
    google_client_secret: str = Field(default="mock-client-secret")

    # --- Networking ---------------------------------------------------------
    # Bound to localhost only in Phase 1. Remote Mode (section 34 of the
    # spec) is explicitly out of scope until its own security review.
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8756)

    # --- Database -------------------------------------------------------
    # SQLite for Phase 1, per the approved architecture. The file lives
    # under the backend's local data directory, not inside source control.
    database_url: str = Field(default_factory=get_default_db_url)

    # --- Logging --------------------------------------------------------
    log_level: str = Field(default="INFO")  # DEBUG | INFO | WARNING | ERROR
    log_dir: str = Field(default_factory=get_default_log_dir)

    # --- AI providers (Phase 2) ---------------------------------------------
    # API keys: read from env/`.env` only, never hard-coded, never logged
    # (see ProviderConfig.__repr__ in app/ai_providers/base.py).
    anthropic_api_key: str | None = Field(default=None)
    gemini_api_key: str | None = Field(default=None)
    openai_api_key: str | None = Field(default=None)  # reserved; no OpenAI adapter yet

    claude_model: str = Field(default="claude-sonnet-4-5-20250929")
    gemini_model: str = Field(default="gemini-2.5-flash")

    ai_provider_timeout_seconds: float = Field(default=30.0)
    ai_provider_max_retries: int = Field(default=2)

    # Which provider is tried first, and which one (if any) is tried if the
    # primary fails -- fallback is only ever used when it's also authorized
    # for the request's sensitivity (see ProviderManager).
    ai_primary_provider: str = Field(default="claude")
    ai_fallback_provider: str | None = Field(default="gemini")

    # Authorization lists: comma-separated Sensitivity names this provider
    # may be used for, e.g. "PUBLIC,INTERNAL,SENSITIVE,PRIVATE". Defaults
    # are conservative -- SENSITIVE/PRIVATE data requires an explicit,
    # deliberate opt-in per provider, not an assumed default.
    ai_claude_authorized_sensitivities: str = Field(default="PUBLIC,INTERNAL,SENSITIVE,PRIVATE")
    ai_gemini_authorized_sensitivities: str = Field(default="PUBLIC,INTERNAL")

    # --- Browser (Phase 8) --------------------------------------------------
    # Explicitly controls whether the browser can access localhost or internal
    # IP blocks like 192.168.x.x, 10.x.x.x, etc.
    allow_local_network_browser: bool = Field(default=False)

    # --- Voice (Phase 14) ---------------------------------------------------
    voice_conversation_timeout_seconds: float = Field(default=15.0, gt=0.0)

    @property
    def data_dir(self) -> Path:
        return Path(self.log_dir).parent

    def ensure_data_dirs(self) -> None:
        """Create local data/log directories if they don't exist yet."""
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        db_dir = Path(self.database_url.replace("sqlite:///", "")).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        # Phase 27: Enforce Windows ACLs on the top-level ULTRON directory
        from app.core.acl import secure_directory_windows
        # self.data_dir is usually LOCALAPPDATA/ULTRON/data, we want LOCALAPPDATA/ULTRON
        ultron_dir = self.data_dir.parent
        if ultron_dir.name == "ULTRON":
            secure_directory_windows(ultron_dir)
        else:
            secure_directory_windows(self.data_dir)


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor -- import and call this, don't instantiate
    Settings() directly elsewhere, so the whole app shares one config."""
    return Settings()
