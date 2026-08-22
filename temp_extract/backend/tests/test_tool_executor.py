"""
Tool Executor pipeline tests.

Covers, in order, every stage of:
    schema -> risk -> device -> permission -> confirmation -> execution -> verification
plus the emergency stop foundation and audit logging, using mock/test
tools only (no PC, Android, browser, email, or calendar action --
explicitly out of scope for Phase 3).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.audit.log import redact_detail
from app.core.database import AuditLogEntry
from app.emergency.stop import EmergencyStop
from app.executor.confirmation import ConfirmationBroker
from app.executor.executor import (
    ConfirmationDeniedError,
    ConfirmationTimeoutError,
    DeviceValidationError,
    EmergencyStopEngagedError,
    PermissionDeniedError,
    RiskRejectedError,
    SchemaValidationError,
    OutputSchemaValidationError,
    ToolDisabledError,
    ToolExecutor,
    ToolNotFoundError,
    ToolTimeoutError,
)
from app.permissions.models import PermissionScope
from app.safety.gate import SafetyGate
from app.safety.models import SafetyMode
from app.tools.models import (
    ConfirmationTier,
    DeviceType,
    PermissionCategory,
    RetryPolicy,
    RiskLevel,
    ToolDefinition,
    VerificationMethod,
)
from app.tools.registry import ToolAlreadyRegisteredError, ToolRegistry

# pytest.ini sets asyncio_mode = auto, so `async def test_...` functions
# below run without needing an explicit @pytest.mark.asyncio marker.


# --- mock tool handlers (test/mock tools only, per the Phase 3 spec) -----


async def echo_handler(ctx, args: dict[str, Any]) -> dict[str, Any]:
    return {"echo": args}


async def slow_handler(ctx, args: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(2.0)
    return {"ok": True}


async def failing_handler(ctx, args: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("mock tool failure")


def make_flaky_handler(fail_times: int):
    calls = {"count": 0}

    async def handler(ctx, args: dict[str, Any]) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] <= fail_times:
            raise RuntimeError("transient mock failure")
        return {"attempt": calls["count"]}

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


def make_tool(**overrides: Any) -> ToolDefinition:
    defaults: dict[str, Any] = dict(
        name="mock.echo",
        description="Echoes its arguments back. Test/mock tool only.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.FILE_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        timeout_seconds=5.0,
        handler=echo_handler,
    )
    defaults.update(overrides)
    return ToolDefinition(**defaults)


def make_executor(db_session, *, mode: SafetyMode = SafetyMode.BALANCED, **kwargs: Any):
    registry = kwargs.pop("registry", ToolRegistry())
    return registry, ToolExecutor(
        registry=registry,
        db=db_session,
        mode=mode,
        gate=kwargs.pop("gate", SafetyGate()),
        confirmation_broker=kwargs.pop("confirmation_broker", ConfirmationBroker()),
        session_confirmations=kwargs.pop("session_confirmations", {}),
        **kwargs,
    )


def latest_audit_row(db_session) -> AuditLogEntry:
    stmt = select(AuditLogEntry).order_by(AuditLogEntry.id.desc()).limit(1)
    row = db_session.scalars(stmt).first()
    assert row is not None, "expected an audit log row to have been written"
    return row


# --- 1. Tool Registry -----------------------------------------------------


def test_valid_tool_registration() -> None:
    registry = ToolRegistry()
    tool = make_tool()

    registry.register(tool)

    assert registry.exists("mock.echo")
    fetched = registry.get("mock.echo")
    assert fetched.name == "mock.echo"
    assert fetched.enabled is True
    assert fetched in registry.list_tools()


def test_registering_duplicate_tool_name_raises() -> None:
    registry = ToolRegistry()
    registry.register(make_tool())

    with pytest.raises(ToolAlreadyRegisteredError):
        registry.register(make_tool())


def test_tool_definition_missing_required_safety_field_raises() -> None:
    with pytest.raises(ValidationError):
        ToolDefinition(
            name="mock.incomplete",
            description="Missing risk_level and friends.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            # risk_level intentionally omitted
            permission_category=PermissionCategory.OTHER,
            confirmation_tier=ConfirmationTier.AUTOMATIC,
            allowed_devices=[DeviceType.PC],
            handler=echo_handler,
        )


def test_tool_definition_requires_at_least_one_allowed_device() -> None:
    with pytest.raises(ValidationError):
        make_tool(allowed_devices=[])


# --- 2/6. Tool validation: unknown tool, wrong device, malformed args -----


async def test_execute_unknown_tool_is_rejected(db_session) -> None:
    _, executor = make_executor(db_session)

    with pytest.raises(ToolNotFoundError):
        await executor.execute("does.not.exist", {}, target_device=DeviceType.PC)

    row = latest_audit_row(db_session)
    assert row.execution_result == "rejected_unknown_tool"


async def test_execute_rejects_disabled_tool(db_session) -> None:
    registry, executor = make_executor(db_session)
    registry.register(make_tool())
    registry.set_enabled("mock.echo", False)

    with pytest.raises(ToolDisabledError):
        await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert latest_audit_row(db_session).execution_result == "rejected_tool_disabled"


async def test_execute_rejects_malformed_arguments(db_session) -> None:
    registry, executor = make_executor(db_session)
    registry.register(make_tool())

    with pytest.raises(SchemaValidationError):
        # missing required "path"
        await executor.execute("mock.echo", {}, target_device=DeviceType.PC)

    assert latest_audit_row(db_session).execution_result == "rejected_malformed_arguments"


async def test_execute_rejects_malicious_extra_arguments(db_session) -> None:
    registry, executor = make_executor(db_session)
    registry.register(make_tool())

    with pytest.raises(SchemaValidationError):
        await executor.execute(
            "mock.echo",
            {"path": "ok.txt", "__proto__": {"admin": True}},
            target_device=DeviceType.PC,
        )

    assert latest_audit_row(db_session).execution_result == "rejected_malformed_arguments"


async def test_execute_rejects_wrong_type_argument(db_session) -> None:
    registry, executor = make_executor(db_session)
    registry.register(make_tool())

    with pytest.raises(SchemaValidationError):
        await executor.execute("mock.echo", {"path": 12345}, target_device=DeviceType.PC)


async def test_execute_rejects_invalid_tool_schema_itself(db_session) -> None:
    registry, executor = make_executor(db_session)
    # The tool's OWN declared input_schema is not valid JSON Schema --
    # "properties" must be an object, not a string.
    registry.register(make_tool(input_schema={"type": "object", "properties": "nope"}))

    with pytest.raises(SchemaValidationError):
        await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert latest_audit_row(db_session).execution_result == "rejected_invalid_tool_schema"


async def test_execute_rejects_wrong_device(db_session) -> None:
    registry, executor = make_executor(db_session)
    registry.register(make_tool(allowed_devices=[DeviceType.ANDROID]))

    with pytest.raises(DeviceValidationError):
        await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert latest_audit_row(db_session).execution_result == "rejected_unauthorized_device"


async def test_execute_blocks_configured_risk_level(db_session) -> None:
    registry, executor = make_executor(
        db_session, blocked_risk_levels={RiskLevel.HIGH}
    )
    registry.register(make_tool(risk_level=RiskLevel.HIGH))

    with pytest.raises(RiskRejectedError):
        await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert latest_audit_row(db_session).execution_result == "rejected_risk_blocked"


# --- Permission validation -------------------------------------------------


async def test_execute_rejects_missing_permission(db_session) -> None:
    registry, executor = make_executor(db_session)
    registry.register(make_tool())

    with pytest.raises(PermissionDeniedError):
        await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    row = latest_audit_row(db_session)
    assert row.execution_result == "rejected_missing_permission"
    assert row.permission_result == "unset"


async def test_execute_rejects_denied_permission(db_session) -> None:
    registry, executor = make_executor(db_session)
    registry.register(make_tool())
    executor.permission_store.revoke(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    with pytest.raises(PermissionDeniedError):
        await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    row = latest_audit_row(db_session)
    assert row.execution_result == "rejected_permission_denied"
    assert row.permission_result == "denied"


# --- Confirmation system ----------------------------------------------------


async def test_execute_succeeds_after_confirmation_approved(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.SAFE)
    registry.register(make_tool())
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    result = await executor.execute(
        "mock.echo",
        {"path": "x"},
        target_device=DeviceType.PC,
        confirmation_callback=lambda req: True,
    )

    assert result.success is True
    assert result.output == {"echo": {"path": "x"}}
    row = latest_audit_row(db_session)
    assert row.confirmation_result == "approved"
    assert row.execution_result == "success"


async def test_execute_raises_when_confirmation_denied(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.SAFE)
    registry.register(make_tool())
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    with pytest.raises(ConfirmationDeniedError):
        await executor.execute(
            "mock.echo",
            {"path": "x"},
            target_device=DeviceType.PC,
            confirmation_callback=lambda req: False,
        )

    row = latest_audit_row(db_session)
    assert row.confirmation_result == "denied"
    assert row.execution_result == "rejected_confirmation_denied"


async def test_execute_raises_when_confirmation_times_out(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.SAFE)
    registry.register(make_tool())
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    with pytest.raises(ConfirmationTimeoutError):
        await executor.execute(
            "mock.echo",
            {"path": "x"},
            target_device=DeviceType.PC,
            confirmation_timeout_seconds=0.05,
        )

    row = latest_audit_row(db_session)
    assert row.confirmation_result == "timed_out"
    assert row.execution_result == "rejected_confirmation_timeout"


async def test_ask_once_per_session_skips_confirmation_on_second_call(db_session) -> None:
    session_confirmations: dict[str, set[str]] = {}
    registry, executor = make_executor(
        db_session, mode=SafetyMode.BALANCED, session_confirmations=session_confirmations
    )
    registry.register(make_tool(confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION))
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    first = await executor.execute(
        "mock.echo",
        {"path": "x"},
        target_device=DeviceType.PC,
        session_id="s1",
        confirmation_callback=lambda req: True,
    )
    # Second call: no confirmation_callback given at all. If the gate
    # incorrectly asked again, this would hang waiting on the broker
    # until the default 120s timeout -- so a fast pass here proves it
    # was skipped, not just "eventually allowed".
    second = await executor.execute(
        "mock.echo",
        {"path": "x"},
        target_device=DeviceType.PC,
        session_id="s1",
        confirmation_timeout_seconds=0.2,
    )

    assert first.success is True
    assert second.success is True
    assert latest_audit_row(db_session).confirmation_result == "not_required"


async def test_always_ask_cannot_be_bypassed_across_repeated_calls(db_session) -> None:
    session_confirmations: dict[str, set[str]] = {}
    registry, executor = make_executor(
        db_session, mode=SafetyMode.BALANCED, session_confirmations=session_confirmations
    )
    registry.register(make_tool(confirmation_tier=ConfirmationTier.ALWAYS_ASK))
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    call_count = {"n": 0}

    def approve(req):
        call_count["n"] += 1
        return True

    for _ in range(3):
        result = await executor.execute(
            "mock.echo",
            {"path": "x"},
            target_device=DeviceType.PC,
            session_id="same-session",
            confirmation_callback=approve,
        )
        assert result.success is True

    # Every single call had to be confirmed again -- an "ask once"
    # shortcut never kicked in for an ALWAYS_ASK tool.
    assert call_count["n"] == 3


async def test_trusted_mode_cannot_bypass_always_ask(db_session) -> None:
    session_confirmations: dict[str, set[str]] = {}
    registry, executor = make_executor(
        db_session, mode=SafetyMode.TRUSTED, session_confirmations=session_confirmations
    )
    registry.register(make_tool(confirmation_tier=ConfirmationTier.ALWAYS_ASK))
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    call_count = {"n": 0}

    def approve(req):
        call_count["n"] += 1
        return True

    await executor.execute(
        "mock.echo",
        {"path": "x"},
        target_device=DeviceType.PC,
        session_id="trusted-session",
        confirmation_callback=approve,
    )
    await executor.execute(
        "mock.echo",
        {"path": "x"},
        target_device=DeviceType.PC,
        session_id="trusted-session",
        confirmation_callback=approve,
    )

    assert call_count["n"] == 2  # confirmed twice, not auto-approved by Trusted Mode

    # Contrast: a plain AUTOMATIC tool in Trusted Mode does NOT need any
    # confirmation callback at all -- proves Trusted Mode is genuinely
    # auto-approving everything else, and the ALWAYS_ASK case above is a
    # real floor rather than Trusted Mode just always asking anyway.
    registry.register(make_tool(name="mock.echo.auto", confirmation_tier=ConfirmationTier.AUTOMATIC))
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)
    auto_result = await executor.execute(
        "mock.echo.auto", {"path": "x"}, target_device=DeviceType.PC
    )
    assert auto_result.success is True


async def test_session_permission_grant_is_scoped_to_its_session(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)
    registry.register(make_tool())
    executor.permission_store.grant(
        PermissionCategory.FILE_READ, PermissionScope.SESSION, session_id="granted-session"
    )

    ok = await executor.execute(
        "mock.echo", {"path": "x"}, target_device=DeviceType.PC, session_id="granted-session"
    )
    assert ok.success is True

    with pytest.raises(PermissionDeniedError):
        await executor.execute(
            "mock.echo",
            {"path": "x"},
            target_device=DeviceType.PC,
            session_id="different-session",
        )


# --- Execution: timeout + retries ------------------------------------------


async def test_tool_execution_timeout_is_enforced(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)
    registry.register(make_tool(handler=slow_handler, timeout_seconds=0.05))
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    with pytest.raises(ToolTimeoutError):
        await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert latest_audit_row(db_session).execution_result == "timed_out"


async def test_handler_error_without_retry_returns_failure_result(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)
    registry.register(make_tool(handler=failing_handler))
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    result = await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert result.success is False
    assert "mock tool failure" in (result.error or "")
    assert latest_audit_row(db_session).execution_result == "error"


async def test_retry_policy_retries_then_succeeds(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)
    flaky = make_flaky_handler(fail_times=1)
    registry.register(
        make_tool(handler=flaky, retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=0.0))
    )
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    result = await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert result.success is True
    assert result.output == {"attempt": 2}


# --- Verification -----------------------------------------------------------


async def test_verification_callback_marks_verified_or_failed(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)

    async def always_true_verifier(ctx, args, output):
        return True

    registry.register(
        make_tool(
            verification_method=VerificationMethod.CALLBACK,
            verifier=always_true_verifier,
        )
    )
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    result = await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert result.success is True
    assert latest_audit_row(db_session).verification_result == "verified"




async def test_invalid_output_schema_is_rejected(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)
    registry.register(make_tool(output_schema={"type": "object", "required": ["must_exist"]}))
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    result = await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert result.success is False
    assert result.stage == "output_validation"
    assert latest_audit_row(db_session).execution_result == "rejected_invalid_output"


async def test_failed_verification_is_not_reported_as_success(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)

    async def always_false_verifier(ctx, args, output):
        return False

    registry.register(
        make_tool(
            verification_method=VerificationMethod.CALLBACK,
            verifier=always_false_verifier,
        )
    )
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    result = await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert result.success is False
    assert result.output is None
    row = latest_audit_row(db_session)
    assert row.execution_result == "success_unverified"
    assert row.verification_result == "failed"


def test_audit_redacts_secret_like_strings() -> None:
    text = redact_detail("Authorization: Bearer super-secret-token")
    assert "super-secret-token" not in text
    assert "[REDACTED]" in text

# --- Emergency Stop ----------------------------------------------------------


async def test_emergency_stop_blocks_new_tool_execution(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)
    registry.register(make_tool())
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    stop = EmergencyStop(db_session)
    stop.activate(reason="test halt", activated_by="tester")

    with pytest.raises(EmergencyStopEngagedError):
        await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)

    assert latest_audit_row(db_session).execution_result == "blocked_emergency_stop"

    stop.reset(reset_by="tester")
    result = await executor.execute("mock.echo", {"path": "x"}, target_device=DeviceType.PC)
    assert result.success is True


async def test_emergency_stop_status_reports_reason(db_session) -> None:
    stop = EmergencyStop(db_session)
    assert stop.status().engaged is False

    stop.activate(reason="button pressed", activated_by="user")
    status = stop.status()
    assert status.engaged is True
    assert status.reason == "button pressed"

    stop.reset(reset_by="user")
    assert stop.status().engaged is False


# --- Audit logging ------------------------------------------------------------


async def test_audit_logging_records_full_pipeline(db_session) -> None:
    registry, executor = make_executor(db_session, mode=SafetyMode.TRUSTED)
    registry.register(make_tool())
    executor.permission_store.grant(PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)

    result = await executor.execute(
        "mock.echo", {"path": "secret-plan.txt"}, target_device=DeviceType.PC
    )

    assert result.success is True
    row = latest_audit_row(db_session)
    assert row.tool_name == "mock.echo"
    assert row.risk_level == "low"
    assert row.permission_result == "granted"
    assert row.confirmation_result == "not_required"
    assert row.execution_result == "success"
    assert row.verification_result == "not_required"


async def test_ai_layer_never_touches_handler_directly(db_session) -> None:
    """Regression guard for 'the AI must never execute a tool directly':
    the only public way to reach a tool's handler is through
    ToolExecutor.execute -- registry.get() returns metadata, and while
    ToolDefinition.handler is technically reachable on that object in
    Python, it is excluded from every serialized/public view."""
    registry, _ = make_executor(db_session)
    registry.register(make_tool())

    public = registry.get("mock.echo").public_metadata()
    assert "handler" not in public
    assert "verifier" not in public
