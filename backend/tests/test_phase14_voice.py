import asyncio
import json
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import app
from app.security.local_auth import get_or_create_local_token
from app.voice.engine import VoiceSessionState
from app.emergency.stop import EmergencyStop
from app.core.database import get_db, Base, engine

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = next(get_db())
    yield session
    session.rollback()
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)

@pytest.fixture
def desktop_auth():
    token = get_or_create_local_token()
    return {"token": token}

def get_config_msg():
    return json.dumps({
        "input_format": {"codec": "pcm", "sample_rate": 16000, "channels": 1},
        "output_format": {"codec": "pcm", "sample_rate": 24000, "channels": 1}
    })

def test_configurable_timeout_default():
    from app.core.config import get_settings
    settings = get_settings()
    assert settings.voice_conversation_timeout_seconds == 15.0

def test_watchdog_timeout_in_listening(desktop_auth, db_session, monkeypatch):
    monkeypatch.setenv("VOICE_CONVERSATION_TIMEOUT_SECONDS", "0.5")
    from app.core.config import get_settings
    get_settings.cache_clear()
    
    with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_bytes()
        assert exc_info.value.code == 1000
    get_settings.cache_clear()

def test_graceful_exit_commands(desktop_auth, db_session, monkeypatch):
    commands = [b"goodbye", b"stop listening", b"exit conversation"]
    
    called = False
    async def mock_process_turn(*args, **kwargs):
        nonlocal called
        called = True
        return "Should not be called"
    
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)
    
    for cmd in commands:
        called = False
        with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
            ws.send_text(get_config_msg())
            ws.receive_json()
            
            ws.send_bytes(cmd)
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_bytes()
            assert exc_info.value.code == 1000
        assert called is False

def test_emergency_stop_kills_db(desktop_auth, db_session, monkeypatch):
    called = False
    async def mock_process_turn(*args, **kwargs):
        nonlocal called
        called = True
        return "Should not be called"
    
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)
    
    with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        
        ws.send_bytes(b"Ultron, emergency stop")
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_bytes()
        assert exc_info.value.code == 1000
    assert called is False
    
    status = EmergencyStop(db_session).status()
    assert status.engaged is True
    
    # reset
    EmergencyStop(db_session).reset()

def test_watchdog_suspended_during_processing_and_speaking(desktop_auth, db_session, monkeypatch):
    monkeypatch.setenv("VOICE_CONVERSATION_TIMEOUT_SECONDS", "0.5")
    from app.core.config import get_settings
    get_settings.cache_clear()
    
    async def mock_process_turn(*args, **kwargs):
        await asyncio.sleep(1.0) # > 0.5s timeout
        return "Response"
        
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)
    
    with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        
        ws.send_bytes(b"Some text")
        
        # It should yield audio after 1 second without timing out.
        chunk = ws.receive_bytes()
        assert chunk is not None
    
    get_settings.cache_clear()

def test_client_disconnect_cleanup(desktop_auth, db_session):
    with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
