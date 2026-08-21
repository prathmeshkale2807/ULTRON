"""Tool Registry -- Phase 3.

Every capability ULTRON can ever perform (PC control, Android control,
browser, email, calendar, file access, etc.) is required to exist as a
registered Tool with a full metadata contract before anything is allowed
to call it. Nothing in this package executes a tool -- that is the
ToolExecutor's job (see app/executor/). This package only defines *what
a tool is* and *where tools are looked up*.
"""

from app.tools.models import (
    ConfirmationTier,
    DeviceType,
    PermissionCategory,
    RetryPolicy,
    RiskLevel,
    ToolDefinition,
    VerificationMethod,
)
from app.tools.registry import ToolRegistry, get_registry

__all__ = [
    "ConfirmationTier",
    "DeviceType",
    "PermissionCategory",
    "RetryPolicy",
    "RiskLevel",
    "ToolDefinition",
    "VerificationMethod",
    "ToolRegistry",
    "get_registry",
]
