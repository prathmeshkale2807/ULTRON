import enum
from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
import uuid

from app.core.database import Base

class AutomationType(str, enum.Enum):
    ONE_TIME = "ONE_TIME"
    RECURRING = "RECURRING"
    CRON = "CRON"
    DELAY = "DELAY"
    CONDITION = "CONDITION"

class MisfirePolicy(str, enum.Enum):
    SKIP = "SKIP"
    CATCH_UP_ONCE = "CATCH_UP_ONCE"

class AutomationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class RunStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    CLAIMED = "CLAIMED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"

class AutomationRecord(Base):
    __tablename__ = "automation_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    principal_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    automation_type: Mapped[AutomationType] = mapped_column(Enum(AutomationType), nullable=False)
    schedule_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    misfire_policy: Mapped[MisfirePolicy] = mapped_column(Enum(MisfirePolicy), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    task_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[AutomationStatus] = mapped_column(Enum(AutomationStatus), nullable=False, default=AutomationStatus.ACTIVE)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_runs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    automation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class AutomationRunRecord(Base):
    __tablename__ = "automation_run_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    automation_id: Mapped[str] = mapped_column(String(64), ForeignKey("automation_records.id", ondelete="CASCADE"), nullable=False, index=True)
    automation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), nullable=False, default=RunStatus.SCHEDULED, index=True)
    
    claim_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    claim_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_summary: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        UniqueConstraint('idempotency_key', name='uq_automation_run_idempotency'),
    )
