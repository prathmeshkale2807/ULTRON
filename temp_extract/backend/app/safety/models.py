"""
Safety Mode + Gate decision shapes.

These models carry no behavior -- the decision logic lives in
app/safety/gate.py so it can be unit-tested against these plain data
shapes without needing a database, an executor, or a running app.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.tools.models import ConfirmationTier, PermissionCategory, RiskLevel


class SafetyMode(str, Enum):
    """The four modes required by the spec.

    SAFE       -- everything requires explicit confirmation, every time.
    BALANCED   -- default. Follows each tool's own confirmation_tier.
    TRUSTED    -- most things auto-run, but CRITICAL risk and any tool
                  marked ALWAYS_ASK still always require confirmation.
                  Trusted Mode narrows *what gets asked*, never *what
                  gets bypassed at the ALWAYS_ASK/CRITICAL floor*.
    CUSTOM     -- foundation only in Phase 3: a per-category override
                  map supplied by the caller, still bounded by the same
                  ALWAYS_ASK/CRITICAL floor as every other mode.
    """

    SAFE = "safe"
    BALANCED = "balanced"
    TRUSTED = "trusted"
    CUSTOM = "custom"


class GateAction(str, Enum):
    ALLOW = "allow"  # proceed straight to execution
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"  # explicit, terminal denial -- not a prompt


class GateDecision(BaseModel):
    action: GateAction
    reason: str
    risk_level: RiskLevel
    permission_category: PermissionCategory
    confirmation_tier: ConfirmationTier
    # True when this decision was forced by a floor that no mode or
    # permission grant is allowed to override (ALWAYS_ASK tier, or
    # CRITICAL risk in Trusted/Custom mode). Surfaced so audit logs and
    # tests can distinguish "chose to ask" from "was never allowed not
    # to ask".
    non_overridable: bool = Field(default=False)
