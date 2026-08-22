"""
ProviderManager -- the single entry point the rest of ULTRON uses to talk
to an AI provider. Nothing outside app/ai_providers/ should import a
provider adapter directly.

Policy enforced here (per the approved architecture):
  1. Every request carries a Sensitivity tag.
  2. A provider is only ever used for a request if that provider is
     explicitly authorized for that sensitivity level.
  3. On primary-provider failure, fallback is attempted -- but ONLY if
     the fallback provider is also authorized for that request's
     sensitivity. A failure never silently escalates to a provider that
     isn't cleared for the data.
  4. If no authorized provider succeeds, NoAuthorizedProviderError /
     ProviderError propagates -- the caller reports failure, it never
     gets a response from an unauthorized provider instead.
"""

from __future__ import annotations

import asyncio

from app.ai_providers.base import AIProvider, ProviderHealth, ProviderRequest, ProviderResponse, Sensitivity
from app.ai_providers.exceptions import NoAuthorizedProviderError, ProviderError, ProviderTimeoutError
from app.core.logging_config import get_logger

logger = get_logger("ai_providers.manager")


class ProviderManager:
    def __init__(
        self,
        providers: dict[str, AIProvider],
        primary: str,
        fallback: str | None = None,
    ) -> None:
        if primary not in providers:
            raise ValueError(f"Primary provider '{primary}' is not registered")
        if fallback is not None and fallback not in providers:
            raise ValueError(f"Fallback provider '{fallback}' is not registered")

        self._providers = providers
        self._primary = primary
        self._fallback = fallback

    def get(self, name: str) -> AIProvider:
        return self._providers[name]

    def _authorized_chain(self, sensitivity: Sensitivity) -> list[AIProvider]:
        """Ordered list of providers eligible for this request: primary
        first, then fallback -- skipping any not authorized for this
        sensitivity level. Never includes an unauthorized provider,
        regardless of ordering."""
        chain = []
        for name in (self._primary, self._fallback):
            if name is None:
                continue
            provider = self._providers[name]
            if provider.is_authorized_for(sensitivity):
                chain.append(provider)
        return chain

    async def _call_with_retry(self, provider: AIProvider, request: ProviderRequest, use_tools: bool):
        method = provider.tool_call if use_tools else provider.generate
        last_error: Exception | None = None
        for attempt in range(provider.config.max_retries + 1):
            try:
                return await method(request)
            except ProviderTimeoutError as exc:
                last_error = exc
                logger.warning(
                    "%s timed out (attempt %d/%d)",
                    provider.name,
                    attempt + 1,
                    provider.config.max_retries + 1,
                )
            except ProviderError as exc:
                last_error = exc
                logger.warning(
                    "%s failed (attempt %d/%d): %s",
                    provider.name,
                    attempt + 1,
                    provider.config.max_retries + 1,
                    exc,
                )
            if attempt < provider.config.max_retries:
                await asyncio.sleep(0.5 * (2**attempt))  # exponential backoff
        assert last_error is not None
        raise last_error

    async def complete(self, request: ProviderRequest, use_tools: bool = False) -> ProviderResponse:
        chain = self._authorized_chain(request.sensitivity)
        if not chain:
            raise NoAuthorizedProviderError(
                f"No provider is authorized for sensitivity={request.sensitivity.name}"
            )

        last_error: Exception | None = None
        for provider in chain:
            try:
                return await self._call_with_retry(provider, request, use_tools)
            except ProviderError as exc:
                last_error = exc
                logger.warning(
                    "%s exhausted retries for this request, trying next authorized provider (if any): %s",
                    provider.name,
                    exc,
                )

        assert last_error is not None
        raise last_error

    async def health_check_all(self) -> dict[str, ProviderHealth]:
        results = await asyncio.gather(
            *(p.health_check() for p in self._providers.values()), return_exceptions=True
        )
        out: dict[str, ProviderHealth] = {}
        for name, result in zip(self._providers.keys(), results, strict=True):
            if isinstance(result, Exception):
                out[name] = ProviderHealth(name, "unreachable", str(result))
            else:
                out[name] = result
        return out
