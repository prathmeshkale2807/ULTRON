import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import get_db, Base, engine
from app.devices.manager import DeviceManager

client = TestClient(app)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = next(get_db())
    yield session
    session.rollback()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def device(db_session: Session):
    manager = DeviceManager(db_session)
    record = manager.generate_pairing_code("principal-1", "Test Device")
    device_id, cred = manager.pair_device(record.code, "Test Device")
    return {"device_id": device_id, "credential": cred, "principal_id": "principal-1"}

def test_ws_authentication_success(device):
    dev_id = device["device_id"]
    cred = device["credential"]
    with client.websocket_connect(f"/api/devices/ws?device_id={dev_id}&credential={cred}") as websocket:
        # If it connects without raising WebSocketDisconnect(4001), it's successful
        assert True

def test_ws_authentication_invalid_credential(device):
    dev_id = device["device_id"]
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/api/devices/ws?device_id={dev_id}&credential=invalid"):
            pass
    assert excinfo.value.code == 4001

def test_ws_authentication_unknown_device(db_session):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/api/devices/ws?device_id=unknown&credential=valid"):
            pass
    assert excinfo.value.code == 4001

def test_ws_authentication_revoked_device(device, db_session):
    manager = DeviceManager(db_session)
    manager.revoke_device(device["device_id"], device["principal_id"])
    
    dev_id = device["device_id"]
    cred = device["credential"]
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/api/devices/ws?device_id={dev_id}&credential={cred}"):
            pass
    assert excinfo.value.code == 4001
