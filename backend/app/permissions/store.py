"""
Permission Store.

Session grants live in a plain in-memory dict -- by definition they must
not outlive the process, so writing them to the database would be
actively wrong (a restart should NOT resurrect a session grant).
Persistent grants are rows in `permission_records`, looked up by most
recent decision for a given (category, tool_name, device) combination.

Never store secrets as permissions: the only fields ever written are a
PermissionCategory value, an optional tool name, an optional device
type, and a boolean. There is no "value" column for arbitrary data --
that is a deliberate schema constraint, not just a convention.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import PermissionRecord
from app.core.logging_config import get_logger
from app.permissions.models import PermissionScope, PermissionStatus
from app.tools.models import DeviceType, PermissionCategory

logger = get_logger("permissions.store")

# Process-wide session grant table, shared across PermissionStore
# instances (each HTTP request gets its own DB Session, but session
# grants must be visible across requests within the same ULTRON
# session). Tests that need isolation should pass their own dict via
# `session_store=`.
_default_session_store: dict[str, dict[str, bool]] = {}


def _key(
    category: PermissionCategory, tool_name: str | None, device: DeviceType | str | None
) -> str:
    device_value = device.value if isinstance(device, DeviceType) else device
    return f"{category.value}|{tool_name or '*'}|{device_value or '*'}"


class PermissionStore:
    def __init__(
        self,
        db: Session,
        *,
        session_store: dict[str, dict[str, bool]] | None = None,
    ) -> None:
        self.db = db
        self._session_store = (
            session_store if session_store is not None else _default_session_store
        )

    # --- writes -------------------------------------------------------
    def grant(
        self,
        principal_id: str,
        category: PermissionCategory,
        scope: PermissionScope,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        device: DeviceType | None = None,
    ) -> None:
        self._set(principal_id, category, True, scope, session_id, tool_name, device)

    def revoke(
        self,
        principal_id: str,
        category: PermissionCategory,
        scope: PermissionScope,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        device: DeviceType | None = None,
    ) -> None:
        """Explicit denial -- distinct from simply never having granted.
        A revoked permission is remembered as DENIED, not reset to
        UNSET, so a later check correctly reports "explicitly denied"."""
        self._set(principal_id, category, False, scope, session_id, tool_name, device)

    def _set(
        self,
        principal_id: str,
        category: PermissionCategory,
        granted: bool,
        scope: PermissionScope,
        session_id: str | None,
        tool_name: str | None,
        device: DeviceType | None,
    ) -> None:
        if scope == PermissionScope.SESSION:
            if not session_id:
                raise ValueError("session_id is required for SESSION-scoped permissions")
            bucket = self._session_store.setdefault(session_id, {})
            bucket[_key(category, tool_name, device)] = granted
        else:
            record = PermissionRecord(
                principal_id=principal_id,
                category=category.value,
                tool_name=tool_name,
                device=device.value if device else None,
                granted=granted,
            )
            self.db.add(record)
            self.db.commit()
        logger.info(
            "Permission %s: category=%s tool=%s device=%s scope=%s",
            "granted" if granted else "revoked",
            category.value,
            tool_name,
            device.value if device else None,
            scope.value,
        )

    # --- reads ----------------------------------------------------------
    def check(
        self,
        principal_id: str,
        category: PermissionCategory,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        device: DeviceType | None = None,
    ) -> PermissionStatus:
        """Session grants/denials take priority over persistent ones when
        a session_id is supplied (an explicit in-session decision should
        win over a stale persistent one). Falls back to persistent, then
        UNSET if nothing has ever been recorded."""
        if session_id:
            bucket = self._session_store.get(session_id, {})
            # Specific (tool_name/device) key first, then category-wide.
            for candidate_tool, candidate_device in (
                (tool_name, device),
                (None, None),
            ):
                key = _key(category, candidate_tool, candidate_device)
                if key in bucket:
                    return PermissionStatus.GRANTED if bucket[key] else PermissionStatus.DENIED

        return self._check_persistent(principal_id, category, tool_name, device)

    def _check_persistent(
        self,
        principal_id: str,
        category: PermissionCategory,
        tool_name: str | None,
        device: DeviceType | None,
    ) -> PermissionStatus:
        device_value = device.value if device else None
        for candidate_tool, candidate_device in (
            (tool_name, device_value),
            (None, None),
        ):
            stmt = (
                select(PermissionRecord)
                .where(PermissionRecord.principal_id == principal_id)
                .where(PermissionRecord.category == category.value)
                .where(PermissionRecord.tool_name == candidate_tool)
                .where(PermissionRecord.device == candidate_device)
                .order_by(PermissionRecord.created_at.desc(), PermissionRecord.id.desc())
                .limit(1)
            )
            row = self.db.scalars(stmt).first()
            if row is not None:
                return PermissionStatus.GRANTED if row.granted else PermissionStatus.DENIED
        return PermissionStatus.UNSET

    def clear_session(self, principal_id: str, session_id: str) -> None:
        self._session_store.pop(session_id, None)
