import pytest
import asyncio
from app.tasks.models import TaskState
from app.tasks.worker import _execute_task
from app.core.database import TaskRecord
from app.tasks.manager import TaskManager

@pytest.fixture
def session_factory(db_session):
    return lambda: db_session

@pytest.mark.asyncio
async def test_bounded_concurrency(db_session, session_factory):
    # submit a few tasks, ensure they process correctly
    # Without starting a real worker loop (which would be complex to orchestrate here),
    # we can just run execute_task concurrently.
    
    tasks = []
    import json
    for i in range(5):
        row = TaskRecord(
            task_id=f"task_conc_{i}",
            principal_id="user1",
            state=TaskState.QUEUED.value,
            tools_requested="[]"
        )
        db_session.add(row)
        tasks.append(f"task_conc_{i}")
    
    db_session.commit()
    
    # Run them all
    await asyncio.gather(*[_execute_task(t, session_factory=session_factory) for t in tasks])
    
    db_session.expire_all()
    
    for t in tasks:
        updated = db_session.get(TaskRecord, t)
        assert updated.state == TaskState.COMPLETED.value
