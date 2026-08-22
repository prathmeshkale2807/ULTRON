"""
Task lifecycle audit log.

Records task-level events (created, state changes, cancellation,
emergency stop, tool steps, verification) in the task_audit_entries
table. This is separate from AuditLogEntry (per-tool-call decisions)
and PermissionAuditEntry (management decisions).

`detail` is capped at 512 chars and passed through redact_detail() so
this logger can never become a secrets sink even with an unexpected
caller mistake.
"""

from __future__ import annotations

from app.audit.log import redact_detail
from app.core.database import TaskAuditEntry
from app.core.logging_config import get_logger
from sqlalchemy.orm import Session

logger = get_logger("tasks.audit")

_MAX_DETAIL = 512


class TaskAuditLogger:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        task_id: str,
        event: str,
        detail: object = "",
        actor: str = "system",
    ) -> TaskAuditEntry:
        safe_detail = redact_detail(detail)
        if len(safe_detail) > _MAX_DETAIL:
            safe_detail = safe_detail[:_MAX_DETAIL - 3] + "..."
        entry = TaskAuditEntry(
            task_id=task_id[:64],
            event=event[:64],
            detail=safe_detail,
            actor=actor[:128],
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        logger.info(
            "TASK_AUDIT task_id=%s event=%s actor=%s",
            task_id,
            event,
            actor,
        )
        return entry
