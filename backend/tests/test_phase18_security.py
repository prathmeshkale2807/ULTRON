from pathlib import Path
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "test_ultron.db"
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from app.core.config import get_settings
    get_settings.cache_clear()
    
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    
    from app.core.database import Base, get_db
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()
            
    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

def test_automation_api_auth_bypass(client: TestClient):
    """
    Test that Automations API endpoints require local authentication.
    """
    resp = client.post("/api/automations/", json={
        "name": "Hack",
        "automation_type": "SCHEDULED",
        "schedule_definition": {"type": "cron", "cron": "* * * * *"},
        "misfire_policy": "SKIP",
        "timezone": "UTC",
        "task_definition": {"tool_name": "android_send_sms"}
    })
    assert resp.status_code == 401

    resp = client.get("/api/automations/some-id")
    assert resp.status_code == 401

    resp = client.patch("/api/automations/some-id", json={})
    assert resp.status_code == 401

    resp = client.delete("/api/automations/some-id")
    assert resp.status_code == 401


def test_confirmation_api_auth_bypass(client: TestClient):
    resp = client.get("/api/confirmations/pending")
    assert resp.status_code == 401

    resp = client.get("/api/confirmations/some-id")
    assert resp.status_code == 401

    resp = client.post("/api/confirmations/some-id/resolve", json={"approved": True})
    assert resp.status_code == 401


def test_confirmation_api_correlation(client: TestClient):
    from app.executor.confirmation import get_confirmation_broker
    from app.tools.models import DeviceType, RiskLevel
    
    broker = get_confirmation_broker()
    req = broker.create(
        principal_id="other_user",
        session_id="dummy_session",
        task_id="dummy_task",
        tool_name="dummy_tool",
        target_device=DeviceType.PC,
        action="dummy_action",
        reason="dummy",
        important_consequence="dummy",
        risk=RiskLevel.LOW
    )
    
    from app.security.local_auth import get_or_create_local_token
    token = get_or_create_local_token()
    headers = {"X-Ultron-Auth": token}
    
    resp = client.get(f"/api/confirmations/{req.id}", headers=headers)
    assert resp.status_code == 403
    
    resp = client.post(f"/api/confirmations/{req.id}/resolve", json={"approved": True}, headers=headers)
    assert resp.status_code == 403
    
    resp = client.get("/api/confirmations/pending", headers=headers)
    assert resp.status_code == 200
    assert not any(r["id"] == req.id for r in resp.json())

def test_persistent_permission_isolation(client: TestClient, tmp_path: Path):
    """
    Test that a persistent permission granted by one principal doesn't leak to another.
    """
    from app.permissions.store import PermissionStore
    from app.tools.models import PermissionCategory, DeviceType
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
    
    db_file = tmp_path / "test_ultron.db"
    test_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    
    db = TestingSessionLocal()
    try:
        store = PermissionStore(db)
        from app.permissions.models import PermissionScope
        
        # Grant permission for principal A
        store.grant("principal_A", PermissionCategory.FILE_READ, PermissionScope.PERSISTENT)
        
        # Check permission for principal B
        status = store.check("principal_B", PermissionCategory.FILE_READ)
        assert status.value == "unset"
    finally:
        db.close()

def test_session_api_isolation(client: TestClient, tmp_path: Path):
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
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
    
    # Use the same db file the client is using
    db_file = tmp_path / "test_ultron.db"
    test_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    
    db = TestingSessionLocal()
    try:
        mgr = SessionManager(db)
        
        # Valid for local
        assert mgr.is_valid(session_id, "local") is True
        # Invalid for hacker
        assert mgr.is_valid(session_id, "hacker") is False
    finally:
        db.close()


def test_browser_ssrf_dns_hardening(monkeypatch):
    """
    Test that browser URL validation resolves DNS and blocks SSRF targets.
    """
    from app.browser.safety import validate_url_safe, BrowserSafetyError
    import socket
    
    # Mock DNS resolution to return 127.0.0.1
    def mock_gethostbyname(hostname):
        return "127.0.0.1"
        
    monkeypatch.setattr(socket, "gethostbyname", mock_gethostbyname)
    
    # Ensure local network is not allowed
    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_LOCAL_NETWORK_BROWSER", "False")
    
    import pytest
    with pytest.raises(BrowserSafetyError, match="strictly forbidden"):
        validate_url_safe("http://evil.com/admin")
        
    # Unresolvable hostname
    def mock_gethostbyname_fail(hostname):
        raise socket.gaierror("Name or service not known")
    monkeypatch.setattr(socket, "gethostbyname", mock_gethostbyname_fail)
    
    with pytest.raises(BrowserSafetyError, match="Could not resolve"):
        validate_url_safe("http://nonexistent.internal")
