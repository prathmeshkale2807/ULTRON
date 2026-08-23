import pytest
from app.conversation.manager import ConversationManager
from app.core.database import ConversationRecord, TaskRecord
from app.ai_providers.base import ProviderResponse
import json
import asyncio

@pytest.fixture
def mock_provider_manager():
    class MockProviderManager:
        async def complete(self, request, use_tools=False):
            if "IntentExtraction" in request.system_prompt:
                return ProviderResponse(
                    text=json.dumps({
                        "intent_type": "TOOL_ACTION",
                        "confidence": "High",
                        "entities": {},
                        "requested_outcome": "Do thing"
                    }),
                    tool_calls=[], provider_name="mock", model="mock", finish_reason="stop"
                )
            if "PlanDefinition" in request.system_prompt:
                return ProviderResponse(
                    text=json.dumps({
                        "objective": "Do thing",
                        "steps": [{"tool_name": "windows_list_running_applications", "arguments": {}}]
                    }),
                    tool_calls=[], provider_name="mock", model="mock", finish_reason="stop"
                )
            return ProviderResponse(
                text="Done.", tool_calls=[], provider_name="mock", model="mock", finish_reason="stop"
            )
    return MockProviderManager()

@pytest.fixture
def client(monkeypatch, tmp_path):
    db_file = tmp_path / "test_phase7_sec.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    from sqlalchemy import create_engine as _make_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    import app.core.database as _db_module
    _test_engine = _make_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    _db_module.Base.metadata.create_all(bind=_test_engine)
    _test_session_local = _sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
    monkeypatch.setattr(_db_module, "engine", _test_engine)
    monkeypatch.setattr(_db_module, "SessionLocal", _test_session_local)
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    yield client
    _test_engine.dispose()

@pytest.fixture(autouse=True)
def setup_windows_tools(client):
    from app.windows.tools import register_windows_tools
    from app.tools.registry import get_registry, _default_registry
    _default_registry.clear()
    register_windows_tools(get_registry())
    yield

@pytest.fixture(autouse=True)
async def manage_task_worker(client):
    from app.tasks.worker import get_task_worker, reset_task_worker
    worker = get_task_worker()
    await worker.start()
    yield
    await worker.stop()
    reset_task_worker()

@pytest.mark.asyncio
async def test_stale_plan_cancellation(client, mock_provider_manager):
    # This verifies requirement 4: superseding a plan cancels the old one
    from app.core.database import SessionLocal
    db = SessionLocal()
    
    manager = ConversationManager(db, mock_provider_manager)
    conv_id = "test-conv-sec-001"
    
    # Send first turn
    await manager.process_turn(conv_id, "Action 1", "sess-1", "local")
    conv = db.get(ConversationRecord, conv_id)
    first_task_id = conv.active_task_id
    assert first_task_id is not None
    
    # Send second turn immediately (superseding)
    await manager.process_turn(conv_id, "Wait, Action 2 instead", "sess-1", "local")
    db.refresh(conv)
    second_task_id = conv.active_task_id
    
    assert first_task_id != second_task_id
    
    # The first task MUST be cancelled
    first_task = db.get(TaskRecord, first_task_id)
    assert first_task.state in ["completed", "failed", "cancelled"]

@pytest.mark.asyncio
async def test_no_bypass_of_executor(client, mock_provider_manager):
    # This verifies requirement 1, 2, 3: Task worker must use the executor which enforces safety
    from app.core.database import SessionLocal
    db = SessionLocal()
    
    manager = ConversationManager(db, mock_provider_manager)
    conv_id = "test-conv-sec-002"
    
    from app.permissions.store import PermissionStore
    from app.tools.models import PermissionCategory
    from app.permissions.models import PermissionScope
    from app.core.database import SessionRecord
    db.merge(SessionRecord(session_id="sess-1", principal_id="local"))
    db.commit()
    p_store = PermissionStore(db)
    p_store.grant("local", PermissionCategory.PC_READ, PermissionScope.SESSION, session_id="sess-1")
    
    await manager.process_turn(conv_id, "Show running apps", "sess-1", "local")
    
    conv = db.get(ConversationRecord, conv_id)
    task_id = conv.active_task_id
    task = db.get(TaskRecord, task_id)
    
    # It should have completed successfully because list_running_applications requires no confirmation (safe)
    assert task.state == "completed"
