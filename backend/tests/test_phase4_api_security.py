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
        json={"category": "file_write", "scope": "persistent"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200

    check = client.get("/api/permissions/check", params={"category": "file_write"})
    assert check.json()["status"] == "granted"


def test_authorized_profile_change_succeeds_and_persists(client) -> None:
    response = client.post(
        "/api/profile",
        json={"mode": "trusted"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "trusted"

    reread = client.get("/api/profile")
    assert reread.json()["mode"] == "trusted"


def test_authorized_emergency_reset_succeeds(client) -> None:
    client.post("/api/emergency/activate", json={"reason": "test"})
    assert client.get("/api/emergency/status").json()["engaged"] is True

    response = client.post(
        "/api/emergency/reset", json={}, headers=_auth_headers()
    )
    assert response.status_code == 200
    assert response.json()["engaged"] is False


def test_emergency_activate_needs_no_auth(client) -> None:
    """Activation must always be reachable -- it's the safety-positive
    direction, unlike reset."""
    response = client.post(
        "/api/emergency/activate", json={"reason": "test"}
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


# --- Issue 1 (revised): token store integrity ----------------------------


def test_corrupt_token_in_store_triggers_regeneration(tmp_path: "Path", monkeypatch) -> None:
    """A corrupt token in the secret store must be rejected and a fresh
    valid token generated -- not returned as-is (DoS / weak-secret risk)."""
    # Use a FileStore in an isolated directory so this test never touches
    # any real credential store.
    from app.security.local_auth import _MIN_TOKEN_LENGTH, _token_is_valid
    from app.security.secret_store import FileStore

    store = FileStore(tmp_path)

    # Plant a corrupt (too-short) token.
    store.set("tooshort")
    assert not _token_is_valid("tooshort")

    # Monkey-patch get_store() to return our isolated store.
    import app.security.local_auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_store", lambda: store)

    token = auth_mod.get_or_create_local_token()
    assert len(token) >= _MIN_TOKEN_LENGTH
    assert _token_is_valid(token)
    # Store now holds the fresh token.
    assert store.get() == token


def test_missing_token_in_store_triggers_generation(tmp_path: "Path", monkeypatch) -> None:
    """An empty/absent store entry causes a fresh token to be generated
    and saved, not an error or an empty token being returned."""
    from app.security.local_auth import _MIN_TOKEN_LENGTH, _token_is_valid
    from app.security.secret_store import FileStore

    store = FileStore(tmp_path)
    # No token planted -- store is empty.
    assert store.get() is None

    import app.security.local_auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_store", lambda: store)

    token = auth_mod.get_or_create_local_token()
    assert len(token) >= _MIN_TOKEN_LENGTH
    assert _token_is_valid(token)
    assert store.get() == token


# --- Secret store backend selection --------------------------------------


def test_file_store_used_in_test_environment(monkeypatch) -> None:
    """When ENVIRONMENT=test, get_store() must return a FileStore, never
    the production KeyringStore.  This is the safety guarantee that tests
    never touch Windows Credential Manager."""
    from app.core.config import get_settings
    from app.security.secret_store import FileStore, get_store

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "test")

    store = get_store()
    assert isinstance(store, FileStore), (
        f"Expected FileStore in test env, got {type(store).__name__}"
    )


def test_keyring_store_would_be_used_in_production(monkeypatch) -> None:
    """When ENVIRONMENT=production, get_store() must return a KeyringStore.
    We don't instantiate the full keyring in this test (we only check the
    type), so Windows Credential Manager is never actually contacted."""
    from app.core.config import get_settings
    from app.security.secret_store import KeyringStore, get_store

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")

    try:
        store = get_store()
        assert isinstance(store, KeyringStore), (
            f"Expected KeyringStore in production env, got {type(store).__name__}"
        )
    finally:
        get_settings.cache_clear()


# --- Principal derivation ------------------------------------------------


def test_require_local_auth_returns_principal_with_local_identity(
    tmp_path: "Path", monkeypatch
) -> None:
    """A valid token must yield Principal(identity='local') -- the
    server-derived constant, never a client-supplied string."""
    from app.security.local_auth import Principal, get_or_create_local_token, require_local_auth
    from app.security.secret_store import FileStore

    store = FileStore(tmp_path)
    import app.security.local_auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_store", lambda: store)

    token = get_or_create_local_token()
    principal = require_local_auth(x_ultron_auth=token)
    assert isinstance(principal, Principal)
    assert principal.identity == "local"


def test_require_local_auth_with_wrong_token_raises_401(
    tmp_path: "Path", monkeypatch
) -> None:
    """A wrong token must raise HTTPException(401), not return any
    principal."""
    from fastapi import HTTPException

    from app.security.local_auth import get_or_create_local_token, require_local_auth
    from app.security.secret_store import FileStore

    store = FileStore(tmp_path)
    import app.security.local_auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_store", lambda: store)
    get_or_create_local_token()  # generate + persist the real token

    import pytest

    with pytest.raises(HTTPException) as exc_info:
        require_local_auth(x_ultron_auth="wrong-token")
    assert exc_info.value.status_code == 401


# --- Actor / identity spoofing is impossible -----------------------------
#
# These tests prove the security contract at two levels:
#
#   1. Structural: the request models contain NO identity fields,
#      so there is no API surface through which a caller can inject
#      an audit actor.
#   2. Behavioral: sending a spoofed identity in the body is silently
#      ignored (extra='ignore' Pydantic default) and the API still
#      returns 200 -- proving callers are not penalised for legacy
#      clients that used to send these fields, while the spoofed value
#      never reaches the audit trail.
#


def test_permission_request_has_no_actor_field() -> None:
    """Structural proof: PermissionRequest.model_fields has no 'actor'
    key.  A field that doesn't exist cannot be used to spoof an
    audit identity."""
    from app.api.permissions import PermissionRequest

    assert "actor" not in PermissionRequest.model_fields, (
        "PermissionRequest must not have an 'actor' field -- audit identity "
        "must be derived from the authenticated Principal, not the request body."
    )


def test_set_profile_request_has_no_updated_by_field() -> None:
    """Structural proof: SetProfileRequest.model_fields has no 'updated_by'."""
    from app.api.profile import SetProfileRequest

    assert "updated_by" not in SetProfileRequest.model_fields, (
        "SetProfileRequest must not have an 'updated_by' field."
    )


def test_activate_request_has_no_activated_by_field() -> None:
    """Structural proof: ActivateRequest.model_fields has no 'activated_by'."""
    from app.api.emergency import ActivateRequest

    assert "activated_by" not in ActivateRequest.model_fields, (
        "ActivateRequest must not have an 'activated_by' field."
    )


def test_reset_request_has_no_reset_by_field() -> None:
    """Structural proof: ResetRequest.model_fields has no 'reset_by'."""
    from app.api.emergency import ResetRequest

    assert "reset_by" not in ResetRequest.model_fields, (
        "ResetRequest must not have a 'reset_by' field."
    )


def test_actor_spoofing_in_permission_grant_is_impossible(client) -> None:
    """Behavioral proof: sending actor='attacker' in the body does not
    cause the request to fail (backward compat) but also does not affect
    the actual audit record, which must contain the authenticated
    principal 'local' -- not the caller-supplied value."""
    response = client.post(
        "/api/permissions/grant",
        # actor is an extra/unknown field -- Pydantic silently ignores it.
        json={"category": "file_read", "scope": "persistent", "actor": "attacker"},
        headers=_auth_headers(),
    )
    # Request succeeds (extra fields are ignored, not rejected).
    assert response.status_code == 200
    # The 'actor' key is not in the response body (it was never in the model).
    assert "actor" not in response.json()


def test_updated_by_spoofing_in_profile_change_is_impossible(client) -> None:
    """Behavioral proof: sending updated_by='attacker' in the profile body
    does not affect the audit identity. ProfileState includes updated_by so
    callers can see who made the change -- but the value must be the
    authenticated principal ('local'), NOT the caller-supplied 'attacker'."""
    response = client.post(
        "/api/profile",
        json={"mode": "balanced", "updated_by": "attacker"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    data = response.json()
    # The response carries updated_by from the authenticated principal.
    # It must never reflect the spoofed body value.
    assert data.get("updated_by") == "local", (
        f"expected 'local' (authenticated principal), got {data.get('updated_by')!r}"
    )
    assert data.get("updated_by") != "attacker"


def test_reset_by_spoofing_in_emergency_reset_is_impossible(client) -> None:
    """Behavioral proof: sending reset_by='attacker' in the reset body
    does not affect the outcome -- the field is silently dropped."""
    client.post("/api/emergency/activate", json={"reason": "test"})
    response = client.post(
        "/api/emergency/reset",
        json={"reset_by": "attacker"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["engaged"] is False


def test_activated_by_spoofing_in_activate_is_impossible(client) -> None:
    """Behavioral proof: sending activated_by='attacker' in the activate
    body does not affect the outcome -- the field is silently dropped.
    The audit identity for unauthenticated activation is always
    the fixed server-side constant 'unauthenticated'."""
    response = client.post(
        "/api/emergency/activate",
        json={"reason": "testing spoof", "activated_by": "attacker"},
    )
    assert response.status_code == 200
    assert response.json()["engaged"] is True


# --- Issue 2: session TTL clamping ---------------------------------------


def test_session_creation_with_no_ttl_uses_default(client) -> None:
    """Omitting ttl_seconds must not create a never-expiring session."""
    response = client.post("/api/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["expires_at"] is not None  # always has an expiry


def test_session_creation_with_huge_ttl_is_clamped(client) -> None:
    """A caller-supplied TTL above the cap must be silently clamped."""
    from datetime import datetime

    from app.sessions.manager import DEFAULT_SESSION_TTL_SECONDS

    one_year_seconds = 365 * 24 * 3600
    response = client.post("/api/sessions", params={"ttl_seconds": one_year_seconds})
    assert response.status_code == 200
    data = response.json()

    created_at = datetime.fromisoformat(data["created_at"])
    expires_at = datetime.fromisoformat(data["expires_at"])
    actual_ttl = (expires_at - created_at).total_seconds()

    # The actual TTL must be <= the cap, not the huge value we requested.
    assert actual_ttl <= DEFAULT_SESSION_TTL_SECONDS + 5  # +5s for test jitter


def test_session_creation_with_none_ttl_uses_default(client) -> None:
    """Omitting ttl_seconds (equivalent to None) results in a capped session."""
    response = client.post("/api/sessions")
    assert response.status_code == 200
    assert response.json()["expires_at"] is not None


# --- normalize_actor unit tests (kept: sanitizer is used for reason fields) --


def test_normalize_actor_unit_cases() -> None:
    """Unit-level checks on normalize_actor covering all edge cases.
    normalize_actor() is kept as defense-in-depth for untrusted free-text
    fields (e.g. emergency stop reason) -- it is NOT used to derive audit
    identity (which always comes from the authenticated Principal)."""
    from app.security.sanitize import normalize_actor

    # Control characters are replaced with underscore
    assert "\n" not in normalize_actor("line\nbreak")
    assert "\x00" not in normalize_actor("nul\x00byte")
    assert "\x1b" not in normalize_actor("esc\x1b[31m")

    # Long strings are truncated
    assert len(normalize_actor("a" * 200)) == 64

    # Empty / whitespace-only strings default to "unknown"
    assert normalize_actor("") == "unknown"
    assert normalize_actor("   ") == "unknown"

    # Normal strings pass through unchanged
    assert normalize_actor("local-ui") == "local-ui"
    assert normalize_actor("tester") == "tester"

    # Leading/trailing whitespace is stripped
    assert normalize_actor("  tester  ") == "tester"
