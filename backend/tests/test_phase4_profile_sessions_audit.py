"""
Phase 4 unit tests: persistent active profile, session lifecycle, and
the permission/profile/emergency audit trail. Gate-level floor
guarantees (ALWAYS_ASK/CRITICAL non-overridability across modes) are
already covered by tests/test_safety_gate.py and are not re-tested
here -- this file only covers what's new in Phase 4: persistence,
session lifecycle, and audit history, plus the one genuinely new
integration point (a persisted Custom override still can't cross the
gate's floors).
"""

from __future__ import annotations

import time

from app.audit.permission_log import PermissionAuditLogger
from app.core.database import PermissionAuditEntry
from app.profile.manager import ProfileManager
from app.safety.gate import SafetyGate
from app.safety.models import GateAction, SafetyMode
from app.sessions.manager import SessionManager
from app.tools.models import ConfirmationTier, DeviceType, PermissionCategory, RiskLevel


# --- ProfileManager ---------------------------------------------------


def test_profile_defaults_to_balanced(db_session) -> None:
    state = ProfileManager(db_session).get()
    assert state.mode == SafetyMode.BALANCED
    assert state.custom_overrides == {}


def test_profile_persists_across_manager_instances(db_session) -> None:
    ProfileManager(db_session).set(SafetyMode.TRUSTED, updated_by="user")

    reloaded = ProfileManager(db_session).get()
    assert reloaded.mode == SafetyMode.TRUSTED
    assert reloaded.updated_by == "user"


def test_profile_custom_overrides_round_trip(db_session) -> None:
    overrides = {PermissionCategory.NETWORK: ConfirmationTier.ALWAYS_ASK}
    ProfileManager(db_session).set(
        SafetyMode.CUSTOM, custom_overrides=overrides, updated_by="user"
    )

    reloaded = ProfileManager(db_session).get()
    assert reloaded.mode == SafetyMode.CUSTOM
    assert reloaded.custom_overrides == overrides


def test_leaving_custom_mode_clears_stale_overrides(db_session) -> None:
    manager = ProfileManager(db_session)
    manager.set(
        SafetyMode.CUSTOM,
        custom_overrides={PermissionCategory.NETWORK: ConfirmationTier.AUTOMATIC},
        updated_by="user",
    )
    manager.set(SafetyMode.BALANCED, updated_by="user")

    assert manager.get().custom_overrides == {}


async def _noop_handler(args):
    return {}


def test_persisted_custom_override_still_cannot_bypass_critical_floor(db_session) -> None:
    """A Custom Mode override that tries to make CRITICAL tools
    automatic must still be forced to REQUIRE_CONFIRMATION by the gate
    -- persistence must never widen what Custom Mode is allowed to do."""
    from app.tools.models import ToolDefinition

    ProfileManager(db_session).set(
        SafetyMode.CUSTOM,
        custom_overrides={PermissionCategory.SYSTEM_CONTROL: ConfirmationTier.AUTOMATIC},
        updated_by="user",
    )
    gate, mode = ProfileManager(db_session).to_gate()
    assert isinstance(gate, SafetyGate)
    assert mode == SafetyMode.CUSTOM

    critical_tool = ToolDefinition(
        name="pc.wipe_disk",
        description="critical test tool",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        risk_level=RiskLevel.CRITICAL,
        permission_category=PermissionCategory.SYSTEM_CONTROL,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.PC],
        handler=_noop_handler,
    )

    decision = gate.evaluate(critical_tool, mode)
    assert decision.action == GateAction.REQUIRE_CONFIRMATION
    assert decision.non_overridable is True


# --- SessionManager -----------------------------------------------------


def test_session_create_and_is_valid(db_session) -> None:
    manager = SessionManager(db_session)
    info = manager.create()
    assert info.valid is True
    assert manager.is_valid(info.session_id) is True


def test_session_expires(db_session) -> None:
    manager = SessionManager(db_session)
    info = manager.create(ttl_seconds=0.01)
    time.sleep(0.05)
    assert manager.is_valid(info.session_id) is False
    assert manager.get(info.session_id).valid is False


def test_session_invalidation_clears_session_permissions(db_session) -> None:
    from app.permissions.models import PermissionScope, PermissionStatus
    from app.permissions.store import PermissionStore

    # No explicit session_store: use the same process-wide default dict
    # that SessionManager.invalidate()'s internal PermissionStore(db)
    # also uses, so invalidation is exercised end-to-end for real.
    store = PermissionStore(db_session)
    manager = SessionManager(db_session)
    info = manager.create()

    store.grant(PermissionCategory.NETWORK, PermissionScope.SESSION, session_id=info.session_id)
    assert store.check(PermissionCategory.NETWORK, session_id=info.session_id) == (
        PermissionStatus.GRANTED
    )

    manager.invalidate(info.session_id)

    assert store.check(PermissionCategory.NETWORK, session_id=info.session_id) == (
        PermissionStatus.UNSET
    )
    assert manager.is_valid(info.session_id) is False


def test_unknown_session_is_not_valid(db_session) -> None:
    assert SessionManager(db_session).is_valid("nonexistent") is False


# --- PermissionAuditLogger -----------------------------------------------


def test_permission_audit_records_actor_and_states(db_session) -> None:
    entry = PermissionAuditLogger(db_session).record(
        actor="local-ui",
        action="grant",
        category=PermissionCategory.FILE_WRITE.value,
        tool_name="pc.write_file",
        device=DeviceType.PC.value,
        old_state="unset",
        new_state="granted",
    )
    row = db_session.get(PermissionAuditEntry, entry.id)
    assert row is not None
    assert row.actor == "local-ui"
    assert row.action == "grant"
    assert row.old_state == "unset"
    assert row.new_state == "granted"


def test_permission_audit_entry_has_no_secret_bearing_field(db_session) -> None:
    """Structural guarantee: this table has no free-form detail column
    at all, so a secret can't be smuggled through it even by accident."""
    columns = {c.name for c in PermissionAuditEntry.__table__.columns}
    assert "detail" not in columns
    assert "value" not in columns
