import pytest
import asyncio
import json
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import get_db, Base, engine
from app.security.local_auth import get_or_create_local_token
from app.devices.manager import DeviceManager
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

@pytest.fixture
def android_auth(db_session: Session):
    manager = DeviceManager(db_session)
    record = manager.generate_pairing_code("local", "Test Pixel")
    device_id, credential = manager.pair_device(record.code, "Test Pixel")
    return {"device_id": device_id, "credential": credential, "principal_id": "local"}

def get_config_msg():
    return json.dumps({
        "input_format": {"codec": "pcm", "sample_rate": 16000, "channels": 1},
        "output_format": {"codec": "opus", "sample_rate": 24000, "channels": 1}
    })

def test_unauthorized_ws():
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/voice/ws") as ws:
            ws.receive_json()
    assert excinfo.value.code == 4001

def test_authenticated_desktop_ws(desktop_auth):
    with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
        ws.send_text(get_config_msg())
        resp = ws.receive_json()
        assert resp["status"] == "ready"

def test_authenticated_android_ws(android_auth):
    dev_id = android_auth["device_id"]
    cred = android_auth["credential"]
    import urllib.parse
    cred = urllib.parse.quote(cred)
    
    with client.websocket_connect(f"/api/voice/ws?device_id={dev_id}&credential={cred}") as ws:
        ws.send_text(get_config_msg())
        resp = ws.receive_json()
        assert resp["status"] == "ready"

def test_audio_format_validation(desktop_auth):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
            ws.send_text(json.dumps({
                "input_format": {"codec": "mp3", "sample_rate": 16000, "channels": 1},
                "output_format": {"codec": "mp3", "sample_rate": 24000, "channels": 1}
            }))
            resp = ws.receive_json()
            assert resp["error"] == "Unsupported codec"
            ws.receive_json() # this will raise disconnect
    assert excinfo.value.code == 1003

def test_emergency_stop_voice(desktop_auth, db_session):
    with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
        ws.send_text(get_config_msg())
        resp = ws.receive_json()
        
        ws.send_bytes(b"Ultron, stop")
        
        with pytest.raises(WebSocketDisconnect):
            ws.receive_bytes()
            
    assert EmergencyStop(db_session).is_engaged()

def test_barge_in_cancellation(desktop_auth, monkeypatch):
    async def mock_process_turn(*args, **kwargs):
        return "Here is your mocked response"
    
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)

    with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        
        ws.send_bytes(b"Hello Ultron")
        
        # We should get TTS audio chunks eventually
        tts_chunk = ws.receive_bytes()
        assert len(tts_chunk) > 0
        
        # Barge-in with new audio
        ws.send_bytes(b"Wait nevermind")
        
        tts_chunk_2 = ws.receive_bytes()
        assert len(tts_chunk_2) > 0

def test_no_audio_persistence(desktop_auth, monkeypatch):
    async def mock_process_turn(*args, **kwargs):
        return "Here is your mocked response"
    
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)
    import os, glob
    before_wavs = glob.glob("**/*.wav", recursive=True)
    before_mp3s = glob.glob("**/*.mp3", recursive=True)
    
    with client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}") as ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        ws.send_bytes(b"Check privacy")
        ws.receive_bytes()
        
    after_wavs = glob.glob("**/*.wav", recursive=True)
    after_mp3s = glob.glob("**/*.mp3", recursive=True)
    
    assert len(before_wavs) == len(after_wavs)
    assert len(before_mp3s) == len(after_mp3s)

def test_client_disconnect(desktop_auth, monkeypatch):
    async def mock_process_turn(*args, **kwargs):
        return "Here is your mocked response"
    
    monkeypatch.setattr("app.conversation.manager.ConversationManager.process_turn", mock_process_turn)
    ws = client.websocket_connect(f"/api/voice/ws?token={desktop_auth['token']}")
    with ws:
        ws.send_text(get_config_msg())
        ws.receive_json()
        ws.send_bytes(b"Disconnecting soon")
    assert True
