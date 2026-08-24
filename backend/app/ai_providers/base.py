"""
AIProvider interface -- the abstraction every provider adapter implements.

Design goal: the orchestrator (a later phase) and ProviderManager only ever
talk to this interface. Adding OpenAI or a local model later means writing
one new adapter class here, not touching orchestrator/manager code.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


class Sensitivity(enum.IntEnum):
    """How sensitive the data in a request is. Ordered so a provider
    authorized up to level N is authorized for every level <= N.

    PUBLIC     -- no user data, e.g. "what's 2+2"
    INTERNAL   -- ULTRON's own state (task status, device names)
    SENSITIVE  -- user content: file contents, calendar events, general text
    PRIVATE    -- explicitly private: email bodies, credentials-adjacent
                  content, anything the user has tagged private
    """

    PUBLIC = 0
    INTERNAL = 1
    SENSITIVE = 2
    PRIVATE = 3


@dataclass(frozen=True)
class ToolDefinition:
    """A tool the model may call, in provider-agnostic form. Each adapter
    translates this to its own SDK's tool-schema format."""

    name: str
    description: str
    input_schema: dict  # JSON Schema


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation the model requested, normalized across providers."""

    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ContentPart:
    """A single piece of multimodal content. type is 'text' or 'image'."""
    type: str
    text: str | None = None
    mime_type: str | None = None
    data: bytes | None = None
    
    def __repr__(self) -> str:
        # Crucial Security Constraint: Never log raw image bytes or base64
        # to prevent leaking sensitive screenshot data into system logs.
        if self.type == "image":
            data_len = len(self.data) if self.data else 0
            return f"ContentPart(type='image', mime_type={self.mime_type!r}, data_bytes={data_len})"
        return f"ContentPart(type='text', text={self.text!r})"

@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant" | "system"
    content: str | list[ContentPart]


@dataclass(frozen=True)
class ProviderRequest:
    messages: list[Message]
    sensitivity: Sensitivity
    tools: list[ToolDefinition] = field(default_factory=list)
    max_tokens: int = 1024
    system_prompt: str | None = None


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    tool_calls: list[ToolCall]
    provider_name: str
    model: str
    finish_reason: str
    raw: dict = field(default_factory=dict)  # provider-native response, for debugging only


@dataclass(frozen=True)
class ProviderHealth:
    provider_name: str
    status: str  # "ok" | "unauthenticated" | "unreachable" | "not_configured"
    detail: str = ""


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for one provider instance. `api_key` is read from an
    environment variable at construction time (see app.core.config) and is
    never written to a log, a __repr__, or the database. Dataclass fields
    are otherwise plain -- the secrecy discipline is "never pass this to
    logger.*()", enforced by code review / grep in CI, not by a special
    wrapper type (kept simple for Phase 2's scope)."""

    provider_name: str
    api_key: str | None
    model: str
    timeout_seconds: float = 30.0
    max_retries: int = 2
    authorized_sensitivities: frozenset[Sensitivity] = field(
        default_factory=lambda: frozenset({Sensitivity.PUBLIC})
    )

    def __repr__(self) -> str:
        # Explicit override so accidental logging (str(config), f"{config}")
        # can never leak the key, even if someone forgets api_key exists.
        return (
            f"ProviderConfig(provider_name={self.provider_name!r}, "
            f"model={self.model!r}, api_key=***REDACTED***, "
            f"timeout_seconds={self.timeout_seconds}, "
            f"authorized_sensitivities={sorted(s.name for s in self.authorized_sensitivities)})"
        )


class AIProvider(ABC):
    """Every adapter (Gemini, Claude, later OpenAI/local) implements this."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.provider_name

    def is_authorized_for(self, sensitivity: Sensitivity) -> bool:
        return sensitivity in self.config.authorized_sensitivities

    @abstractmethod
    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        """Single-shot completion."""

    @abstractmethod
    def stream(self, request: ProviderRequest) -> AsyncIterator[str]:
        """Streaming completion -- yields text chunks as they arrive."""

    @abstractmethod
    async def tool_call(self, request: ProviderRequest) -> ProviderResponse:
        """Completion that may include structured tool calls. Separate
        from generate() because providers often need a distinct code path
        (different SDK method / response shape) for tool use; callers that
        don't care about tools just use generate()."""

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Cheap, real call that proves the API key + network path work.
        Never returns "ok" without actually making a request."""
