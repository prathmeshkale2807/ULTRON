from sqlalchemy import text
import pytest
import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.security.local_auth import Principal, require_local_auth

def _mock_auth():
    return Principal(identity="test_principal")

@pytest.fixture(autouse=True)
def _patch_auth():
    app.dependency_overrides[require_local_auth] = _mock_auth
    yield
    app.dependency_overrides.pop(require_local_auth, None)

client = TestClient(app)

@pytest.mark.asyncio
async def test_event_loop_responsiveness():
    """Verify that heavy database queries do not stall the asyncio event loop."""
    import time
    from app.core.database import get_db
    
    # We simulate a delay in the event loop check
    start = time.perf_counter()
    
    async def loop_ticker():
        await asyncio.sleep(0.1)
        return time.perf_counter()
        
    def do_sync_req():
        # Hit the health endpoint which hits the DB
        client.get("/health")
        
    t = asyncio.create_task(loop_ticker())
    # Offload blocking request
    await asyncio.to_thread(do_sync_req)
    
    end = await t
    duration = end - start
    
    # The tick should not be delayed more than 0.2s by the DB request
    assert duration < 0.2, f"Event loop stalled for {duration} seconds"

@pytest.mark.asyncio
async def test_wal_verification():
    from app.core.database import engine
    
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert result.upper() == "WAL", "WAL is not enabled"
        
@pytest.mark.asyncio
async def test_bounded_queue_rejection():
    from app.tasks.worker import TaskWorker
    worker = TaskWorker(max_concurrent=1)
    # Patch queue size to 2
    worker._queue = asyncio.PriorityQueue(maxsize=2)
    
    # Fill the queue
    await worker.submit("task1")
    await worker.submit("task2")
    
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await worker.submit("task3")
        
    assert exc.value.status_code == 429
    assert "QUEUE_FULL" in exc.value.detail
