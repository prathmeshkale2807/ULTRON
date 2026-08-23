import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from app.main import app

def test_readiness_endpoint_when_complete():
    """Test that /api/ready returns 200 when startup_complete is True"""
    with TestClient(app) as client:
        client.app.state.startup_complete = True
        response = client.get("/api/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

def test_readiness_endpoint_when_incomplete():
    """Test that /api/ready returns 503 when startup_complete is False"""
    with TestClient(app) as client:
        client.app.state.startup_complete = False
        response = client.get("/api/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "starting"

@pytest.mark.asyncio
async def test_migration_failure_fails_closed(monkeypatch):
    """Simulate a migration failure to ensure we fail closed."""
    from app.core import database
    def mock_run(*args, **kwargs):
        raise RuntimeError("Migration lock failed")
    
    monkeypatch.setattr(database, "run_migrations", mock_run)
    
    from app.main import lifespan
    import sys
    from fastapi import FastAPI
    import contextlib
    import os

    test_app = FastAPI()
    
    # We also need to patch environment back to production to bypass the test check
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(SystemExit) as exc:
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(test_app))
    
    assert exc.value.code == 1

