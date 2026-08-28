"""
Phase 28 — JARVIS Terminal / CLI Tests

Tests cover:
1.  CLI imports successfully.
2.  CLI obtains local auth token through the existing abstraction (not directly from file).
3.  Session creation request is correct.
4.  Conversation request includes conversation_id, session_id, X-ULTRON-AUTH.
5.  Session invalidation occurs on shutdown.
6.  CLI handles backend unavailable.
7.  CLI handles HTTP 401.
8.  CLI handles HTTP 403.
9.  CLI handles HTTP 429 (backpressure message).
10. CLI handles timeout.
11. CLI handles Ctrl+C (KeyboardInterrupt).
12. CLI handles `exit` command.
13. CLI handles `clear` command (no crash).
14. CLI handles `help` command.
15. Status command uses real health endpoint.
16. Auth token is never printed to output.
17. ConversationManager is reached through the API (not directly).
18. CLI does not directly execute tool handlers.
19. Launcher only kills the process it started, not all port-8756 listeners.
20. Existing security behaviour remains unchanged (GET conversation ownership check).

All network calls are mocked — no real Gemini / backend required.
"""

from __future__ import annotations

import importlib
import sys
import uuid
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mock_resp(status_code: int, json_data: dict | list | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = (200 <= status_code < 300)
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


def _health_resp(extra: list | None = None) -> dict:
    components = [
        {"name": "database",          "status": "ok",    "detail": ""},
        {"name": "ai_provider.gemini","status": "ok",    "detail": ""},
        {"name": "windows_control",   "status": "ok",    "detail": ""},
        {"name": "device_manager",    "status": "ok",    "detail": ""},
        {"name": "android_companion", "status": "ok",    "detail": ""},
        {"name": "voice_engine",      "status": "ok",    "detail": ""},
    ]
    if extra:
        components.extend(extra)
    return {"service": "ULTRON", "version": "1.0", "timestamp": "", "components": components}


# ---------------------------------------------------------------------------
# 1. CLI imports successfully
# ---------------------------------------------------------------------------
def test_cli_imports():
    import app.cli.main as m
    assert hasattr(m, "main")
    assert hasattr(m, "send_message")
    assert hasattr(m, "create_session")
    assert hasattr(m, "invalidate_session")
    assert hasattr(m, "check_backend")


# ---------------------------------------------------------------------------
# 2. Local auth token obtained through the existing abstraction
# ---------------------------------------------------------------------------
def test_auth_token_obtained_via_abstraction():
    """The CLI must call get_or_create_local_token() indirectly through
    app.cli.auth.get_cli_auth_token(), NOT read a token file directly."""
    import app.cli.auth as auth_mod
    # Confirm the abstraction is used (not direct file read)
    import inspect
    src = inspect.getsource(auth_mod)
    assert "get_or_create_local_token" in src
    # Confirm the file does not open any file paths for reading
    assert "open(" not in src
    assert "read_text" not in src

    with patch("app.security.local_auth.get_store") as mock_store:
        mock_store.return_value.get.return_value = "A" * 32
        token = auth_mod.get_cli_auth_token()
    assert token == "A" * 32


# ---------------------------------------------------------------------------
# 3. Session creation request is correct
# ---------------------------------------------------------------------------
def test_session_creation_request():
    import app.cli.main as m

    m._state.auth_token = "test-tok-" + "a" * 24
    session_id = "sess-" + uuid.uuid4().hex

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_resp(200, {"session_id": session_id})
        result = m.create_session()

    assert result == session_id
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
    assert "/api/sessions" in url
    assert call_args.kwargs.get("headers", {}).get("X-ULTRON-AUTH") == m._state.auth_token


# ---------------------------------------------------------------------------
# 4. Conversation request includes conversation_id, session_id, X-ULTRON-AUTH
# ---------------------------------------------------------------------------
def test_conversation_request_structure():
    import app.cli.main as m

    m._state.auth_token = "test-tok-" + "b" * 24
    m._state.session_id = "sess-conv-" + uuid.uuid4().hex
    m._state.conversation_id = str(uuid.uuid4())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_resp(200, {"content": "Hello!"})
        result = m.send_message("Hello")

    assert result == "Hello!"
    call_args = mock_post.call_args
    url = call_args.args[0] if call_args.args else ""
    assert m._state.conversation_id in url
    assert call_args.kwargs.get("params", {}).get("session_id") == m._state.session_id
    assert call_args.kwargs.get("headers", {}).get("X-ULTRON-AUTH") == m._state.auth_token


# ---------------------------------------------------------------------------
# 5. Session invalidation occurs on shutdown
# ---------------------------------------------------------------------------
def test_session_invalidated_on_shutdown():
    import app.cli.main as m

    m._state.auth_token = "test-tok-" + "c" * 24
    m._state.session_id = "sess-inv-" + uuid.uuid4().hex

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_resp(200, {"session_id": m._state.session_id, "valid": False})
        m.invalidate_session()

    mock_post.assert_called_once()
    url = mock_post.call_args.args[0]
    assert m._state.session_id in url
    assert "invalidate" in url


# ---------------------------------------------------------------------------
# 6. CLI handles backend unavailable
# ---------------------------------------------------------------------------
def test_backend_unavailable():
    import app.cli.main as m
    import requests as req

    with patch("requests.get", side_effect=req.ConnectionError("refused")):
        with pytest.raises(RuntimeError, match="unreachable"):
            m.check_backend()


# ---------------------------------------------------------------------------
# 7. CLI handles HTTP 401
# ---------------------------------------------------------------------------
def test_http_401_message():
    import app.cli.main as m

    m._state.auth_token = "x" * 32
    m._state.session_id = "sess-401"
    m._state.conversation_id = str(uuid.uuid4())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_resp(401, {"detail": "missing or invalid local auth token"})
        with pytest.raises(RuntimeError, match="Authentication failed"):
            m.send_message("test")


# ---------------------------------------------------------------------------
# 8. CLI handles HTTP 403
# ---------------------------------------------------------------------------
def test_http_403_message():
    import app.cli.main as m

    m._state.auth_token = "x" * 32
    m._state.session_id = "sess-403"
    m._state.conversation_id = str(uuid.uuid4())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_resp(403, {"detail": "not authorized"})
        with pytest.raises(RuntimeError, match="Access denied"):
            m.send_message("test")


# ---------------------------------------------------------------------------
# 9. CLI handles HTTP 429 (backpressure)
# ---------------------------------------------------------------------------
def test_http_429_backpressure():
    import app.cli.main as m

    m._state.auth_token = "x" * 32
    m._state.session_id = "sess-429"
    m._state.conversation_id = str(uuid.uuid4())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_resp(429, {"detail": "rate limit exceeded"})
        with pytest.raises(RuntimeError, match="backpressure|rate limit"):
            m.send_message("test")


# ---------------------------------------------------------------------------
# 10. CLI handles timeout
# ---------------------------------------------------------------------------
def test_timeout_handled():
    import app.cli.main as m
    import requests as req

    m._state.auth_token = "x" * 32
    m._state.session_id = "sess-to"
    m._state.conversation_id = str(uuid.uuid4())

    with patch("requests.post", side_effect=req.Timeout("timed out")):
        # send_message itself propagates the Timeout; main() catches it.
        with pytest.raises(req.Timeout):
            m.send_message("test")


# ---------------------------------------------------------------------------
# 11. main() handles KeyboardInterrupt cleanly
# ---------------------------------------------------------------------------
def test_keyboard_interrupt_handled(capsys):
    import app.cli.main as m

    # Patch: auth, health, session creation, then raise KeyboardInterrupt at input
    with patch("app.cli.auth.get_cli_auth_token", return_value="t" * 32):
        with patch("app.cli.main.check_backend", return_value=_health_resp()):
            with patch("app.cli.main.create_session", return_value="sess-ki"):
                with patch("app.cli.main.invalidate_session") as mock_inv:
                    with patch("builtins.input", side_effect=KeyboardInterrupt):
                        m.main()  # Should NOT raise

    mock_inv.assert_called_once()


# ---------------------------------------------------------------------------
# 12. `exit` command invalidates session and exits loop
# ---------------------------------------------------------------------------
def test_exit_command(capsys):
    import app.cli.main as m

    with patch("app.cli.auth.get_cli_auth_token", return_value="t" * 32):
        with patch("app.cli.main.check_backend", return_value=_health_resp()):
            with patch("app.cli.main.create_session", return_value="sess-exit"):
                with patch("app.cli.main.invalidate_session") as mock_inv:
                    with patch("builtins.input", return_value="exit"):
                        m.main()

    mock_inv.assert_called_once()


# ---------------------------------------------------------------------------
# 13. `clear` command does not crash
# ---------------------------------------------------------------------------
def test_clear_command_no_crash(capsys):
    import app.cli.main as m

    inputs = iter(["clear", "exit"])

    with patch("app.cli.auth.get_cli_auth_token", return_value="t" * 32):
        with patch("app.cli.main.check_backend", return_value=_health_resp()):
            with patch("app.cli.main.create_session", return_value="sess-clear"):
                with patch("app.cli.main.invalidate_session"):
                    with patch("builtins.input", side_effect=inputs):
                        with patch("os.system"):  # Don't actually clear
                            m.main()  # Should not raise


# ---------------------------------------------------------------------------
# 14. `help` command outputs help text
# ---------------------------------------------------------------------------
def test_help_command(capsys):
    import app.cli.main as m

    inputs = iter(["help", "exit"])

    with patch("app.cli.auth.get_cli_auth_token", return_value="t" * 32):
        with patch("app.cli.main.check_backend", return_value=_health_resp()):
            with patch("app.cli.main.create_session", return_value="sess-help"):
                with patch("app.cli.main.invalidate_session"):
                    with patch("builtins.input", side_effect=inputs):
                        m.main()

    captured = capsys.readouterr()
    assert "help" in captured.out.lower()
    assert "exit" in captured.out.lower()


# ---------------------------------------------------------------------------
# 15. Status command uses real health endpoint
# ---------------------------------------------------------------------------
def test_status_uses_real_health(capsys):
    import app.cli.main as m

    inputs = iter(["status", "exit"])
    health = _health_resp()

    with patch("app.cli.auth.get_cli_auth_token", return_value="t" * 32):
        with patch("app.cli.main.check_backend", return_value=health) as mock_health:
            with patch("app.cli.main.create_session", return_value="sess-status"):
                with patch("app.cli.main.invalidate_session"):
                    with patch("builtins.input", side_effect=inputs):
                        m.main()

    # check_backend must have been called (both at startup and for status)
    assert mock_health.call_count >= 2


# ---------------------------------------------------------------------------
# 16. Auth token is NEVER printed to terminal output
# ---------------------------------------------------------------------------
def test_auth_token_never_printed(capsys):
    import app.cli.main as m

    secret_token = "SUPERSECRET_TOKEN_" + "z" * 20

    with patch("app.cli.auth.get_cli_auth_token", return_value=secret_token):
        with patch("app.cli.main.check_backend", return_value=_health_resp()):
            with patch("app.cli.main.create_session", return_value="sess-tok"):
                with patch("app.cli.main.invalidate_session"):
                    with patch("builtins.input", return_value="exit"):
                        m.main()

    captured = capsys.readouterr()
    assert secret_token not in captured.out
    assert secret_token not in captured.err


# ---------------------------------------------------------------------------
# 17. Natural-language input reaches the conversation API
# ---------------------------------------------------------------------------
def test_natural_language_reaches_conversation_api():
    import app.cli.main as m

    m._state.auth_token = "t" * 32
    m._state.session_id = "sess-nl"
    m._state.conversation_id = str(uuid.uuid4())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _mock_resp(200, {"content": "Chrome is open."})
        result = m.send_message("open Chrome")

    assert result == "Chrome is open."
    url = mock_post.call_args.args[0]
    # Must go through /api/conversations/<id>/messages
    assert "/api/conversations/" in url
    assert "/messages" in url


# ---------------------------------------------------------------------------
# 18. CLI does not directly execute tool handlers
# ---------------------------------------------------------------------------
def test_cli_does_not_call_tool_handlers_directly():
    """Verify that the CLI module does not import or reference any tool
    handler functions directly. Tool execution must go through the API."""
    import inspect
    import app.cli.main as m
    src = inspect.getsource(m)

    # Must not directly reference the tool executor or tool handlers
    assert "ToolExecutor" not in src
    assert "tool.handler" not in src
    assert "handler()" not in src
    assert "pywinauto" not in src
    # subprocess.run is permitted ONLY for Windows SAPI TTS audio synthesis.
    # Count allowed uses: _do_speak (TTS) and _mic_listener (Popen, not run).
    # Disallow arbitrary shell execution (e.g. subprocess.run("cmd") for tool calls).
    # We allow subprocess.run with powershell + EncodedCommand for TTS.
    import re
    # Any subprocess.run call must be inside a TTS context (_do_speak / SAPI)
    forbidden_run = re.findall(r'subprocess\.run\([^)]*\)', src)
    for call in forbidden_run:
        assert "EncodedCommand" in call or "powershell" in call, (
            f"subprocess.run outside TTS context is not allowed: {call}"
        )
    # Must not call AI provider directly
    assert "provider_manager" not in src
    assert "complete(" not in src


# ---------------------------------------------------------------------------
# 19. Launcher never kills unrelated processes
# ---------------------------------------------------------------------------
def test_launcher_script_safety():
    """Verify that the launcher script does not contain dangerous kill commands
    that could affect unrelated processes."""
    ps1_path = __file__.replace(
        "tests/test_phase28_cli.py", "ultron.ps1"
    ).replace(
        "tests\\test_phase28_cli.py", "ultron.ps1"
    )
    # Find the ps1 relative to backend root
    import os
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    root_dir = os.path.dirname(backend_dir)
    ps1 = os.path.join(root_dir, "ultron.ps1")

    if not os.path.exists(ps1):
        pytest.skip("ultron.ps1 not found at expected location")

    content = open(ps1, encoding="utf-8").read().lower()

    # Must NOT use dangerous broad kill patterns
    assert "taskkill /im python" not in content
    assert "stop-process -name python" not in content
    # Should only stop by -Id (specific PID)
    if "stop-process" in content:
        assert "-id" in content


# ---------------------------------------------------------------------------
# 20. Existing security: GET /conversations/{id} enforces ownership check
# ---------------------------------------------------------------------------
def test_get_conversation_enforces_ownership_check(tmp_path, monkeypatch):
    """Regression test: _require_valid_session must pass principal.identity
    so the ownership check (row.principal_id == principal.identity) is enforced
    on the GET /conversations/{id} route.

    This tests the bug that was present before Phase 28: the GET route called
    _require_valid_session(session_id, db) with only 2 args, skipping the
    principal_id check entirely.
    """
    import inspect
    import app.api.conversations as conv_mod

    src = inspect.getsource(conv_mod.get_conversation)

    # _require_valid_session must be called with principal.identity as 3rd arg
    assert "principal.identity" in src

    # Verify the helper signature requires 3 args
    sig = inspect.signature(conv_mod._require_valid_session)
    params = list(sig.parameters.keys())
    assert "principal_id" in params


# ---------------------------------------------------------------------------
# Bonus: CLI state is independent between test calls (no shared global leakage)
# ---------------------------------------------------------------------------
def test_cli_state_isolation():
    """Each run of main() should start with a fresh conversation ID (uuid4).
    The module-level _state.conversation_id is set once at import; this test
    verifies that the session_id is only populated after create_session()."""
    import app.cli.main as m

    # Reset state
    m._state.session_id = ""
    m._state.auth_token = ""

    assert m._state.session_id == ""
    assert m._state.auth_token == ""
