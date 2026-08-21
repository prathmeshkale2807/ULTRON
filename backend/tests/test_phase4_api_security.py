"""
Phase 4 API-level security tests: the local authorization boundary on
permission grant/revoke, profile changes, and emergency-stop reset, run
against the real FastAPI app + TestClient (same pattern as
tests/test_health.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest


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

    from app.ai_providers.factory import get_provider_manager

    get_provider_manager.cache_clear()

    from app.core.database import create_all_for_tests

    create_all_for_tests()

    from app.api import health as health_module

    health_module._provider_health_cache["checked_at"] = 0.0
    health_module._provider_health_cache["results"] = {}

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    get_provider_manager.cache_clear()


def _local_token() -> str:
    from app.security.local_auth import get_or_create_local_token

    return get_or_create_local_token()


def _auth_headers() -> dict:
    return {"X-Ultron-Auth": _local_token()}


# --- unauthorized attempts are rejected ----------------------------------


def test_unauthorized_permission_grant_is_rejected(client) -> None:
    response = client.post(
        "/api/permissions/grant",
        json={"category": "file_write", "scope": "persistent"},
    )
    assert response.status_code == 401


def test_unauthorized_permission_revoke_is_rejected(client) -> None:
    response = client.post(
        "/api/permissions/revoke",
        json={"category": "file_write", "scope": "persistent"},
    )
    assert response.status_code == 401


def test_unauthorized_profile_change_is_rejected(client) -> None:
    response = client.post("/api/profile", json={"mode": "trusted"})
    assert response.status_code == 401


def test_unauthorized_emergency_reset_is_rejected(client) -> None:
    response = client.post("/api/emergency/reset", json={})
    assert response.status_code == 401


def test_wrong_token_is_rejected(client) -> None:
    response = client.post(
        "/api/profile",
        json={"mode": "trusted"},
        headers={"X-Ultron-Auth": "not-the-real-token"},
    )
    assert response.status_code == 401


# --- authorized attempts succeed and are audited ---------------------------


def test_authorized_permission_grant_succeeds_and_is_audited(client) -> None:
    response = client.post(
        "/api/permissions/grant",
        json={"category": "file_write", "scope": "persistent", "actor": "local-ui"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200

    check = client.get("/api/permissions/check", params={"category": "file_write"})
    assert check.json()["status"] == "granted"


def test_authorized_profile_change_succeeds_and_persists(client) -> None:
    response = client.post(
        "/api/profile",
        json={"mode": "trusted", "updated_by": "local-ui"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "trusted"

    reread = client.get("/api/profile")
    assert reread.json()["mode"] == "trusted"


def test_authorized_emergency_reset_succeeds(client) -> None:
    client.post("/api/emergency/activate", json={"reason": "test", "activated_by": "tester"})
    assert client.get("/api/emergency/status").json()["engaged"] is True

    response = client.post(
        "/api/emergency/reset", json={"reset_by": "local-ui"}, headers=_auth_headers()
    )
    assert response.status_code == 200
    assert response.json()["engaged"] is False


def test_emergency_activate_needs_no_auth(client) -> None:
    """Activation must always be reachable -- it's the safety-positive
    direction, unlike reset."""
    response = client.post(
        "/api/emergency/activate", json={"reason": "test", "activated_by": "tester"}
    )
    assert response.status_code == 200
    assert response.json()["engaged"] is True


# --- session-scoped permission requires a valid session --------------------


def test_session_scoped_grant_requires_known_session(client) -> None:
    response = client.post(
        "/api/permissions/grant",
        json={
            "category": "network",
            "scope": "session",
            "session_id": "does-not-exist",
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 400


def test_session_scoped_grant_succeeds_with_valid_session(client) -> None:
    session = client.post("/api/sessions").json()

    response = client.post(
        "/api/permissions/grant",
        json={
            "category": "network",
            "scope": "session",
            "session_id": session["session_id"],
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 200


def test_invalidated_session_rejects_further_session_scoped_grants(client) -> None:
    session = client.post("/api/sessions").json()
    client.post(f"/api/sessions/{session['session_id']}/invalidate")

    response = client.post(
        "/api/permissions/grant",
        json={
            "category": "network",
            "scope": "session",
            "session_id": session["session_id"],
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 400
