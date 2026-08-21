"""
Data model for a registered Tool.

Every field here is deliberately mandatory (no silent defaults for the
safety-relevant fields) -- a tool that doesn't declare its risk level,
permission category, confirmation tier, and allowed devices is not
registrable at all. That refusal is intentional: Phase 3's whole point
is that nothing gets to skip declaring how dangerous it is.

This module only defines *shape*. It never imports anything that talks
to a real device, the filesystem, or the network -- that keeps the
registry importable and testable in complete isolation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    """How dangerous a successful, correctly-used call of this tool is.

    Ordering matters -- RISK_ORDER below is used by the Safety Gate to
    compare levels (e.g. "is this tool's risk at or above HIGH?").
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class PermissionCategory(str, Enum):
    """Broad capability buckets that permissions are granted/revoked
    against. Deliberately coarse in Phase 3 -- future phases may add
    more categories, but every tool must fit in exactly one."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SYSTEM_CONTROL = "system_control"
    NETWORK = "network"
    BROWSER = "browser"
    COMMUNICATION = "communication"  # email, calendar, messaging
    DEVICE_CONTROL = "device_control"  # PC/Android input, power, etc.
    FINANCIAL = "financial"
    PC_READ = "pc_read"
    PC_PROCESS_CONTROL = "pc_process_control"
    PC_SCREEN_CAPTURE = "pc_screen_capture"
    OTHER = "other"


class ConfirmationTier(str, Enum):
    """How often a human must explicitly approve a call, independent of
    Safety Mode. A tool's OWN confirmation_tier is a floor, not a
    suggestion -- see app/safety/gate.py: ALWAYS_ASK can never be
    downgraded by any Safety Mode, including Trusted Mode."""

    AUTOMATIC = "automatic"  # never needs a human prompt, on its own
    ASK_ONCE_PER_SESSION = "ask_once_per_session"
    ALWAYS_ASK = "always_ask"  # non-overridable, every single call


class VerificationMethod(str, Enum):
    """How the executor confirms a tool's execution actually did what it
    claimed, after the call returns. Phase 3 has no real tools yet, so
    this is a declared contract -- enforcement of CALLBACK/CHECKSUM
    happens per-tool once real tools exist."""

    NONE = "none"  # no verification is possible/meaningful
    CALLBACK = "callback"  # tool provides its own verify() callable
    MANUAL = "manual"  # a human must confirm the outcome


class DeviceType(str, Enum):
    """Devices a tool call can be targeted at. Phase 3 defines the enum
    and validates against it -- no real device backend exists yet."""

    PC = "pc"
    ANDROID = "android"
    BROWSER = "browser"
    SERVER = "server"  # ULTRON's own backend/local machine
    ANY = "any"  # tool is device-agnostic (e.g. pure computation)


class RetryPolicy(BaseModel):
    """Bounded, explicit retry behavior. No infinite retries, ever --
    max_attempts is capped defensively even if a tool author forgets."""

    max_attempts: int = Field(default=1, ge=1, le=5)
    backoff_seconds: float = Field(default=0.0, ge=0.0, le=60.0)
    retry_on_timeout: bool = Field(default=False)

    @field_validator("max_attempts")
    @classmethod
    def _cap_attempts(cls, v: int) -> int:
        # Belt-and-suspenders on top of the ge/le constraint above --
        # this stays true even if the Field constraints are ever loosened
        # by a future edit that doesn't notice the safety implication.
        if v > 5:
            raise ValueError("max_attempts must not exceed 5")
        return v


# A tool handler is never a "direct call" from the AI -- it is only ever
# invoked by ToolExecutor, after the full validation pipeline. Handlers
# are plain async callables so Phase 3 test/mock tools can be simple
# functions; nothing about this type implies real device access.
ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolVerifier = Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]]


class ToolDefinition(BaseModel):
    """Full metadata contract a tool must declare to be registrable.

    `handler` and `verifier` are excluded from serialization -- they're
    Python callables, not something the desktop UI or API consumers
    should ever see or need. Everything else here is safe (and meant)
    to be exposed to the UI so a human can see exactly what a tool is
    before ever approving it.
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2000)

    # JSON Schema (draft 2020-12 subset) dicts -- validated with the
    # `jsonschema` library by the executor, not hand-rolled here.
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    risk_level: RiskLevel
    permission_category: PermissionCategory
    confirmation_tier: ConfirmationTier
    allowed_devices: list[DeviceType] = Field(min_length=1)

    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    verification_method: VerificationMethod = Field(default=VerificationMethod.NONE)

    enabled: bool = Field(default=True)

    handler: ToolHandler = Field(exclude=True)
    verifier: ToolVerifier | None = Field(default=None, exclude=True)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("tool name must not be blank")
        if v != v.strip():
            raise ValueError("tool name must not have leading/trailing whitespace")
        return v

    @field_validator("allowed_devices")
    @classmethod
    def _validate_devices(cls, v: list[DeviceType]) -> list[DeviceType]:
        if not v:
            raise ValueError("a tool must declare at least one allowed device")
        return v

    def risk_at_least(self, floor: RiskLevel) -> bool:
        return RISK_ORDER[self.risk_level] >= RISK_ORDER[floor]

    def public_metadata(self) -> dict[str, Any]:
        """Everything safe to hand to the desktop UI / API layer."""
        return self.model_dump(mode="json")
