import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, update
import zoneinfo

# We will import croniter when needed. It should be available.
from croniter import croniter

from app.automations.models import (
    AutomationRecord, 
    AutomationType, 
    AutomationStatus, 
    MisfirePolicy,
    RunStatus,
    AutomationRunRecord
)
from app.automations.schemas import AutomationCreate, AutomationUpdate
from app.tools.registry import get_registry

class AutomationError(Exception):
    pass

class AutomationManager:
    def __init__(self, db: Session):
        self.db = db

    def _calculate_next_run(self, automation_type: AutomationType, schedule_def: dict, tz_name: str, start_time: datetime) -> Optional[datetime]:
        """Calculates the next run time in UTC based on the schedule and timezone."""
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except zoneinfo.ZoneInfoNotFoundError:
            raise AutomationError(f"Invalid timezone: {tz_name}")

        # Ensure start_time is UTC and convert to the target timezone for evaluation
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        start_time_loc = start_time.astimezone(tz)

        if automation_type == AutomationType.ONE_TIME:
            # ONE_TIME expects an exact ISO timestamp in 'scheduled_time'
            scheduled_str = schedule_def.get("scheduled_time")
            if not scheduled_str:
                raise AutomationError("ONE_TIME requires 'scheduled_time' in schedule_definition.")
            try:
                dt = datetime.fromisoformat(scheduled_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz) # Assume local if naive
                next_time_utc = dt.astimezone(timezone.utc)
                if next_time_utc <= start_time:
                    raise AutomationError("ONE_TIME scheduled_time must be in the future.")
                return next_time_utc
            except ValueError:
                raise AutomationError("Invalid scheduled_time format. Use ISO format.")

        elif automation_type == AutomationType.DELAY:
            # DELAY expects 'delay_seconds'
            delay_sec = schedule_def.get("delay_seconds")
            if not isinstance(delay_sec, (int, float)) or delay_sec <= 0:
                raise AutomationError("DELAY requires a positive 'delay_seconds'.")
            return start_time + timedelta(seconds=delay_sec)

        elif automation_type == AutomationType.CRON or automation_type == AutomationType.RECURRING:
            # CRON expects 'cron' expression
            cron_expr = schedule_def.get("cron")
            if not cron_expr:
                raise AutomationError("CRON/RECURRING requires 'cron' string in schedule_definition.")
            try:
                # croniter handles DST transitions correctly if given the tz-aware start_time_loc
                itr = croniter(cron_expr, start_time_loc)
                next_time_loc = itr.get_next(datetime)
                return next_time_loc.astimezone(timezone.utc)
            except Exception as e:
                raise AutomationError(f"Invalid CRON expression: {str(e)}")

        elif automation_type == AutomationType.CONDITION:
            raise NotImplementedError("CONDITION type automations are not currently implemented.")

        raise AutomationError(f"Unsupported automation type: {automation_type}")

    def create_automation(self, principal_id: str, data: AutomationCreate) -> AutomationRecord:
        if data.automation_type == AutomationType.CONDITION:
            raise NotImplementedError("CONDITION type automations are not currently implemented.")
            
        # Validate tool definition
        registry = get_registry()
        tool_name = data.task_definition.tool_name
        try:
            tool = registry.get(tool_name)
        except Exception:
            raise AutomationError(f"Tool '{tool_name}' is not registered.")
        
        # Using jsonschema to validate args
        import jsonschema
        try:
            jsonschema.validate(instance=data.task_definition.tool_args, schema=tool.input_schema)
        except Exception as e:
            raise AutomationError(f"Invalid task_definition tool_args: {str(e)}")

        now_utc = datetime.now(timezone.utc)
        next_run = self._calculate_next_run(data.automation_type, data.schedule_definition, data.timezone, now_utc)

        record = AutomationRecord(
            principal_id=principal_id,
            name=data.name,
            automation_type=data.automation_type,
            schedule_definition=data.schedule_definition,
            misfire_policy=data.misfire_policy,
            timezone=data.timezone,
            task_definition=data.task_definition.dict(),
            next_run_at=next_run,
            max_runs=data.max_runs,
            expires_at=data.expires_at
        )

        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_automation(self, principal_id: str, automation_id: str) -> AutomationRecord:
        record = self.db.execute(
            select(AutomationRecord)
            .where(AutomationRecord.id == automation_id)
            .where(AutomationRecord.principal_id == principal_id)
        ).scalar_one_or_none()
        if not record:
            raise AutomationError("Automation not found or not owned by principal.")
        return record

    def update_automation(self, principal_id: str, automation_id: str, data: AutomationUpdate) -> AutomationRecord:
        record = self.get_automation(principal_id, automation_id)
        
        has_schedule_change = False
        
        if data.name is not None:
            record.name = data.name
        if data.misfire_policy is not None:
            record.misfire_policy = data.misfire_policy
        if data.max_runs is not None:
            record.max_runs = data.max_runs
        if data.expires_at is not None:
            record.expires_at = data.expires_at
            
        if data.timezone is not None:
            record.timezone = data.timezone
            has_schedule_change = True
            
        if data.schedule_definition is not None:
            record.schedule_definition = data.schedule_definition
            has_schedule_change = True
            
        if data.task_definition is not None:
            # Validate new task definition
            registry = get_registry()
            tool_name = data.task_definition.tool_name
            try:
                tool = registry.get(tool_name)
            except Exception:
                raise AutomationError(f"Tool '{tool_name}' is not registered.")
            import jsonschema
            try:
                jsonschema.validate(instance=data.task_definition.tool_args, schema=tool.input_schema)
            except Exception as e:
                raise AutomationError(f"Invalid task_definition tool_args: {str(e)}")
            
            record.task_definition = data.task_definition.dict()
            has_schedule_change = True # Treat as significant change needing version bump

        if has_schedule_change:
            # Increment version to invalidate stale runs
            record.automation_version += 1
            # Recompute next_run_at based on current time
            now_utc = datetime.now(timezone.utc)
            record.next_run_at = self._calculate_next_run(
                record.automation_type, 
                record.schedule_definition, 
                record.timezone, 
                now_utc
            )
            # Cancel pending SCHEDULED runs for this automation
            self.db.execute(
                update(AutomationRunRecord)
                .where(AutomationRunRecord.automation_id == record.id)
                .where(AutomationRunRecord.status == RunStatus.SCHEDULED)
                .values(status=RunStatus.CANCELLED, error_summary="Cancelled due to automation edit")
            )
            
        self.db.commit()
        self.db.refresh(record)
        return record

    def delete_automation(self, principal_id: str, automation_id: str) -> None:
        record = self.get_automation(principal_id, automation_id)
        # Also cancel all scheduled runs (Cascade delete handles records, but we might want to keep history and just set status if we didn't cascade. Here we cascade ondelete)
        self.db.delete(record)
        self.db.commit()

    def set_status(self, principal_id: str, automation_id: str, status: AutomationStatus) -> AutomationRecord:
        record = self.get_automation(principal_id, automation_id)
        if record.status != status:
            record.status = status
            if status == AutomationStatus.PAUSED or status == AutomationStatus.CANCELLED:
                # Cancel pending scheduled runs
                self.db.execute(
                    update(AutomationRunRecord)
                    .where(AutomationRunRecord.automation_id == record.id)
                    .where(AutomationRunRecord.status == RunStatus.SCHEDULED)
                    .values(status=RunStatus.CANCELLED, error_summary=f"Cancelled due to automation status change: {status.value}")
                )
            self.db.commit()
            self.db.refresh(record)
        return record
