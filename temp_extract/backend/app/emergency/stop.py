from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import EmergencyStopRecord
from app.core.logging_config import get_logger

logger = get_logger("emergency.stop")

_SINGLETON_ID = 1


class EmergencyStopStatus(BaseModel):
    engaged: bool
    reason: str
    activated_by: str
    updated_at: datetime | None


class EmergencyStop:
    """DB-backed activate/reset/status. A single row (id=1) is the
    source of truth so every process sharing this database agrees on
    whether the stop is engaged, including after a restart."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_or_create_row(self) -> EmergencyStopRecord:
        row = self.db.get(EmergencyStopRecord, _SINGLETON_ID)
        if row is None:
            row = EmergencyStopRecord(
                id=_SINGLETON_ID,
                engaged=False,
                reason="",
                activated_by="",
                updated_at=datetime.now(timezone.utc),
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    def activate(self, *, reason: str = "", activated_by: str = "unknown") -> EmergencyStopStatus:
        row = self._get_or_create_row()
        row.engaged = True
        row.reason = reason[:512]
        row.activated_by = activated_by[:128]
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        logger.warning("EMERGENCY STOP ACTIVATED by=%s reason=%s", activated_by, reason)
        return self.status()

    def reset(self, *, reset_by: str = "unknown") -> EmergencyStopStatus:
        row = self._get_or_create_row()
        row.engaged = False
        row.reason = ""
        row.activated_by = ""
        row.updated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        logger.warning("Emergency stop reset by=%s", reset_by)
        return self.status()

    def status(self) -> EmergencyStopStatus:
        row = self._get_or_create_row()
        return EmergencyStopStatus(
            engaged=row.engaged,
            reason=row.reason,
            activated_by=row.activated_by,
            updated_at=row.updated_at,
        )

    def is_engaged(self) -> bool:
        return self.status().engaged
