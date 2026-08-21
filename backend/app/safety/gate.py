"""
Safety Gate decision logic.

Pure decision function: (tool metadata, mode, a little bit of session
state) -> GateDecision. No I/O, no device access, no database. This is
what makes "Always-Ask cannot be bypassed" and "Trusted Mode cannot
bypass Always-Ask" simple to prove with a unit test -- the function is
deterministic and has no hidden state to fake out.

Non-overridable floors (checked BEFORE any mode branch, so no mode --
including a future CUSTOM misconfiguration -- can skip them):
  1. confirmation_tier == ALWAYS_ASK on the tool itself.
  2. risk_level == CRITICAL.
Both always resolve to REQUIRE_CONFIRMATION with non_overridable=True.
Permission denial resolves to DENY before either floor is evaluated,
since a denied permission means the call doesn't proceed regardless of
how it would otherwise be confirmed.
"""

from __future__ import annotations

from app.safety.models import GateAction, GateDecision, SafetyMode
from app.tools.models import ConfirmationTier, PermissionCategory, RiskLevel, ToolDefinition


class SafetyGate:
    def __init__(
        self,
        custom_overrides: dict[PermissionCategory, ConfirmationTier] | None = None,
    ) -> None:
        # Only meaningful when mode == CUSTOM. Foundation for a future
        # per-user settings UI -- Phase 3 just needs the mechanism to
        # exist and to respect the same non-overridable floors as every
        # other mode.
        self.custom_overrides = dict(custom_overrides or {})

    def evaluate(
        self,
        tool: ToolDefinition,
        mode: SafetyMode,
        *,
        permission_denied: bool = False,
        already_confirmed_this_session: bool = False,
    ) -> GateDecision:
        base_kwargs = dict(
            risk_level=tool.risk_level,
            permission_category=tool.permission_category,
            confirmation_tier=tool.confirmation_tier,
        )

        # --- Explicit denial: terminal, checked first ----------------------
        if permission_denied:
            return GateDecision(
                action=GateAction.DENY,
                reason=(
                    f"permission for category '{tool.permission_category.value}' "
                    "has been explicitly denied/revoked"
                ),
                non_overridable=True,
                **base_kwargs,
            )

        # --- Floor 1: tool-level ALWAYS_ASK, non-overridable ---------------
        if tool.confirmation_tier == ConfirmationTier.ALWAYS_ASK:
            return GateDecision(
                action=GateAction.REQUIRE_CONFIRMATION,
                reason="tool is marked ALWAYS_ASK; no Safety Mode may bypass this",
                non_overridable=True,
                **base_kwargs,
            )

        # --- Floor 2: CRITICAL risk, non-overridable -----------------------
        if tool.risk_level == RiskLevel.CRITICAL:
            return GateDecision(
                action=GateAction.REQUIRE_CONFIRMATION,
                reason="tool risk level is CRITICAL; always requires confirmation",
                non_overridable=True,
                **base_kwargs,
            )

        # --- Safe Mode: everything else still asks --------------------------
        if mode == SafetyMode.SAFE:
            return GateDecision(
                action=GateAction.REQUIRE_CONFIRMATION,
                reason="Safe Mode requires confirmation for every action",
                **base_kwargs,
            )

        # --- Trusted Mode: auto-run anything past the floors above ---------
        if mode == SafetyMode.TRUSTED:
            return GateDecision(
                action=GateAction.ALLOW,
                reason="Trusted Mode auto-approves below the ALWAYS_ASK/CRITICAL floor",
                **base_kwargs,
            )

        # --- Custom Mode: per-category override, still floor-bound ---------
        if mode == SafetyMode.CUSTOM:
            effective_tier = self.custom_overrides.get(
                tool.permission_category, tool.confirmation_tier
            )
            if effective_tier == ConfirmationTier.ALWAYS_ASK:
                return GateDecision(
                    action=GateAction.REQUIRE_CONFIRMATION,
                    reason=(
                        f"Custom Mode override for '{tool.permission_category.value}' "
                        "is ALWAYS_ASK"
                    ),
                    non_overridable=True,
                    **base_kwargs,
                )
            if effective_tier == ConfirmationTier.ASK_ONCE_PER_SESSION:
                if already_confirmed_this_session:
                    return GateDecision(
                        action=GateAction.ALLOW,
                        reason="already confirmed once this session (Custom Mode)",
                        **base_kwargs,
                    )
                return GateDecision(
                    action=GateAction.REQUIRE_CONFIRMATION,
                    reason="Custom Mode: ask-once-per-session, not yet confirmed",
                    **base_kwargs,
                )
            return GateDecision(
                action=GateAction.ALLOW,
                reason="Custom Mode override permits automatic execution",
                **base_kwargs,
            )

        # --- Balanced Mode (default): follow the tool's own tier -----------
        if tool.confirmation_tier == ConfirmationTier.ASK_ONCE_PER_SESSION:
            if already_confirmed_this_session:
                return GateDecision(
                    action=GateAction.ALLOW,
                    reason="already confirmed once this session (Balanced Mode)",
                    **base_kwargs,
                )
            return GateDecision(
                action=GateAction.REQUIRE_CONFIRMATION,
                reason="Balanced Mode: ask-once-per-session, not yet confirmed",
                **base_kwargs,
            )

        # AUTOMATIC tier: Balanced Mode still escalates HIGH risk to a
        # confirmation -- "automatic" describes the tool's baseline, not
        # a promise that Balanced Mode never double-checks a risky call.
        if tool.risk_level == RiskLevel.HIGH:
            return GateDecision(
                action=GateAction.REQUIRE_CONFIRMATION,
                reason="Balanced Mode escalates HIGH risk automatic tools to confirmation",
                **base_kwargs,
            )

        return GateDecision(
            action=GateAction.ALLOW,
            reason="Balanced Mode: automatic tier, risk below the escalation threshold",
            **base_kwargs,
        )
