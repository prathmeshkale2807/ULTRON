"""Builds the real ProviderManager from app settings. This is the only
place adapter classes are instantiated with real config -- keeps
construction/env concerns out of manager.py itself."""

from __future__ import annotations

from functools import lru_cache

from app.ai_providers.base import ProviderConfig, Sensitivity
from app.ai_providers.claude_provider import ClaudeProvider
from app.ai_providers.gemini_provider import GeminiProvider
from app.ai_providers.manager import ProviderManager
from app.core.config import Settings, get_settings


def _parse_sensitivities(csv: str) -> frozenset[Sensitivity]:
    return frozenset(Sensitivity[name.strip().upper()] for name in csv.split(",") if name.strip())


def build_provider_manager(settings: Settings | None = None) -> ProviderManager:
    settings = settings or get_settings()

    claude_config = ProviderConfig(
        provider_name="claude",
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
        timeout_seconds=settings.ai_provider_timeout_seconds,
        max_retries=settings.ai_provider_max_retries,
        authorized_sensitivities=_parse_sensitivities(settings.ai_claude_authorized_sensitivities),
    )
    gemini_config = ProviderConfig(
        provider_name="gemini",
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.ai_provider_timeout_seconds,
        max_retries=settings.ai_provider_max_retries,
        authorized_sensitivities=_parse_sensitivities(settings.ai_gemini_authorized_sensitivities),
    )

    providers = {
        "claude": ClaudeProvider(claude_config),
        "gemini": GeminiProvider(gemini_config),
    }

    fallback = settings.ai_fallback_provider or None

    return ProviderManager(
        providers=providers,
        primary=settings.ai_primary_provider,
        fallback=fallback,
    )


@lru_cache
def get_provider_manager() -> ProviderManager:
    """Cached accessor, mirroring get_settings(). Tests that need a fresh
    manager (different config) should call build_provider_manager()
    directly instead of this cached accessor."""
    return build_provider_manager()
