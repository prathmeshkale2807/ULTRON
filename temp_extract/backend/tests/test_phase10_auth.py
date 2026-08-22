import pytest
import json
from unittest.mock import patch, MagicMock
from app.integrations.google_workspace import (
    save_credentials, get_credentials, revoke_credentials,
    SERVICE_NAME, _get_keyring_key,
)


def test_save_and_get_credentials():
    mock_keyring = {}
    def mock_set(svc, key, val): mock_keyring[f"{svc}:{key}"] = val
    def mock_get(svc, key): return mock_keyring.get(f"{svc}:{key}")
    with patch("app.integrations.google_workspace.keyring.set_password", side_effect=mock_set), \
         patch("app.integrations.google_workspace.keyring.get_password", side_effect=mock_get):
         save_credentials("user1", "mock_refresh_token", ["scope1", "scope2"])
         assert f"{SERVICE_NAME}:{_get_keyring_key('user1')}" in mock_keyring
         creds = get_credentials("user1", ["scope1"])
         assert creds is not None
         assert creds.refresh_token == "mock_refresh_token"
         creds2 = get_credentials("user1", ["scope3"])
         assert creds2 is None


def test_revoke_credentials():
    mock_keyring = {f"{SERVICE_NAME}:{_get_keyring_key('user1')}": "data"}
    def mock_del(svc, key): mock_keyring.pop(f"{svc}:{key}", None)
    with patch("app.integrations.google_workspace.keyring.delete_password", side_effect=mock_del):
        revoke_credentials("user1")
        assert f"{SERVICE_NAME}:{_get_keyring_key('user1')}" not in mock_keyring


def test_principal_isolation():
    mock_keyring = {}
    def mock_set(svc, key, val): mock_keyring[f"{svc}:{key}"] = val
    def mock_get(svc, key): return mock_keyring.get(f"{svc}:{key}")
    with patch("app.integrations.google_workspace.keyring.set_password", side_effect=mock_set), \
         patch("app.integrations.google_workspace.keyring.get_password", side_effect=mock_get):
        save_credentials("alice", "alice_token", ["scope1"])
        save_credentials("bob", "bob_token", ["scope1"])
        alice_creds = get_credentials("alice", ["scope1"])
        bob_creds = get_credentials("bob", ["scope1"])
        assert alice_creds.refresh_token == "alice_token"
        assert bob_creds.refresh_token == "bob_token"
        assert _get_keyring_key("alice") != _get_keyring_key("bob")
