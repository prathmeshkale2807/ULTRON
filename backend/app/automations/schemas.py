from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field

from app.automations.models import AutomationType, MisfirePolicy, AutomationStatus, RunStatus

class TaskDefinition(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any]

class AutomationCreate(BaseModel):
    name: str
    automation_type: AutomationType
    schedule_definition: Dict[str, Any]
    misfire_policy: MisfirePolicy = MisfirePolicy.SKIP
    timezone: str = "UTC"
    task_definition: TaskDefinition
    max_runs: Optional[int] = None
    expires_at: Optional[datetime] = None

class AutomationUpdate(BaseModel):
    name: Optional[str] = None
    schedule_definition: Optional[Dict[str, Any]] = None
    misfire_policy: Optional[MisfirePolicy] = None
    timezone: Optional[str] = None
    task_definition: Optional[TaskDefinition] = None
    max_runs: Optional[int] = None
    expires_at: Optional[datetime] = None

class AutomationResponse(BaseModel):
    id: str
    principal_id: str
    name: str
    automation_type: AutomationType
    schedule_definition: Dict[str, Any]
    misfire_policy: MisfirePolicy
    timezone: str
    task_definition: Dict[str, Any]
    status: AutomationStatus
    next_run_at: Optional[datetime]
    last_run_at: Optional[datetime]
    run_count: int
    max_runs: Optional[int]
    automation_version: int
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime]

    class Config:
        orm_mode = True

class AutomationRunResponse(BaseModel):
    id: str
    automation_id: str
    automation_version: int
    principal_id: str
    scheduled_for: datetime
    status: RunStatus
    task_id: Optional[str]
    idempotency_key: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    error_summary: Optional[str]

    class Config:
        orm_mode = True
