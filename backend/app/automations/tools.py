from typing import Any
from datetime import datetime, timezone
from app.tools.models import (
    ConfirmationTier,
    DeviceType,
    PermissionCategory,
    RiskLevel,
    ToolDefinition,
    VerificationMethod,
    ExecutionContext
)
from app.automations.schemas import AutomationCreate, TaskDefinition
from app.automations.models import AutomationType
from app.automations.manager import AutomationManager, AutomationError
from app.core.database import SessionLocal

async def handle_create_automation(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    principal_id = ctx.principal_id
    if not principal_id:
        return {"status": "error", "error": "principal_id is required"}

    try:
        # Construct schedule definition
        sched_def = {}
        auto_type = AutomationType(arguments.get("automation_type", "ONE_TIME"))
        
        if auto_type == AutomationType.ONE_TIME:
            sched_def["scheduled_time"] = arguments.get("scheduled_time")
        elif auto_type == AutomationType.DELAY:
            sched_def["delay_seconds"] = arguments.get("delay_seconds")
        elif auto_type in (AutomationType.CRON, AutomationType.RECURRING):
            sched_def["cron"] = arguments.get("cron_expression")
            
        task_def = TaskDefinition(
            tool_name=arguments.get("task_tool_name"),
            tool_args=arguments.get("task_tool_args", {})
        )

        auto_create = AutomationCreate(
            name=arguments.get("name"),
            automation_type=auto_type,
            schedule_definition=sched_def,
            timezone=arguments.get("timezone", "UTC"),
            task_definition=task_def
        )

        with SessionLocal() as db:
            mgr = AutomationManager(db)
            record = mgr.create_automation(principal_id, auto_create)
            return {
                "status": "success",
                "automation_id": record.id,
                "name": record.name,
                "next_run_at": record.next_run_at.isoformat() if record.next_run_at else None
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}

tool_create_automation = ToolDefinition(
    name="create_automation",
    description="Schedules a task to run automatically in the future.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "automation_type": {"type": "string", "enum": ["ONE_TIME", "RECURRING", "CRON", "DELAY"]},
            "scheduled_time": {"type": "string", "description": "ISO timestamp for ONE_TIME automations"},
            "delay_seconds": {"type": "integer", "description": "Seconds for DELAY automations"},
            "cron_expression": {"type": "string", "description": "Cron string for CRON/RECURRING"},
            "timezone": {"type": "string", "default": "UTC"},
            "task_tool_name": {"type": "string", "description": "Name of the tool to execute"},
            "task_tool_args": {"type": "object", "description": "Arguments for the tool"}
        },
        "required": ["name", "automation_type", "task_tool_name", "task_tool_args"]
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "automation_id": {"type": "string"},
            "name": {"type": "string"},
            "next_run_at": {"type": "string"}
        }
    },
    handler=handle_create_automation,
    risk_level=RiskLevel.LOW, # Creating the automation is LOW; the actual execution evaluates the tool's risk!
    permission_category=PermissionCategory.SCHEDULING,
    confirmation_tier=ConfirmationTier.AUTOMATIC,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.SERVER],
    schema_version="1.0"
)

AUTOMATION_TOOLS = [tool_create_automation]
