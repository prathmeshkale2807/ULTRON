"""
Safety Gate unit tests.

Pure function tests -- no database, no asyncio, no executor. These pin
down the two non-overridable floors (tool-level ALWAYS_ASK, and
CRITICAL risk) across every Safety Mode, plus Balanced/Trusted/Custom
mode-specific behavior.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.safety.gate import SafetyGate
from app.safety.models import GateAction, SafetyMode
from app.tools.models import (
    ConfirmationTier,
    DeviceType,
    PermissionCategory,
    RiskLevel,
    ToolDefinition,
)


async def _noop_handler(args: dict[str, Any]) -> dict[str, Any]:
    return {}


def make_tool(**overrides: Any) -> ToolDefinition:
    defaults: dict[str, Any] = dict(
        name="mock.tool",
        description="A mock tool for gate tests.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.OTHER,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.SERVER],
        handler=_noop_handler,
    )
    defaults.update(overrides)
    return ToolDefinition(**defaults)


@pytest.mark.parametrize(
    "mode", [SafetyMode.SAFE, SafetyMode.BALANCED, SafetyMode.TRUSTED, SafetyMode.CUSTOM]
)
def test_always_ask_is_never_bypassed(mode: SafetyMode) -> None:
    """The core non-overridable guarantee: no matter the mode, a tool
    marked ALWAYS_ASK always requires confirmation."""
    tool = make_tool(confirmation_tier=ConfirmationTier.ALWAYS_ASK, risk_level=RiskLevel.LOW)
    gate = SafetyGate(custom_overrides={PermissionCategory.OTHER: ConfirmationTier.AUTOMATIC})

    decision = gate.evaluate(tool, mode)

    assert decision.action == GateAction.REQUIRE_CONFIRMATION
    assert decision.non_overridable is True


def test_trusted_mode_cannot_bypass_always_ask() -> None:
    """Explicit, named test for the exact scenario called out in the
    spec: Trusted Mode + an ALWAYS_ASK tool still requires confirmation,
    even though Trusted Mode auto-approves everything else."""
    always_ask_tool = make_tool(confirmation_tier=ConfirmationTier.ALWAYS_ASK)
    automatic_tool = make_tool(confirmation_tier=ConfirmationTier.AUTOMATIC)
    gate = SafetyGate()

    always_ask_decision = gate.evaluate(always_ask_tool, SafetyMode.TRUSTED)
    automatic_decision = gate.evaluate(automatic_tool, SafetyMode.TRUSTED)

    assert always_ask_decision.action == GateAction.REQUIRE_CONFIRMATION
    assert always_ask_decision.non_overridable is True
    # Contrast case: Trusted Mode DOES auto-approve a plain automatic
    # tool, proving the ALWAYS_ASK floor above is doing real work and
    # Trusted Mode isn't just always asking anyway.
    assert automatic_decision.action == GateAction.ALLOW


@pytest.mark.parametrize(
    "mode", [SafetyMode.SAFE, SafetyMode.BALANCED, SafetyMode.TRUSTED, SafetyMode.CUSTOM]
)
def test_critical_risk_always_requires_confirmation(mode: SafetyMode) -> None:
    tool = make_tool(
        risk_level=RiskLevel.CRITICAL, confirmation_tier=ConfirmationTier.AUTOMATIC
    )
    gate = SafetyGate()

    decision = gate.evaluate(tool, mode)

    assert decision.action == GateAction.REQUIRE_CONFIRMATION
    assert decision.non_overridable is True


def test_safe_mode_requires_confirmation_for_everything() -> None:
    tool = make_tool(risk_level=RiskLevel.LOW, confirmation_tier=ConfirmationTier.AUTOMATIC)
    gate = SafetyGate()

    decision = gate.evaluate(tool, SafetyMode.SAFE)

    assert decision.action == GateAction.REQUIRE_CONFIRMATION


def test_trusted_mode_auto_approves_low_risk_automatic_tool() -> None:
    tool = make_tool(risk_level=RiskLevel.LOW, confirmation_tier=ConfirmationTier.AUTOMATIC)
    gate = SafetyGate()

    decision = gate.evaluate(tool, SafetyMode.TRUSTED)

    assert decision.action == GateAction.ALLOW


def test_balanced_mode_escalates_high_risk_automatic_tool() -> None:
    tool = make_tool(risk_level=RiskLevel.HIGH, confirmation_tier=ConfirmationTier.AUTOMATIC)
    gate = SafetyGate()

    decision = gate.evaluate(tool, SafetyMode.BALANCED)

    assert decision.action == GateAction.REQUIRE_CONFIRMATION


def test_balanced_mode_allows_low_risk_automatic_tool() -> None:
    tool = make_tool(risk_level=RiskLevel.LOW, confirmation_tier=ConfirmationTier.AUTOMATIC)
    gate = SafetyGate()

    decision = gate.evaluate(tool, SafetyMode.BALANCED)

    assert decision.action == GateAction.ALLOW


def test_ask_once_per_session_requires_confirmation_first_time_only() -> None:
    tool = make_tool(
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION, risk_level=RiskLevel.LOW
    )
    gate = SafetyGate()

    first = gate.evaluate(tool, SafetyMode.BALANCED, already_confirmed_this_session=False)
    second = gate.evaluate(tool, SafetyMode.BALANCED, already_confirmed_this_session=True)

    assert first.action == GateAction.REQUIRE_CONFIRMATION
    assert second.action == GateAction.ALLOW


def test_explicit_permission_denial_is_terminal_deny() -> None:
    tool = make_tool(risk_level=RiskLevel.LOW, confirmation_tier=ConfirmationTier.AUTOMATIC)
    gate = SafetyGate()

    decision = gate.evaluate(tool, SafetyMode.TRUSTED, permission_denied=True)

    assert decision.action == GateAction.DENY
    assert decision.non_overridable is True


def test_custom_mode_override_can_escalate_but_not_bypass_floor() -> None:
    tool = make_tool(
        permission_category=PermissionCategory.FILE_WRITE,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        risk_level=RiskLevel.LOW,
    )
    # Custom override forces FILE_WRITE to always ask, even though the
    # tool itself only declares AUTOMATIC.
    gate = SafetyGate(
        custom_overrides={PermissionCategory.FILE_WRITE: ConfirmationTier.ALWAYS_ASK}
    )

    decision = gate.evaluate(tool, SafetyMode.CUSTOM)

    assert decision.action == GateAction.REQUIRE_CONFIRMATION
    assert decision.non_overridable is True


def test_custom_mode_override_can_relax_to_automatic() -> None:
    tool = make_tool(
        permission_category=PermissionCategory.NETWORK,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        risk_level=RiskLevel.LOW,
    )
    gate = SafetyGate(
        custom_overrides={PermissionCategory.NETWORK: ConfirmationTier.AUTOMATIC}
    )

    decision = gate.evaluate(tool, SafetyMode.CUSTOM)

    assert decision.action == GateAction.ALLOW
