import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from app.automations.models import AutomationType, MisfirePolicy, AutomationStatus, RunStatus, AutomationRecord, AutomationRunRecord
from app.automations.manager import AutomationManager
from app.automations.schemas import AutomationCreate, TaskDefinition, AutomationUpdate
from app.automations.scheduler import SchedulerEngine
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.database import SessionLocal
from app.tools.registry import get_registry
from app.tools.models import ToolDefinition, RiskLevel, PermissionCategory, ConfirmationTier, VerificationMethod, DeviceType

@pytest.fixture(autouse=True)
def setup_dummy_tool():
    registry = get_registry()
    dummy = ToolDefinition(
        name="windows_get_system_info",
        description="dummy",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        handler=lambda x: None,
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.SCHEDULING,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        verification_method=VerificationMethod.NONE,
        allowed_devices=[DeviceType.SERVER],
        schema_version="1.0"
    )
    registry.register(dummy, replace=True)
    yield
    registry.clear()

@pytest.fixture
def automation_manager(db_session: Session):
    return AutomationManager(db_session)

def test_crud_automation(automation_manager: AutomationManager, db_session: Session):
    principal = "test_user"
    
    # Create
    create_data = AutomationCreate(
        name="Test Auto",
        automation_type=AutomationType.DELAY,
        schedule_definition={"delay_seconds": 3600},
        task_definition=TaskDefinition(tool_name="windows_get_system_info", tool_args={})
    )
    
    record = automation_manager.create_automation(principal, create_data)
    assert record.id is not None
    assert record.status == AutomationStatus.ACTIVE
    
    # Get
    fetched = automation_manager.get_automation(principal, record.id)
    assert fetched.id == record.id
    
    # Update
    update_data = AutomationUpdate(name="Updated Name")
    updated = automation_manager.update_automation(principal, record.id, update_data)
    assert updated.name == "Updated Name"
    
    # Delete
    automation_manager.delete_automation(principal, record.id)
    with pytest.raises(Exception):
        automation_manager.get_automation(principal, record.id)

def test_cron_next_run(automation_manager: AutomationManager):
    principal = "test_user"
    create_data = AutomationCreate(
        name="Cron Auto",
        automation_type=AutomationType.CRON,
        schedule_definition={"cron": "0 8 * * *"}, # 8 AM UTC
        task_definition=TaskDefinition(tool_name="windows_get_system_info", tool_args={})
    )
    record = automation_manager.create_automation(principal, create_data)
    assert record.next_run_at is not None
    assert record.next_run_at.hour == 8

def test_idempotency_constraint(automation_manager: AutomationManager, db_session: Session):
    principal = "test_user"
    create_data = AutomationCreate(
        name="Idempotent Auto",
        automation_type=AutomationType.DELAY,
        schedule_definition={"delay_seconds": 3600},
        task_definition=TaskDefinition(tool_name="windows_get_system_info", tool_args={})
    )
    auto = automation_manager.create_automation(principal, create_data)
    
    # Try inserting two runs with the same idempotency key
    run1 = AutomationRunRecord(
        automation_id=auto.id,
        automation_version=1,
        principal_id="user1",
        scheduled_for=datetime.now(timezone.utc),
        idempotency_key="unique_key_123"
    )
    db_session.add(run1)
    db_session.commit()
    
    run2 = AutomationRunRecord(
        automation_id=auto.id,
        automation_version=1,
        principal_id="user1",
        scheduled_for=datetime.now(timezone.utc),
        idempotency_key="unique_key_123"
    )
    db_session.add(run2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

@pytest.mark.asyncio
async def test_scheduler_atomic_claims(db_session: Session, automation_manager: AutomationManager):
    principal = "test_user"
    create_data = AutomationCreate(
        name="Delay Auto",
        automation_type=AutomationType.DELAY,
        schedule_definition={"delay_seconds": 10},
        task_definition=TaskDefinition(tool_name="windows_get_system_info", tool_args={})
    )
    auto = automation_manager.create_automation(principal, create_data)
    
    # Make it due
    auto.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    
    engine = SchedulerEngine()
    engine._generate_due_runs(db_session)
    
    runs = db_session.execute(select(AutomationRunRecord)).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == RunStatus.SCHEDULED
    
    # Claim should succeed
    engine._claim_and_submit_runs(db_session)
    db_session.refresh(runs[0])
    if runs[0].status == RunStatus.FAILED:
        print(f"FAILED ERROR: {runs[0].error_summary}")
    assert runs[0].status == RunStatus.SUBMITTED
    assert runs[0].claim_token is not None
