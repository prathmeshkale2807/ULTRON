"""Anthropic Claude adapter. Only this file imports the `anthropic` SDK --
nothing else in the codebase should, so swapping/upgrading the SDK stays
isolated here."""

from __future__ import annotations

import asyncio

import anthropic

from app.ai_providers.base import (
    AIProvider,
    ProviderHealth,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)
from app.ai_providers.exceptions import ProviderError, ProviderTimeoutError
from app.core.logging_config import get_logger

logger = get_logger("ai_providers.claude")


class ClaudeProvider(AIProvider):
    def __init__(self, config):
        super().__init__(config)
        # Do not construct the SDK client without credentials. Some SDK
        # versions raise during construction, which would make health checks
        # fail instead of reporting the honest `not_configured` state.
        self._client = (
            anthropic.AsyncAnthropic(
                api_key=config.api_key,
                timeout=config.timeout_seconds,
            )
            if config.api_key
            else None
        )

    @property
    def client(self):
        if self._client is None:
            raise ProviderError("Claude API key is not configured")
        return self._client

    def _to_anthropic_messages(self, request: ProviderRequest) -> list[dict]:
        import base64
        msgs = []
        for m in request.messages:
            if m.role == "system":
                continue
                
            if isinstance(m.content, str):
                msgs.append({"role": m.role, "content": m.content})
            else:
                parts = []
                for cp in m.content:
                    if cp.type == "text":
                        parts.append({"type": "text", "text": cp.text})
                    elif cp.type == "image":
                        b64 = base64.b64encode(cp.data).decode("utf-8")
                        parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": cp.mime_type,
                                "data": b64
                            }
                        })
                msgs.append({"role": m.role, "content": parts})
        return msgs

    def _to_anthropic_tools(self, request: ProviderRequest) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in request.tools
        ]

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        try:
            response = await asyncio.wait_for(
                self.client.messages.create(
                    model=self.config.model,
                    max_tokens=request.max_tokens,
                    system=request.system_prompt or anthropic.NOT_GIVEN,
                    messages=self._to_anthropic_messages(request),
                ),
                timeout=self.config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"Claude request exceeded {self.config.timeout_seconds}s") from exc
        except anthropic.APIError as exc:
            raise ProviderError(f"Claude API error: {exc.__class__.__name__}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        return ProviderResponse(
            text=text,
            tool_calls=[],
            provider_name=self.name,
            model=response.model,
            finish_reason=response.stop_reason or "unknown",
            raw={"id": response.id},
        )

    async def stream(self, request: ProviderRequest):
        try:
            async with self.client.messages.stream(
                model=self.config.model,
                max_tokens=request.max_tokens,
                system=request.system_prompt or anthropic.NOT_GIVEN,
                messages=self._to_anthropic_messages(request),
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.APIError as exc:
            raise ProviderError(f"Claude streaming error: {exc.__class__.__name__}") from exc

    async def tool_call(self, request: ProviderRequest) -> ProviderResponse:
        try:
            response = await asyncio.wait_for(
                self.client.messages.create(
                    model=self.config.model,
                    max_tokens=request.max_tokens,
                    system=request.system_prompt or anthropic.NOT_GIVEN,
                    messages=self._to_anthropic_messages(request),
                    tools=self._to_anthropic_tools(request),
                ),
                timeout=self.config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"Claude request exceeded {self.config.timeout_seconds}s") from exc
        except anthropic.APIError as exc:
            raise ProviderError(f"Claude API error: {exc.__class__.__name__}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        tool_calls = [
            ToolCall(id=block.id, name=block.name, arguments=block.input)
            for block in response.content
            if block.type == "tool_use"
        ]
        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            provider_name=self.name,
            model=response.model,
            finish_reason=response.stop_reason or "unknown",
            raw={"id": response.id},
        )

    async def health_check(self) -> ProviderHealth:
        if not self.config.api_key:
            return ProviderHealth(self.name, "not_configured", "No API key set")
        try:
            await asyncio.wait_for(
                self.client.messages.create(
                    model=self.config.model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                ),
                timeout=self.config.timeout_seconds,
            )
            return ProviderHealth(self.name, "ok")
        except anthropic.AuthenticationError:
            return ProviderHealth(self.name, "unauthenticated", "API key rejected")
        except (TimeoutError, anthropic.APIConnectionError) as exc:
            return ProviderHealth(self.name, "unreachable", str(exc.__class__.__name__))
        except anthropic.APIError as exc:
            return ProviderHealth(self.name, "unreachable", str(exc.__class__.__name__))
