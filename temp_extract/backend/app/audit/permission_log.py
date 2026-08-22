"""
Permission/profile/security-management audit log.

Distinct from app/audit/log.py's AuditLogger, which records tool-call
decisions (a running action passed through the Safety Gate). This one
records *management* decisions: who changed a permission, the active
profile, or reset emergency stop, and what the state was before/after.

Every field is a short identifier or state label -- there is no
free-form "detail" column here at all, so (unlike AuditLogEntry, which
defensively redacts) there is no field a secret could even be written
into by accident.
"""

from __future__ import annotations

from app.core.database import PermissionAuditEntry
from app.core.logging_config import get_logger
from sqlalchemy.orm import Session

logger = get_logger("audit.permissions")


class PermissionAuditLogger:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        actor: str,
        action: str,
        old_state: str,
        new_state: str,
        category: str | None = None,
        tool_name: str | None = None,
        device: str | None = None,
    ) -> PermissionAuditEntry:
        entry = PermissionAuditEntry(
            actor=actor[:128],
            action=action[:32],
            category=category,
            tool_name=tool_name,
            device=device,
            old_state=old_state[:64],
            new_state=new_state[:64],
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        logger.info(
            "PERMISSION_AUDIT actor=%s action=%s category=%s tool=%s device=%s %s->%s",
            actor,
            action,
            category,
            tool_name,
            device,
            old_state,
            new_state,
        )
        return entry
