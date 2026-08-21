"""Tool Execution Boundary -- Phase 3.

ToolExecutor is the ONLY code path in ULTRON permitted to call a tool's
handler. The AI/orchestrator layer never holds a callable -- it can only
ask ToolExecutor.execute(tool_name, arguments, ...), which runs the full
pipeline (schema -> risk -> device -> permission -> confirmation ->
execution -> verification) and writes exactly one audit log row per
call, regardless of where in the pipeline it stopped.
"""

from app.executor.confirmation import ConfirmationBroker, ConfirmationRequest, ConfirmationStatus
from app.executor.executor import (
    ConfirmationDeniedError,
    ConfirmationTimeoutError,
    DeviceValidationError,
    EmergencyStopEngagedError,
    PermissionDeniedError,
    RiskRejectedError,
    SchemaValidationError,
    ToolDisabledError,
    ToolExecutionResult,
    ToolExecutor,
    ToolNotFoundError,
    ToolTimeoutError,
)

__all__ = [
    "ConfirmationBroker",
    "ConfirmationRequest",
    "ConfirmationStatus",
    "ConfirmationDeniedError",
    "ConfirmationTimeoutError",
    "DeviceValidationError",
    "EmergencyStopEngagedError",
    "PermissionDeniedError",
    "RiskRejectedError",
    "SchemaValidationError",
    "ToolDisabledError",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolNotFoundError",
    "ToolTimeoutError",
]
