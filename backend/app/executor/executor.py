"""
Tool Execution Boundary.

Pipeline, exactly as specified:

    Tool Request
    -> schema validation
    -> risk validation
    -> device validation
    -> permission validation
    -> confirmation if required
    -> execution
    -> verification

Every call -- whether it succeeds, is rejected at any stage, or errors
out -- produces exactly one AuditLogEntry row. The AI/orchestrator layer
never gets a handle to a tool's handler; this class is the only thing
that ever calls `tool.handler(...)`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import jsonschema
from sqlalchemy.orm import Session

from app.audit.log import AuditLogger
from app.core.logging_config import get_logger
from app.emergency.stop import EmergencyStop
from app.executor.confirmation import ConfirmationBroker, ConfirmationStatus
from app.permissions.models import PermissionScope, PermissionStatus
from app.permissions.store import PermissionStore
from app.safety.gate import SafetyGate
from app.safety.models import GateAction, SafetyMode
from app.tools.models import ConfirmationTier, DeviceType, RiskLevel, ToolDefinition
from app.tools.registry import ToolNotFoundError as RegistryToolNotFoundError
from app.tools.registry import ToolRegistry

logger = get_logger("executor")

# --- Exceptions, one per rejection stage -------------------------------


class ToolExecutionError(Exception):
    """Base class for every rejection the executor can produce."""


class ToolNotFoundError(ToolExecutionError):
    pass


class ToolDisabledError(ToolExecutionError):
    pass


class SchemaValidationError(ToolExecutionError):
    pass


class OutputSchemaValidationError(ToolExecutionError):
    pass


class RiskRejectedError(ToolExecutionError):
    pass


class DeviceValidationError(ToolExecutionError):
    pass


class PermissionDeniedError(ToolExecutionError):
    pass


class ConfirmationDeniedError(ToolExecutionError):
    pass


class ConfirmationTimeoutError(ToolExecutionError):
    pass


class EmergencyStopEngagedError(ToolExecutionError):
    pass


class ToolTimeoutError(ToolExecutionError):
    pass


class ToolExecutionResult:
    """Plain result object (not a pydantic model, deliberately -- output
    can contain arbitrary tool-defined data that shouldn't be forced
    through strict validation on the way *out*)."""

    def __init__(
        self,
        *,
        success: bool,
        stage: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        audit_id: int | None = None,
        confirmation_id: str | None = None,
    ) -> None:
        self.success = success
        self.stage = stage
        self.output = output
        self.error = error
        self.audit_id = audit_id
        self.confirmation_id = confirmation_id

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return (
            f"ToolExecutionResult(success={self.success}, stage={self.stage!r}, "
            f"error={self.error!r})"
        )


# Process-wide tracker for "ask once per session" confirmations, shared
# the same way the default session permission store is (see
# app/permissions/store.py) -- a confirmation given once in a session
# must be visible to every subsequent call in that session, regardless
# of which request/DB-session object handles it.
_default_session_confirmations: dict[str, set[str]] = {}


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        db: Session,
        mode: SafetyMode = SafetyMode.BALANCED,
        gate: SafetyGate | None = None,
        confirmation_broker: ConfirmationBroker | None = None,
        blocked_risk_levels: set[RiskLevel] | None = None,
        session_confirmations: dict[str, set[str]] | None = None,
    ) -> None:
        self.registry = registry
        self.db = db
        self.mode = mode
        self.gate = gate or SafetyGate()
        self.confirmation_broker = confirmation_broker or ConfirmationBroker()
        self.permission_store = PermissionStore(db)
        self.audit_logger = AuditLogger(db)
        self.emergency_stop = EmergencyStop(db)
        # Risk levels this executor instance refuses to run at all, no
        # matter the mode or confirmation outcome. Empty by default --
        # this is a policy knob for future phases/deployments, not a
        # Phase 3 default restriction.
        self.blocked_risk_levels = blocked_risk_levels or set()
        self._session_confirmations = (
            session_confirmations
            if session_confirmations is not None
            else _default_session_confirmations
        )

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        target_device: DeviceType,
        session_id: str | None = None,
        principal_id: str | None = None,
        task_id: str | None = None,
        requested_action: str | None = None,
        confirmation_callback: Any = None,
        confirmation_timeout_seconds: float = 120.0,
    ) -> ToolExecutionResult:
        if principal_id is None:
            raise ValueError("principal_id must be explicitly provided.")
        """confirmation_callback, if given, is a callable (sync or async)
        taking the ConfirmationRequest and returning bool -- used by
        tests and fully-automated policies. Without it, a required
        confirmation is created and this call awaits out-of-band
        resolution via self.confirmation_broker.resolve(...)."""

        action_label = requested_action or f"{tool_name}({target_device.value})"

        permission_result = "not_reached"
        confirmation_result = "not_reached"
        execution_result = "not_reached"
        verification_result = "not_reached"
        risk_level_str = "unknown"
        confirmation_id: str | None = None

        def _audit(detail: Any = "") -> None:
            self.audit_logger.record(
                requested_action=action_label,
                tool_name=tool_name,
                risk_level=risk_level_str,
                permission_result=permission_result,
                confirmation_result=confirmation_result,
                execution_result=execution_result,
                verification_result=verification_result,
                detail=detail,
            )

        # --- Stage 0: emergency stop -------------------------------------
        if self.emergency_stop.is_engaged():
            execution_result = "blocked_emergency_stop"
            _audit("emergency stop is engaged; no new tool execution is permitted")
            raise EmergencyStopEngagedError(
                "emergency stop is engaged; no new tool execution is permitted"
            )

        # --- Stage: resolve tool / reject unknown tools --------------------
        try:
            tool = self.registry.get(tool_name)
        except RegistryToolNotFoundError as exc:
            execution_result = "rejected_unknown_tool"
            _audit(str(exc))
            raise ToolNotFoundError(str(exc)) from exc

        risk_level_str = tool.risk_level.value

        if not tool.enabled:
            execution_result = "rejected_tool_disabled"
            _audit(f"tool '{tool_name}' is disabled")
            raise ToolDisabledError(f"tool '{tool_name}' is disabled")

        # --- Stage 1: schema validation -------------------------------------
        try:
            jsonschema.validate(instance=arguments, schema=tool.input_schema)
        except jsonschema.exceptions.SchemaError as exc:
            execution_result = "rejected_invalid_tool_schema"
            _audit(f"tool '{tool_name}' has an invalid input_schema ({type(exc).__name__})")
            raise SchemaValidationError(f"tool '{tool_name}' has an invalid schema") from exc
        except jsonschema.exceptions.ValidationError as exc:
            execution_result = "rejected_malformed_arguments"
            _audit(f"argument validation failed ({type(exc).__name__})")
            raise SchemaValidationError(f"argument validation failed: {exc.message}") from exc

        # --- Stage 2: risk validation -----------------------------------
        if tool.risk_level in self.blocked_risk_levels:
            execution_result = "rejected_risk_blocked"
            _audit(f"risk level '{tool.risk_level.value}' is blocked for this executor")
            raise RiskRejectedError(
                f"risk level '{tool.risk_level.value}' is blocked for this executor"
            )

        # --- Stage 3: device validation -----------------------------------
        if (
            target_device not in tool.allowed_devices
            and DeviceType.ANY not in tool.allowed_devices
        ):
            execution_result = "rejected_unauthorized_device"
            _audit(
                f"tool '{tool_name}' is not allowed on device '{target_device.value}' "
                f"(allowed: {[d.value for d in tool.allowed_devices]})"
            )
            raise DeviceValidationError(
                f"tool '{tool_name}' is not allowed on device '{target_device.value}'"
            )

        if target_device == DeviceType.ANDROID:
            # Phase 11: verify the requested device exists and is owned by principal
            target_device_id = arguments.get("target_device_id")
            if not target_device_id:
                execution_result = "rejected_unauthorized_device"
                _audit("Android execution requires 'target_device_id' argument")
                raise DeviceValidationError("Android execution requires 'target_device_id' argument")
                
            from app.core.database import DeviceRecord
            device_record = self.db.get(DeviceRecord, target_device_id)
            if not device_record or device_record.principal_id != principal_id:
                execution_result = "rejected_unauthorized_device"
                _audit("Android device not found or ownership mismatch")
                raise DeviceValidationError("Android device not found or ownership mismatch")
            if device_record.status == "REVOKED":
                execution_result = "rejected_unauthorized_device"
                _audit("Android device is revoked")
                raise DeviceValidationError("Android device is revoked")

        # --- Stage 4: permission validation -------------------------------
        # Opt-in model: a permission category must have been EXPLICITLY
        # granted (session or persistent) before a tool in that category
        # may run at all. UNSET ("never asked") and DENIED ("explicitly
        # revoked") are both rejections here -- they're just different
        # reasons, both visible in the audit log's permission_result.
        permission_status = self.permission_store.check(
            tool.permission_category,
            session_id=session_id,
            tool_name=tool.name,
            device=target_device,
        )
        permission_result = permission_status.value

        if permission_status == PermissionStatus.DENIED:
            execution_result = "rejected_permission_denied"
            confirmation_result = "not_required"
            reason = (
                f"permission for category '{tool.permission_category.value}' "
                "has been explicitly denied/revoked"
            )
            _audit(reason)
            raise PermissionDeniedError(reason)

        if permission_status == PermissionStatus.UNSET:
            execution_result = "rejected_missing_permission"
            confirmation_result = "not_required"
            reason = (
                f"permission for category '{tool.permission_category.value}' "
                "has never been granted"
            )
            _audit(reason)
            raise PermissionDeniedError(reason)

        # permission_status == GRANTED past this point.
        confirmed_key = f"{session_id}|{tool_name}"
        already_confirmed_this_session = bool(
            session_id
            and confirmed_key in self._session_confirmations.get(session_id, set())
        )

        decision = self.gate.evaluate(
            tool,
            self.mode,
            permission_denied=False,
            already_confirmed_this_session=already_confirmed_this_session,
        )

        if decision.action == GateAction.DENY:
            # Reachable only if a future mode/override introduces another
            # denial path in the gate -- permission denial itself is
            # already handled above, before the gate is ever consulted.
            execution_result = "rejected_by_safety_gate"
            confirmation_result = "not_required"
            _audit(decision.reason)
            raise PermissionDeniedError(decision.reason)

        # --- Stage 5: confirmation if required ------------------------------
        if decision.action == GateAction.REQUIRE_CONFIRMATION:
            request = self.confirmation_broker.create(
                tool_name=tool.name,
                target_device=target_device,
                action=action_label,
                reason=decision.reason,
                important_consequence=(
                    f"This will run '{tool.name}' on {target_device.value} "
                    f"(risk: {tool.risk_level.value})."
                ),
                risk=tool.risk_level,
            )
            confirmation_id = request.id

            approved = await self._resolve_confirmation(
                request, confirmation_callback, confirmation_timeout_seconds
            )

            resolved = self.confirmation_broker.get(request.id)
            status = resolved.status if resolved else ConfirmationStatus.TIMED_OUT
            confirmation_result = status.value

            if status == ConfirmationStatus.TIMED_OUT:
                execution_result = "rejected_confirmation_timeout"
                _audit("confirmation request timed out")
                raise ConfirmationTimeoutError("confirmation request timed out")

            if not approved:
                execution_result = "rejected_confirmation_denied"
                _audit("confirmation was explicitly denied")
                raise ConfirmationDeniedError("confirmation was explicitly denied")

            if tool.confirmation_tier == ConfirmationTier.ASK_ONCE_PER_SESSION and session_id:
                self._session_confirmations.setdefault(session_id, set()).add(confirmed_key)
        else:
            confirmation_result = "not_required"

        # --- Stage 6: execution --------------------------------------------
        output, exec_error = await self._run_with_retries(tool, arguments, session_id, principal_id, task_id)
        if exec_error is not None:
            execution_result = (
                "timed_out" if isinstance(exec_error, asyncio.TimeoutError) else "error"
            )
            _audit(f"execution failed ({type(exec_error).__name__})")
            if isinstance(exec_error, asyncio.TimeoutError):
                raise ToolTimeoutError(
                    f"tool '{tool_name}' exceeded its {tool.timeout_seconds}s timeout"
                ) from exec_error
            return ToolExecutionResult(
                success=False,
                stage="execution",
                error=str(exec_error),
                confirmation_id=confirmation_id,
            )

        execution_result = "success"

        # --- Stage 7a: output-schema validation -----------------------------
        # A handler returning malformed data is not a successful tool call.
        # Validate the declared output contract before verification.
        try:
            jsonschema.validate(instance=output, schema=tool.output_schema)
        except jsonschema.exceptions.SchemaError as exc:
            execution_result = "rejected_invalid_output_schema"
            verification_result = "not_reached"
            _audit(f"tool '{tool_name}' has an invalid output_schema ({type(exc).__name__})")
            raise OutputSchemaValidationError(
                f"tool '{tool_name}' has an invalid output schema"
            ) from exc
        except jsonschema.exceptions.ValidationError as exc:
            execution_result = "rejected_invalid_output"
            verification_result = "not_reached"
            _audit(f"tool '{tool_name}' returned output that violates its schema ({type(exc).__name__})")
            return ToolExecutionResult(
                success=False,
                stage="output_validation",
                error="tool output failed the declared output schema",
                confirmation_id=confirmation_id,
            )

        # --- Stage 7b: verification -----------------------------------------
        verification_result = await self._verify(tool, arguments, output or {}, session_id, principal_id, task_id)

        # Only verified / explicitly-not-required results may be reported as
        # successful. A failed callback or pending manual verification is not
        # a completed action.
        verified_success = verification_result in {"verified", "not_required"}
        if not verified_success:
            execution_result = "success_unverified"

        audit_entry = self.audit_logger.record(
            requested_action=action_label,
            tool_name=tool_name,
            risk_level=risk_level_str,
            permission_result=permission_result,
            confirmation_result=confirmation_result,
            execution_result=execution_result,
            verification_result=verification_result,
            detail={"output_keys": list((output or {}).keys())},
        )

        return ToolExecutionResult(
            success=verified_success,
            stage="verification",
            output=output if verified_success else None,
            error=None if verified_success else "tool execution completed but verification did not establish success",
            audit_id=audit_entry.id,
            confirmation_id=confirmation_id,
        )

    async def _resolve_confirmation(
        self, request, confirmation_callback, timeout_seconds: float
    ) -> bool:
        if confirmation_callback is not None:
            result = confirmation_callback(request)
            if asyncio.iscoroutine(result):
                result = await result
            self.confirmation_broker.resolve(request.id, bool(result), resolved_by="callback")
            return bool(result)

        resolved = await self.confirmation_broker.wait_for_resolution(
            request.id, timeout_seconds=timeout_seconds
        )
        return resolved.status == ConfirmationStatus.APPROVED

    async def _run_with_retries(
        self, tool: ToolDefinition, arguments: dict[str, Any],
        session_id: str | None, principal_id: str, task_id: str | None = None
    ) -> tuple[dict[str, Any] | None, Exception | None]:
        from app.tools.models import ExecutionContext, RESERVED_INTERNAL_KEYS
        policy = tool.retry_policy
        last_error: Exception | None = None

        # Server-created execution context -- the AI never controls these fields.
        ctx = ExecutionContext(
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
        )

        # Strip any reserved internal keys the AI may have injected.
        clean_args = {k: v for k, v in arguments.items() if k not in RESERVED_INTERNAL_KEYS}

        for attempt in range(1, policy.max_attempts + 1):
            try:
                output = await asyncio.wait_for(
                    tool.handler(ctx, clean_args), timeout=tool.timeout_seconds
                )
                return output, None
            except asyncio.TimeoutError as exc:
                last_error = exc
                if not policy.retry_on_timeout:
                    return None, exc
            except Exception as exc:  # noqa: BLE001 -- tool handlers are untrusted
                last_error = exc
                if attempt >= policy.max_attempts:
                    return None, exc
            if attempt < policy.max_attempts and policy.backoff_seconds > 0:
                await asyncio.sleep(policy.backoff_seconds)
        return None, last_error

    async def _verify(
        self, tool: ToolDefinition, arguments: dict[str, Any], output: dict[str, Any],
        session_id: str | None, principal_id: str, task_id: str | None = None
    ) -> str:
        from app.tools.models import VerificationMethod, ExecutionContext, RESERVED_INTERNAL_KEYS

        if tool.verification_method == VerificationMethod.NONE:
            return "not_required"
        if tool.verification_method == VerificationMethod.MANUAL:
            return "pending_manual"
        if tool.verification_method == VerificationMethod.CALLBACK:
            if tool.verifier is None:
                return "misconfigured_no_verifier"
            ctx = ExecutionContext(principal_id=principal_id, session_id=session_id, task_id=task_id)
            clean_args = {k: v for k, v in arguments.items() if k not in RESERVED_INTERNAL_KEYS}
            try:
                ok = await tool.verifier(ctx, clean_args, output)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Verifier raised for tool %s", tool.name)
                return f"verifier_error:{exc}"[:32]
            return "verified" if ok else "failed"
        return "not_required"
