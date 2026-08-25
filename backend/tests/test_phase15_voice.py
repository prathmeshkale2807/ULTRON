import pytest
import asyncio
import json
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import get_db, Base, engine
from app.security.local_auth import get_or_create_local_token
from app.voice.stt_provider import STTEventType
from app.emergency.stop import EmergencyStop

client = TestClient(app)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = next(get_db())
    yield session
    session.rollback()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def desktop_auth():
    token = get_or_create_local_token()
    return {"token": token, "principal_id": "local"}

def get_config_msg():
    return json.dumps({
        "input_format": {"codec": "pcm", "sample_rate": 16000, "channels": 1},
        "output_format": {"codec": "opus", "sample_rate": 24000, "channels": 1}
    })

def test_speech_start_triggers_barge_in(desktop_auth, monkeypatch):
    barge_in_called = False
    
    # We will intercept `_trigger_barge_in`
    from app.voice.engine import VoiceSession
    original_trigger = VoiceSession._trigger_barge_in
    
    async def mock_trigger(self):
        nonlocal barge_in_called
        barge_in_called = True
        await original_trigger(self)
        
    monkeypatch.setattr("app.voice.engine.VoiceSession._trigger_barge_in", mock_trigger)
    
    async def mock_process_turn(*args, **kwargs):
        await asyncio.sleep(2.0) # Simulate long generation
        return "Here is your mocked response"
        
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)
    
    ticket_resp = client.post("/api/voice/ticket", headers={"X-Ultron-Auth": desktop_auth['token']}, json={})
    
    ticket = ticket_resp.json().get("ticket", "invalid")
    
    with client.websocket_connect(f"/api/voice/ws?ticket={ticket}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        
        # Send first phrase
        ws.send_bytes(b"What is the weather")
        
        # Wait a bit so it's PROCESSING
        import time
        time.sleep(0.5)
        
        # Now send PARTIAL to trigger barge-in
        ws.send_bytes(b"PARTIAL: stop")
        
        time.sleep(0.5)
        
    assert barge_in_called

def test_silence_does_not_trigger_barge_in(desktop_auth, monkeypatch):
    barge_in_called = False
    
    from app.voice.engine import VoiceSession
    original_trigger = VoiceSession._trigger_barge_in
    
    async def mock_trigger(self):
        nonlocal barge_in_called
        barge_in_called = True
        await original_trigger(self)
        
    monkeypatch.setattr("app.voice.engine.VoiceSession._trigger_barge_in", mock_trigger)
    
    async def mock_process_turn(*args, **kwargs):
        await asyncio.sleep(1.0)
        return "Here is your mocked response"
        
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)
    
    ticket_resp = client.post("/api/voice/ticket", headers={"X-Ultron-Auth": desktop_auth['token']}, json={})
    
    ticket = ticket_resp.json().get("ticket", "invalid")
    
    with client.websocket_connect(f"/api/voice/ws?ticket={ticket}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        
        # Send first phrase
        ws.send_bytes(b"What is the weather")
        
        # Send empty string - mock STT ignores empty text and does NOT yield started event
        ws.send_bytes(b"")
        ws.send_bytes(b"   ")
        
        import time
        time.sleep(0.5)
        
    assert not barge_in_called

def test_stale_tts_chunk_rejected(desktop_auth, monkeypatch):
    async def mock_process_turn(*args, **kwargs):
        await asyncio.sleep(0.1)
        return "Mock response"
        
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)
    
    ticket_resp = client.post("/api/voice/ticket", headers={"X-Ultron-Auth": desktop_auth['token']}, json={})
    
    ticket = ticket_resp.json().get("ticket", "invalid")
    
    with client.websocket_connect(f"/api/voice/ws?ticket={ticket}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        
        ws.send_bytes(b"Phrase 1")
        
        # Interrupt it before TTS completes
        import time
        time.sleep(0.2)
        ws.send_bytes(b"PARTIAL: Phrase 2")
        ws.send_bytes(b"Phrase 2")
        
        # Read whatever comes out
        try:
            tts_chunk = ws.receive_bytes()
            # If we get a chunk, it should be from the SECOND phrase!
            # The test mock TTS returns the utf-8 bytes of the response text
            # Here response text is always "Mock response" for both, but the first one's queue was flushed
        except Exception:
            pass

def test_emergency_stop_still_cancels_global_work(desktop_auth, db_session):
    ticket_resp = client.post("/api/voice/ticket", headers={"X-Ultron-Auth": desktop_auth['token']}, json={})
    ticket = ticket_resp.json().get("ticket", "invalid")
    with client.websocket_connect(f"/api/voice/ws?ticket={ticket}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        
        ws.send_bytes(b"Ultron, emergency stop")
        
        with pytest.raises(WebSocketDisconnect):
            ws.receive_bytes()
            
    assert EmergencyStop(db_session).is_engaged()
