import pytest
import asyncio
from sqlalchemy.orm import Session
from app.tasks.models import TaskState
from app.core.database import TaskRecord

@pytest.mark.asyncio
async def test_database_recovery_rollback(db_session: Session):
    # Create task
    row = TaskRecord(
        task_id="task_db_1",
        principal_id="user1",
        state=TaskState.QUEUED.value,
        tools_requested="[]"
    )
    db_session.add(row)
    db_session.commit()
    
    # Try an operation that throws, and rollback
    from sqlalchemy import text
    try:
        db_session.execute(text("UPDATE task_records SET state = 'invalid_state'"))
        db_session.execute(text("INSERT INTO non_existent_table VALUES (1)"))
        db_session.commit()
    except Exception:
        db_session.rollback()
        
    db_session.expire_all()
    # verify old state remains
    updated = db_session.get(TaskRecord, "task_db_1")
    assert updated.state == TaskState.QUEUED.value
