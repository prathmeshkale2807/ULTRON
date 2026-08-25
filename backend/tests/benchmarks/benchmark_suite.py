import time
import uuid
import asyncio
import statistics
from typing import Callable, Awaitable
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal, TaskRecord, engine
from app.tasks.manager import TaskManager
from app.security.local_auth import Principal, require_local_auth

# Mock auth
app.dependency_overrides[require_local_auth] = lambda: Principal(identity="test_principal")

client = TestClient(app)

def measure(name: str, func: Callable, iterations: int = 100):
    latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        latencies.append((time.perf_counter() - start) * 1000) # ms
    
    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
    
    print(f"[{name}] (n={iterations}) p50: {p50:.2f}ms, p95: {p95:.2f}ms, p99: {p99:.2f}ms")

async def measure_async(name: str, func: Callable[[], Awaitable], iterations: int = 100):
    latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        await func()
        latencies.append((time.perf_counter() - start) * 1000)
        
    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
    
    print(f"[{name}] (n={iterations}) p50: {p50:.2f}ms, p95: {p95:.2f}ms, p99: {p99:.2f}ms")

def run_benchmarks():
    from app.core.database import Base
    Base.metadata.create_all(engine)
    
    # 1. DB transaction latency
    def db_trans():
        with SessionLocal() as db:
            task = TaskRecord(task_id=str(uuid.uuid4()), principal_id="test", session_id="test")
            db.add(task)
            db.commit()
            db.query(TaskRecord).filter_by(task_id=task.task_id).first()
            
    measure("DB Transaction (Sync)", db_trans, 100)
    
    # 2. TaskManager throughput
    def task_manager_create():
        with SessionLocal() as db:
            tm = TaskManager(db)
            from app.tasks.models import TaskPriority
            tm.create(session_id="test_session", description="bench task", priority=TaskPriority.NORMAL, tools_requested=[], actor="test")
            
    measure("TaskManager.create (Sync)", task_manager_create, 100)
    
    # 3. API Overhead (creates a task)
    def api_overhead():
        client.post("/api/sessions", json={"device_id": "test", "ttl_seconds": 3600})
        # client.post("/api/tasks", json={"session_id": "test", "description": "bench", "priority": "normal"})
        # We just test health for pure overhead
        client.get("/health")
        
    measure("API Request (Sync client)", api_overhead, 100)

if __name__ == "__main__":
    run_benchmarks()
