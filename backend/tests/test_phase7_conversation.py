import pytest
from unittest.mock import AsyncMock
from app.conversation.manager import ConversationManager
from app.core.database import ConversationRecord
from app.ai_providers.base import ProviderResponse
from app.conversation.schemas import ConversationStateEnum
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
                        "entities": {"app": "notepad"},
                        "requested_outcome": "Open notepad"
                    }),
                    tool_calls=[],
                    provider_name="mock",
                    model="mock",
                    finish_reason="stop"
                )
            if "PlanDefinition" in request.system_prompt:
                return ProviderResponse(
                    text=json.dumps({
                        "objective": "Open notepad",
                        "steps": [{"tool_name": "open_application", "arguments": {"app_name": "notepad"}}]
                    }),
                    tool_calls=[],
                    provider_name="mock",
                    model="mock",
                    finish_reason="stop"
                )
            return ProviderResponse(
                text="Done.",
                tool_calls=[],
                provider_name="mock",
                model="mock",
                finish_reason="stop"
            )
    return MockProviderManager()

@pytest.fixture
def client(monkeypatch, tmp_path):
    db_file = tmp_path / "test_phase7_conv.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    from app.core.database import create_all_for_tests
    create_all_for_tests()
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

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
async def test_conversation_flow(client, mock_provider_manager):
    from app.core.database import SessionLocal
    db = SessionLocal()
    manager = ConversationManager(db, mock_provider_manager)
    conv_id = "test-conv-001"
    
    response = await manager.process_turn(conv_id, "Open notepad", "sess-1")
    assert response == "Done."
    
    conv = db.get(ConversationRecord, conv_id)
    assert conv is not None
    assert conv.active_task_id is not None

