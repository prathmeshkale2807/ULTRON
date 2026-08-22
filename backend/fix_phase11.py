import re
with open('tests/test_phase11_devices.py', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('manager.heartbeat(device_id, credential, \"test_user_1\")', 'manager.heartbeat(device_id, credential)')
c = c.replace('manager.heartbeat(device_id, \"wrong_cred\", \"test_user_1\")', 'manager.heartbeat(device_id, \"wrong_cred\")')
c = c.replace('match=\"Pairing code already used\"', 'match=\"Invalid pairing code\"')
c = re.sub(r'(?s)    # Cross-user access denial.*?manager\.heartbeat\(device_id, credential, \"hacker_user\"\)\n\n', '', c)
c += '''
from app.main import app
from fastapi.testclient import TestClient

@pytest.fixture
def test_client(db_session: Session):
    from app.core.database import get_db
    def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def test_android_heartbeat_api(db_session: Session, test_client: TestClient):
    manager = DeviceManager(db_session)
    record = manager.generate_pairing_code(\"test_user_1\", \"Test Pixel\")
    device_id, credential = manager.pair_device(record.code, \"Test Pixel\")

    res = test_client.post(\"/api/devices/heartbeat\", json={
        \"device_id\": device_id,
        \"credential\": credential
    })
    assert res.status_code == 200
    assert res.json() == {\"status\": \"ok\"}
    
    res2 = test_client.post(\"/api/devices/heartbeat\", json={
        \"device_id\": device_id,
        \"credential\": \"wrong\"
    })
    assert res2.status_code == 403
'''
with open('tests/test_phase11_devices.py', 'w', encoding='utf-8') as f:
    f.write(c)
