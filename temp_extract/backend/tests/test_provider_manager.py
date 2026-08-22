"""
Unit tests for ProviderManager: sensitivity-gated routing, retry, and
authorized-only fallback. Uses FakeProvider (defined in this test file
only) instead of real Claude/Gemini adapters -- no network, no keys
needed. FakeProvider must never be imported or used outside tests/.
"""

from __future__ import annotations

import pytest

from app.ai_providers.base import (
    AIProvider,
    Message,
    ProviderConfig,
    ProviderHealth,
    ProviderRequest,
    ProviderResponse,
    Sensitivity,
)
from app.ai_providers.exceptions import NoAuthorizedProviderError, ProviderError, ProviderTimeoutError
from app.ai_providers.manager import ProviderManager


class FakeProvider(AIProvider):
    """Test-only stand-in. `behaviors` is a list of outcomes consumed one
    per call: either a ProviderResponse to return, or an Exception to
    raise. Once exhausted, repeats the last entry."""

    def __init__(self, config: ProviderConfig, behaviors: list):
        super().__init__(config)
        self._behaviors = behaviors
        self.call_count = 0

    def _next(self):
        idx = min(self.call_count, len(self._behaviors) - 1)
        outcome = self._behaviors[idx]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        return self._next()

    async def stream(self, request: ProviderRequest):
        yield self._next().text

    async def tool_call(self, request: ProviderRequest) -> ProviderResponse:
        return self._next()

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(self.name, "ok")


def make_config(name: str, authorized: frozenset[Sensitivity], max_retries: int = 1) -> ProviderConfig:
    return ProviderConfig(
        provider_name=name,
        api_key="fake-key-not-real",
        model="fake-model",
        timeout_seconds=1.0,
        max_retries=max_retries,
        authorized_sensitivities=authorized,
    )


def make_response(provider_name: str, text: str = "ok") -> ProviderResponse:
    return ProviderResponse(
        text=text, tool_calls=[], provider_name=provider_name, model="fake-model", finish_reason="stop"
    )


def make_request(sensitivity: Sensitivity) -> ProviderRequest:
    return ProviderRequest(messages=[Message(role="user", content="hi")], sensitivity=sensitivity)


@pytest.mark.asyncio
async def test_unauthorized_sensitivity_raises():
    primary = FakeProvider(
        make_config("primary", frozenset({Sensitivity.PUBLIC})), [make_response("primary")]
    )
    manager = ProviderManager(providers={"primary": primary}, primary="primary")

    with pytest.raises(NoAuthorizedProviderError):
        await manager.complete(make_request(Sensitivity.PRIVATE))

    # Never called -- rejected before any provider call, not after a failure.
    assert primary.call_count == 0


@pytest.mark.asyncio
async def test_primary_used_when_authorized():
    primary = FakeProvider(
        make_config("primary", frozenset({Sensitivity.PUBLIC})), [make_response("primary")]
    )
    manager = ProviderManager(providers={"primary": primary}, primary="primary")

    response = await manager.complete(make_request(Sensitivity.PUBLIC))

    assert response.provider_name == "primary"
    assert primary.call_count == 1


@pytest.mark.asyncio
async def test_fallback_used_when_primary_exhausts_retries():
    primary = FakeProvider(
        make_config("primary", frozenset({Sensitivity.PUBLIC}), max_retries=1),
        [ProviderError("boom"), ProviderError("boom again")],
    )
    fallback = FakeProvider(
        make_config("fallback", frozenset({Sensitivity.PUBLIC})), [make_response("fallback")]
    )
    manager = ProviderManager(
        providers={"primary": primary, "fallback": fallback}, primary="primary", fallback="fallback"
    )

    response = await manager.complete(make_request(Sensitivity.PUBLIC))

    assert response.provider_name == "fallback"
    assert primary.call_count == 2  # 1 initial + 1 retry, then gave up
    assert fallback.call_count == 1


@pytest.mark.asyncio
async def test_fallback_skipped_when_not_authorized_for_sensitivity():
    # Fallback exists and would succeed, but isn't authorized for PRIVATE
    # data -- must NOT be used. This is the core "never silently escalate
    # to an unauthorized provider" rule.
    primary = FakeProvider(
        make_config("primary", frozenset({Sensitivity.PUBLIC, Sensitivity.PRIVATE}), max_retries=0),
        [ProviderError("boom")],
    )
    fallback = FakeProvider(
        make_config("fallback", frozenset({Sensitivity.PUBLIC})),  # NOT authorized for PRIVATE
        [make_response("fallback")],
    )
    manager = ProviderManager(
        providers={"primary": primary, "fallback": fallback}, primary="primary", fallback="fallback"
    )

    with pytest.raises(ProviderError):
        await manager.complete(make_request(Sensitivity.PRIVATE))

    assert fallback.call_count == 0  # never touched


@pytest.mark.asyncio
async def test_retries_before_giving_up():
    primary = FakeProvider(
        make_config("primary", frozenset({Sensitivity.PUBLIC}), max_retries=2),
        [ProviderTimeoutError("slow"), ProviderTimeoutError("slow"), make_response("primary")],
    )
    manager = ProviderManager(providers={"primary": primary}, primary="primary")

    response = await manager.complete(make_request(Sensitivity.PUBLIC))

    assert response.provider_name == "primary"
    assert primary.call_count == 3  # 2 failures + 1 success, within max_retries=2


@pytest.mark.asyncio
async def test_health_check_all_aggregates_results():
    primary = FakeProvider(make_config("primary", frozenset({Sensitivity.PUBLIC})), [make_response("p")])
    fallback = FakeProvider(make_config("fallback", frozenset({Sensitivity.PUBLIC})), [make_response("f")])
    manager = ProviderManager(
        providers={"primary": primary, "fallback": fallback}, primary="primary", fallback="fallback"
    )

    results = await manager.health_check_all()

    assert results["primary"].status == "ok"
    assert results["fallback"].status == "ok"
