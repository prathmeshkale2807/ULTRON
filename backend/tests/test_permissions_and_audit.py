from __future__ import annotations

from app.audit.log import AuditLogger, redact_detail
from app.core.database import AuditLogEntry
from app.permissions.models import PermissionScope, PermissionStatus
from app.permissions.store import PermissionStore
from app.tools.models import DeviceType, PermissionCategory


def test_permission_defaults_to_unset(db_session) -> None:
    store = PermissionStore(db_session, session_store={})
    status = store.check("local_user", PermissionCategory.FILE_WRITE)
    assert status == PermissionStatus.UNSET


def test_persistent_grant_and_revoke(db_session) -> None:
    store = PermissionStore(db_session, session_store={})

    store.grant("local_user", PermissionCategory.FILE_WRITE, PermissionScope.PERSISTENT)
    assert store.check("local_user", PermissionCategory.FILE_WRITE) == PermissionStatus.GRANTED

    store.revoke("local_user", PermissionCategory.FILE_WRITE, PermissionScope.PERSISTENT)
    assert store.check("local_user", PermissionCategory.FILE_WRITE) == PermissionStatus.DENIED


def test_session_permission_is_isolated_per_session(db_session) -> None:
    store = PermissionStore(db_session, session_store={})

    store.grant(
        "local_user", PermissionCategory.NETWORK, PermissionScope.SESSION, session_id="session-a"
    )

    assert (
        store.check("local_user", PermissionCategory.NETWORK, session_id="session-a")
        == PermissionStatus.GRANTED
    )
    # A different session never saw a grant -- and falls back to
    # persistent, which is also unset here.
    assert (
        store.check("local_user", PermissionCategory.NETWORK, session_id="session-b")
        == PermissionStatus.UNSET
    )
    # No session_id at all -- persistent-only lookup, still unset.
    assert store.check("local_user", PermissionCategory.NETWORK) == PermissionStatus.UNSET


def test_session_grant_does_not_persist_across_stores(db_session) -> None:
    """A session grant lives in-memory only -- a fresh session_store
    (simulating a process restart) must not remember it."""
    first_store = PermissionStore(db_session, session_store={})
    first_store.grant(
        "local_user", PermissionCategory.DEVICE_CONTROL, PermissionScope.SESSION, session_id="s1"
    )

    second_store = PermissionStore(db_session, session_store={})
    assert (
        second_store.check("local_user", PermissionCategory.DEVICE_CONTROL, session_id="s1")
        == PermissionStatus.UNSET
    )


def test_session_grant_takes_priority_over_stale_persistent_denial(db_session) -> None:
    store = PermissionStore(db_session, session_store={})
    store.revoke("local_user", PermissionCategory.BROWSER_NAVIGATE, PermissionScope.PERSISTENT)
    store.grant(
        "local_user", PermissionCategory.BROWSER_NAVIGATE, PermissionScope.SESSION, session_id="s1"
    )

    assert (
        store.check("local_user", PermissionCategory.BROWSER_NAVIGATE, session_id="s1") == PermissionStatus.GRANTED
    )


def test_tool_and_device_scoped_grant_does_not_leak_to_other_tools(db_session) -> None:
    store = PermissionStore(db_session, session_store={})
    store.grant(
        "local_user", PermissionCategory.FILE_WRITE,
        PermissionScope.PERSISTENT,
        tool_name="pc.write_file",
        device=DeviceType.PC,
    )

    assert (
        store.check(
            "local_user", PermissionCategory.FILE_WRITE, tool_name="pc.write_file", device=DeviceType.PC
        )
        == PermissionStatus.GRANTED
    )
    # A different tool in the same category was never granted anything.
    assert (
        store.check(
            "local_user", PermissionCategory.FILE_WRITE, tool_name="android.write_file", device=DeviceType.PC
        )
        == PermissionStatus.UNSET
    )


def test_redact_detail_masks_secret_like_keys() -> None:
    payload = {
        "action": "call api",
        "api_key": "sk-super-secret-value",
        "nested": {"password": "hunter2", "note": "fine"},
        "tokens": ["abc"],
    }
    text = redact_detail(payload)

    assert "sk-super-secret-value" not in text
    assert "hunter2" not in text
    assert "[REDACTED]" in text
    assert "fine" in text  # non-secret values are preserved


def test_audit_logger_writes_row_and_redacts(db_session) -> None:
    logger = AuditLogger(db_session)
    entry = logger.record(
        requested_action="write file",
        tool_name="pc.write_file",
        risk_level="medium",
        permission_result="granted",
        confirmation_result="not_required",
        execution_result="success",
        verification_result="not_required",
        detail={"password": "should-not-appear", "path": "C:/tmp/file.txt"},
    )

    assert entry.id is not None
    row = db_session.get(AuditLogEntry, entry.id)
    assert row is not None
    assert "should-not-appear" not in row.detail
    assert "C:/tmp/file.txt" in row.detail
