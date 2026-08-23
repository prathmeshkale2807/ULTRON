with open("backend/tests/test_phase18_security.py", "a") as f:
    f.write('''
def test_persistent_permission_isolation(client: TestClient):
    """
    Test that a persistent permission granted by one principal doesn't leak to another.
    """
    from app.permissions.store import PermissionStore
    from app.tools.models import PermissionCategory, DeviceType
    from app.core.database import SessionLocal
    
    db = SessionLocal()
    store = PermissionStore(db)
    # Grant permission for principal A
    store.grant("principal_A", PermissionCategory.CALENDAR, "persistent", None, None, None)
    
    # Check permission for principal B
    status = store.check("principal_B", PermissionCategory.CALENDAR)
    assert status.value == "unset"

def test_session_api_isolation(client: TestClient):
    """
    Test that sessions are isolated per principal.
    """
    # 1. POST /sessions without auth fails
    resp = client.post("/api/sessions")
    assert resp.status_code == 401
    
    # 2. Get local token and create session
    from app.security.local_auth import get_or_create_local_token
    token = get_or_create_local_token()
    headers = {"X-Ultron-Auth": token}
    resp = client.post("/api/sessions", headers=headers)
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    
    # 3. Simulate another user checking the session
    from app.sessions.manager import SessionManager
    from app.core.database import SessionLocal
    db = SessionLocal()
    mgr = SessionManager(db)
    
    # Valid for local
    assert mgr.is_valid(session_id, "local") is True
    # Invalid for hacker
    assert mgr.is_valid(session_id, "hacker") is False

''')
