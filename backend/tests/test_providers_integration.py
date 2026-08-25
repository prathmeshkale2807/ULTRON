"""
Integration tests: real calls to Claude and Gemini. Each test is skipped
automatically if its provider's API key isn't set in the environment --
these never run against fakes and never run "successfully" without a
real credential actually being exercised.

Run locally with a key set, e.g. (PowerShell):
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    pytest tests/test_providers_integration.py -v
"""

from __future__ import annotations

import os

import pytest

from app.ai_providers.base import Message, ProviderConfig, ProviderRequest, Sensitivity
from app.ai_providers.claude_provider import ClaudeProvider
from app.ai_providers.gemini_provider import GeminiProvider

requires_anthropic_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
requires_gemini_key = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set"
)


@requires_anthropic_key
async def test_claude_generate_real_call():
    config = ProviderConfig(
        provider_name="claude",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model="claude-sonnet-4-5-20250929",
        authorized_sensitivities=frozenset({Sensitivity.PUBLIC}),
    )
    provider = ClaudeProvider(config)
    request = ProviderRequest(
        messages=[Message(role="user", content="Reply with exactly one word: hello")],
        sensitivity=Sensitivity.PUBLIC,
        max_tokens=10,
    )

    response = await provider.generate(request)

    assert response.text.strip() != ""
    assert response.provider_name == "claude"


@requires_anthropic_key
async def test_claude_health_check_real():
    config = ProviderConfig(
        provider_name="claude",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model="claude-sonnet-4-5-20250929",
    )
    health = await ClaudeProvider(config).health_check()
    assert health.status == "ok"


@requires_anthropic_key
async def test_claude_health_check_rejects_bad_key():
    config = ProviderConfig(
        provider_name="claude",
        api_key="sk-ant-invalid-deliberately-wrong-00000000",
        model="claude-sonnet-4-5-20250929",
    )
    health = await ClaudeProvider(config).health_check()
    assert health.status == "unauthenticated"


@requires_gemini_key
async def test_gemini_generate_real_call():
    config = ProviderConfig(
        provider_name="gemini",
        api_key=os.environ["GEMINI_API_KEY"],
        model="gemini-3.6-flash",
        authorized_sensitivities=frozenset({Sensitivity.PUBLIC}),
    )
    provider = GeminiProvider(config)
    request = ProviderRequest(
        messages=[Message(role="user", content="Hello")],
        sensitivity=Sensitivity.PUBLIC,
        max_tokens=500,
    )

    response = await provider.generate(request)

    assert response.text.strip() != ""
    assert response.provider_name == "gemini"


@requires_gemini_key
async def test_gemini_health_check_real():
    config = ProviderConfig(
        provider_name="gemini", api_key=os.environ["GEMINI_API_KEY"], model="gemini-3.6-flash"
    )
    health = await GeminiProvider(config).health_check()
    assert health.status == "ok"
