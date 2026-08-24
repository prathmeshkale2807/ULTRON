"""Google Gemini adapter. Only this file imports the `google.genai` SDK."""

from __future__ import annotations

import asyncio

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.ai_providers.base import (
    AIProvider,
    ProviderHealth,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)
from app.ai_providers.exceptions import ProviderError, ProviderTimeoutError
from app.core.logging_config import get_logger

logger = get_logger("ai_providers.gemini")


class GeminiProvider(AIProvider):
    def __init__(self, config):
        super().__init__(config)
        # The Google SDK can raise immediately when no API key is supplied.
        # Keep the provider constructible so health checks can honestly
        # report `not_configured` instead of dropping the provider.
        self._client = genai.Client(api_key=config.api_key) if config.api_key else None

    @property
    def client(self):
        if self._client is None:
            raise ProviderError("Gemini API key is not configured")
        return self._client

    def _to_contents(self, request: ProviderRequest) -> list[dict]:
        role_map = {"user": "user", "assistant": "model"}
        contents = []
        for m in request.messages:
            if m.role == "system":
                continue
            
            parts = []
            if isinstance(m.content, str):
                parts.append({"text": m.content})
            else:
                for cp in m.content:
                    if cp.type == "text":
                        parts.append({"text": cp.text})
                    elif cp.type == "image":
                        parts.append({
                            "inline_data": {
                                "mime_type": cp.mime_type,
                                "data": cp.data
                            }
                        })
            
            contents.append({"role": role_map.get(m.role, "user"), "parts": parts})
        return contents

    def _to_gemini_tools(self, request: ProviderRequest) -> list[genai_types.Tool] | None:
        if not request.tools:
            return None
        return [
            genai_types.Tool(
                function_declarations=[
                    genai_types.FunctionDeclaration(
                        name=t.name, description=t.description, parameters=t.input_schema
                    )
                    for t in request.tools
                ]
            )
        ]

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        config = genai_types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            max_output_tokens=request.max_tokens,
        )
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.config.model,
                    contents=self._to_contents(request),
                    config=config,
                ),
                timeout=self.config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"Gemini request exceeded {self.config.timeout_seconds}s") from exc
        except genai_errors.APIError as exc:
            raise ProviderError(f"Gemini API error: {exc.__class__.__name__}") from exc

        return ProviderResponse(
            text=response.text or "",
            tool_calls=[],
            provider_name=self.name,
            model=self.config.model,
            finish_reason=str(getattr(response.candidates[0], "finish_reason", "unknown"))
            if response.candidates
            else "unknown",
        )

    async def stream(self, request: ProviderRequest):
        config = genai_types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            max_output_tokens=request.max_tokens,
        )
        try:
            async for chunk in await self.client.aio.models.generate_content_stream(
                model=self.config.model,
                contents=self._to_contents(request),
                config=config,
            ):
                if chunk.text:
                    yield chunk.text
        except genai_errors.APIError as exc:
            raise ProviderError(f"Gemini streaming error: {exc.__class__.__name__}") from exc

    async def tool_call(self, request: ProviderRequest) -> ProviderResponse:
        config = genai_types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            max_output_tokens=request.max_tokens,
            tools=self._to_gemini_tools(request),
        )
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.config.model,
                    contents=self._to_contents(request),
                    config=config,
                ),
                timeout=self.config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"Gemini request exceeded {self.config.timeout_seconds}s") from exc
        except genai_errors.APIError as exc:
            raise ProviderError(f"Gemini API error: {exc.__class__.__name__}") from exc

        tool_calls = []
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    tool_calls.append(
                        ToolCall(
                            id=part.function_call.id or part.function_call.name,
                            name=part.function_call.name,
                            arguments=dict(part.function_call.args or {}),
                        )
                    )

        return ProviderResponse(
            text=response.text or "",
            tool_calls=tool_calls,
            provider_name=self.name,
            model=self.config.model,
            finish_reason=str(getattr(response.candidates[0], "finish_reason", "unknown"))
            if response.candidates
            else "unknown",
        )

    async def health_check(self) -> ProviderHealth:
        if not self.config.api_key:
            return ProviderHealth(self.name, "not_configured", "No API key set")
        try:
            await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.config.model,
                    contents=[{"role": "user", "parts": [{"text": "ping"}]}],
                    config=genai_types.GenerateContentConfig(max_output_tokens=1),
                ),
                timeout=self.config.timeout_seconds,
            )
            return ProviderHealth(self.name, "ok")
        except genai_errors.ClientError as exc:
            status = getattr(exc, "code", None)
            if status == 401 or status == 403:
                return ProviderHealth(self.name, "unauthenticated", "API key rejected")
            return ProviderHealth(self.name, "unreachable", str(exc.__class__.__name__))
        except (TimeoutError, genai_errors.APIError) as exc:
            return ProviderHealth(self.name, "unreachable", str(exc.__class__.__name__))
