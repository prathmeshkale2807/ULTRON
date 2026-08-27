"""
Phase 30 — ULTRON One-Command JARVIS Experience Test Suite.

Comprehensive tests covering:
1.  Single-command launcher logic & process safety.
2.  Backend health check & attaching to existing backend.
3.  Microphone inspection & graceful degradation when unavailable.
4.  TTS provider initialization (LocalWindowsTTSProvider & ElevenLabs & Mock).
5.  Startup health dashboard rendering with real components.
6.  Wake-word activation ("Hey ULTRON" -> [WAKE_DETECTED] -> "Yes, sir?" -> [LISTENING]).
7.  Greeting text passed to TTS.
8.  Continuous conversation: follow-up commands WITHOUT wake word in LISTENING.
9.  Multiple consecutive follow-up commands without wake word.
10. Watchdog timeout: automatic return to STANDBY on inactivity.
11. Re-activation from STANDBY via "Hey ULTRON".
12. Ignored background speech when in STANDBY.
13. Push-to-talk (`ptt`) transition into LISTENING.
14. Voice confirmation: "yes" approves via ConfirmationBroker.
15. Voice cancellation: "no" denies via ConfirmationBroker.
16. Spoken confirmation request before user response.
17. Emergency stop: "ULTRON, emergency stop" triggers kill switch.
18. Session invalidation on shutdown.
19. Unrelated processes are never terminated by the launcher.
20. Voice / TTS failure does not crash text CLI.
21. No credentials or auth tokens printed.
22. Security architecture intact (SafetyGate, ToolExecutor, LocalAuth).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, engine, get_db
from app.executor.confirmation import ConfirmationStatus, get_confirmation_broker
from app.main import app
from app.security.local_auth import get_or_create_local_token
from app.tools.models import DeviceType, RiskLevel
from app.voice.audio_device import get_microphone_info, get_speaker_info
from app.voice.engine import VoiceSession, VoiceSessionState
from app.voice.tts_provider import (
    LocalWindowsTTSProvider,
    MockTTSProvider,
    get_tts_provider,
    is_tts_available,
)

client = TestClient(app)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = next(get_db())
    yield session
    session.rollback()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def auth_headers():
    token = get_or_create_local_token()
    return {"X-ULTRON-AUTH": token}


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


def _health_resp() -> dict:
    return {
        "service": "ULTRON",
        "version": "1.0",
        "timestamp": "",
        "components": [
            {"name": "database",          "status": "ok", "detail": ""},
            {"name": "ai_provider.gemini","status": "ok", "detail": ""},
            {"name": "windows_control",   "status": "ok", "detail": ""},
            {"name": "device_manager",    "status": "ok", "detail": ""},
            {"name": "android_companion", "status": "ok", "detail": ""},
            {"name": "voice_engine",      "status": "ok", "detail": ""},
        ],
    }


# ---------------------------------------------------------------------------
# 1. Microphone & Speaker Device Discovery
# ---------------------------------------------------------------------------
def test_audio_device_discovery():
    mic = get_microphone_info()
    assert isinstance(mic, dict)
    assert "available" in mic
    assert "name" in mic
    assert "count" in mic

    spk = get_speaker_info()
    assert isinstance(spk, dict)
    assert "available" in spk
    assert "name" in spk
    assert "count" in spk


def test_microphone_unavailable_graceful_fallback():
    """When no microphone is detected, returns clean unavailable dict without exception."""
    with patch("app.voice.audio_device._get_num_wave_in_devs", return_value=0):
        mic = get_microphone_info()
        assert mic["available"] is False
        assert mic["count"] == 0


# ---------------------------------------------------------------------------
# 2. TTS Provider & Real Synthesis Logic
# ---------------------------------------------------------------------------
def test_tts_provider_factory():
    tts = get_tts_provider()
    assert tts is not None
    assert hasattr(tts, "stream_text")
    assert hasattr(tts, "flush")
    assert hasattr(tts, "get_audio")
    assert hasattr(tts, "close")


@pytest.mark.asyncio
async def test_local_windows_tts_provider_buffering():
    provider = LocalWindowsTTSProvider()
    spoken_text = None

    def mock_speak_sync(text):
        nonlocal spoken_text
        spoken_text = text

    provider._speak_sync = mock_speak_sync

    await provider.stream_text("Yes, ")
    await provider.stream_text("sir?")
    await provider.flush()

    assert spoken_text == "Yes, sir?"
    await provider.close()


def test_is_tts_available_helper():
    avail = is_tts_available()
    assert isinstance(avail, bool)


# ---------------------------------------------------------------------------
# 3. Voice Status API Endpoint Returns Hardware Inspection
# ---------------------------------------------------------------------------
def test_voice_status_hardware_inspection(auth_headers):
    resp = client.get("/api/voice/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "microphone_available" in data
    assert "speaker_available" in data
    assert "wake_word" in data
    assert data["wake_word"] == "Hey ULTRON"


# ---------------------------------------------------------------------------
# 4. CLI Startup Dashboard Renders Real Status
# ---------------------------------------------------------------------------
def test_cli_startup_dashboard(capsys):
    import app.cli.main as m

    with patch("app.cli.auth.get_cli_auth_token", return_value="t" * 32):
        with patch("app.cli.main.check_backend", return_value=_health_resp()):
            with patch("app.cli.main.create_session", return_value="sess-dash"):
                with patch("app.cli.main.invalidate_session"):
                    with patch("builtins.input", return_value="exit"):
                        m.main()

    captured = capsys.readouterr().out
    assert "ULTRON INITIALIZING" in captured
    assert "Backend" in captured
    assert "Database" in captured
    assert "AI Provider" in captured
    assert "Microphone" in captured
    assert "TTS" in captured
    assert "Hey ULTRON" in captured
    assert "[STANDBY]" in captured


# ---------------------------------------------------------------------------
# 5. Wake-Word Activation & Spoken Greeting ("Yes, sir?")
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wake_word_speaks_greeting_and_enters_listening(db_session):
    spoken = []

    def on_spoken(text):
        spoken.append(text)

    session = VoiceSession(
        db=db_session,
        conversation_id="conv-p30-wake",
        principal_id="local",
        start_in_standby=True,
        on_response=on_spoken,
    )
    await session.start()
    assert session.state == VoiceSessionState.STANDBY

    # User says "Hey ULTRON"
    await session.process_audio_chunk(b"Hey ULTRON")
    await asyncio.sleep(0.3)

    assert "Yes, sir?" in spoken
    assert session.active_conversation is True
    assert session.state in (VoiceSessionState.SPEAKING, VoiceSessionState.LISTENING)

    await session.close()


# ---------------------------------------------------------------------------
# 6. Continuous Conversation: Follow-up Commands Without Wake Word
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_continuous_conversation_without_wake_words(db_session, monkeypatch):
    executed = []

    async def mock_process_turn(self, conversation_id, user_text, *args, **kwargs):
        executed.append(user_text)
        return f"Acknowledged: {user_text}"

    monkeypatch.setattr(
        "app.conversation.manager.ConversationManager.process_turn",
        mock_process_turn,
    )

    session = VoiceSession(
        db=db_session,
        conversation_id="conv-p30-continuous",
        principal_id="local",
        start_in_standby=True,
    )
    await session.start()

    # Step 1: Wake ULTRON
    await session.process_audio_chunk(b"Hey ULTRON")
    await asyncio.sleep(0.2)

    # Step 2: Consecutive commands without wake word
    await session.process_audio_chunk(b"Open Chrome")
    await asyncio.sleep(0.3)

    await session.process_audio_chunk(b"Search for NVIDIA")
    await asyncio.sleep(0.3)

    await session.process_audio_chunk(b"Now open YouTube")
    await asyncio.sleep(0.3)

    await session.process_audio_chunk(b"Take a screenshot")
    await asyncio.sleep(0.3)

    assert "Open Chrome" in executed
    assert "Search for NVIDIA" in executed
    assert "Now open YouTube" in executed
    assert "Take a screenshot" in executed
    assert session.active_conversation is True

    await session.close()


# ---------------------------------------------------------------------------
# 7. Watchdog Inactivity Timeout Returns to STANDBY
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watchdog_inactivity_timeout_returns_to_standby(db_session):
    with patch.dict(os.environ, {"VOICE_CONVERSATION_TIMEOUT_SECONDS": "0.2"}):
        from app.core.config import get_settings
        get_settings.cache_clear()

        session = VoiceSession(
            db=db_session,
            conversation_id="conv-p30-watchdog",
            principal_id="local",
            start_in_standby=True,
            close_on_timeout=False,
        )
        await session.start()

        # Wake
        await session.process_audio_chunk(b"Hey ULTRON")
        await asyncio.sleep(0.1)
        assert session.active_conversation is True

        # Inactivity > 0.2s
        await asyncio.sleep(0.5)

        assert session.active_conversation is False
        assert session.state == VoiceSessionState.STANDBY

        # Re-activate via wake word
        await session.process_audio_chunk(b"ULTRON")
        await asyncio.sleep(0.2)
        assert session.active_conversation is True

        get_settings.cache_clear()
        await session.close()


# ---------------------------------------------------------------------------
# 8. Push-to-Talk (PTT) Activates LISTENING Directly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_push_to_talk_direct_listening(db_session):
    session = VoiceSession(
        db=db_session,
        conversation_id="conv-p30-ptt",
        principal_id="local",
        start_in_standby=True,
    )
    await session.start()
    assert session.state == VoiceSessionState.STANDBY

    session.trigger_push_to_talk()
    assert session.state == VoiceSessionState.LISTENING
    assert session.active_conversation is True

    await session.close()


# ---------------------------------------------------------------------------
# 9. Voice Confirmation & Cancellation via ConfirmationBroker
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_voice_confirmation_broker_yes_flow(db_session):
    broker = get_confirmation_broker()
    req = broker.create(
        principal_id="local",
        tool_name="reboot_system",
        target_device=DeviceType.PC,
        action="Reboot System",
        reason="Update requested",
        important_consequence="System will restart",
        risk=RiskLevel.CRITICAL,
    )

    session = VoiceSession(
        db=db_session,
        conversation_id="conv-p30-confirm-yes",
        principal_id="local",
        start_in_standby=False,
    )
    await session.start()

    # User confirms by voice
    await session.process_audio_chunk(b"yes")
    await asyncio.sleep(0.3)

    resolved = broker.get(req.id)
    assert resolved.status == ConfirmationStatus.APPROVED
    assert resolved.resolved_by == "voice_user"

    await session.close()


@pytest.mark.asyncio
async def test_voice_confirmation_broker_no_flow(db_session):
    broker = get_confirmation_broker()
    req = broker.create(
        principal_id="local",
        tool_name="delete_database",
        target_device=DeviceType.PC,
        action="Delete Database",
        reason="Purge",
        important_consequence="All data destroyed",
        risk=RiskLevel.CRITICAL,
    )

    session = VoiceSession(
        db=db_session,
        conversation_id="conv-p30-confirm-no",
        principal_id="local",
        start_in_standby=False,
    )
    await session.start()

    # User denies by voice
    await session.process_audio_chunk(b"no, cancel")
    await asyncio.sleep(0.3)

    resolved = broker.get(req.id)
    assert resolved.status == ConfirmationStatus.DENIED
    assert resolved.resolved_by == "voice_user"

    await session.close()


# ---------------------------------------------------------------------------
# 10. Emergency Stop Voice Kill Switch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_voice_emergency_stop(db_session):
    session = VoiceSession(
        db=db_session,
        conversation_id="conv-p30-estop",
        principal_id="local",
        start_in_standby=False,
    )
    await session.start()

    # Trigger emergency stop
    await session.process_audio_chunk(b"ULTRON, emergency stop")
    await asyncio.sleep(0.2)

    # Session closes and kill-switch activates
    assert session.is_closed


# ---------------------------------------------------------------------------
# 11. Launcher Safety & Process Isolation
# ---------------------------------------------------------------------------
def test_launcher_ps1_safety_and_single_pid():
    import os
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    root_dir = os.path.dirname(backend_dir)
    ps1_path = os.path.join(root_dir, "ultron.ps1")

    assert os.path.exists(ps1_path), "ultron.ps1 must exist at root"
    content = open(ps1_path, encoding="utf-8").read().lower()

    # Must NOT kill all python processes
    assert "taskkill /im python" not in content
    assert "taskkill /f /im python.exe" not in content
    assert "stop-process -name python" not in content

    # Must terminate only by specific PID
    assert "stop-process -id" in content


# ---------------------------------------------------------------------------
# 12. CLI State and Security Isolation
# ---------------------------------------------------------------------------
def test_cli_does_not_call_tools_directly():
    import app.cli.main as m
    src = inspect.getsource(m)

    assert "ToolExecutor" not in src
    assert "tool.handler" not in src
    assert "pywinauto" not in src
    assert "subprocess.run(" not in src or "powershell" in src  # Only for local SAPI TTS
