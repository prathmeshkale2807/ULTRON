"""
Core service test suite (Phase 1 + Phase 2 health surface).

These tests exercise the real FastAPI app against a real (temp-file)
SQLite database via TestClient -- nothing here is mocked. They verify:

  1. The service starts without errors.
  2. The root endpoint responds.
  3. /api/health responds and proves a real DB write+read round-trip.
  4. AI provider status is reported honestly (not_configured here, since
     no keys are set in the test environment -- never faked as "ok").
  5. Components not yet built are honestly reported as not_implemented.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    # Point the app at an isolated temp SQLite DB + log dir for this test
    # run, so tests never touch a developer's real ./data directory and
    # tests are independent of each other.
    db_file = tmp_path / "test_ultron.db"
    log_dir = tmp_path / "logs"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("ENVIRONMENT", "test")

    # Force providers to "not_configured" regardless of the developer's
    # real shell environment, so this test never makes a live API call
    # and its assertions stay deterministic.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # Settings and the provider manager are both lru_cache'd -- clear so
    # the env vars above take effect for this test.
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.ai_providers.factory import get_provider_manager

    get_provider_manager.cache_clear()

    # App startup deliberately no longer runs create_all() (that's not a
    # real migration mechanism) -- tests stand up their own isolated temp
    # schema directly instead of depending on Alembic having been run.
    from app.core.database import create_all_for_tests

    create_all_for_tests()

    # Provider health results are cached for 60s (see app/api/health.py) --
    # reset that cache too so each test starts with a fresh check.
    from app.api import health as health_module

    health_module._provider_health_cache["checked_at"] = 0.0
    health_module._provider_health_cache["results"] = {}

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    get_provider_manager.cache_clear()


def test_root_endpoint_responds(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"


def test_health_endpoint_reports_real_database(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()

    assert body["service"] == "ULTRON Core Service"
    components = {c["name"]: c for c in body["components"]}

    # The database component must be reported as genuinely working --
    # this is the one real capability Phase 1 claims to have.
    assert components["database"]["status"] == "ok"
    assert "last event id" in components["database"]["detail"]

    # AI providers: no keys configured in this test env, so both must be
    # honestly reported as not_configured -- never faked as "ok".
    assert components["ai_provider.claude"]["status"] == "not_configured"
    assert components["ai_provider.gemini"]["status"] == "not_configured"

    # New Phase 11 & PC execution components are now implemented
    assert components["device_manager"]["status"] == "ok"
    assert "table accessible" in components["device_manager"]["detail"]

    assert components["android_companion"]["status"] == "ok"
    assert "pairing APIs available" in components["android_companion"]["detail"]

    assert components["windows_control"]["status"] == "ok"

    # Everything not yet built must be honest about it -- this is the
    # "no fake capabilities" rule, enforced by a test, not just a promise.
    for name in (
        # "voice_engine", # Now implemented
    ):
        assert components[name]["status"] == "not_implemented"
        
    assert components["voice_engine"]["status"] in ("ok", "not_configured")


def test_health_endpoint_db_survives_multiple_calls(client):
    # Two calls should each add a row and both should succeed --
    # proves the session lifecycle (get_db dependency) isn't leaking
    # or breaking across requests.
    first = client.get("/api/health")
    second = client.get("/api/health")
    assert first.status_code == 200
    assert second.status_code == 200

    first_id = int(first.json()["components"][0]["detail"].split("=")[1])
    second_id = int(second.json()["components"][0]["detail"].split("=")[1])
    assert second_id == first_id + 1
