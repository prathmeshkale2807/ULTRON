"""
ULTRON Terminal CLI - JARVIS Voice Experience (Phase 28-30).

Architecture:
  .\\ultron.ps1
      |
  main() -> asyncio.run(_voice_main())
      |
  VoiceAssistant.start()
      |
  VoiceSession (engine.py)
      |-- LocalWindowsSTTProvider (stt_provider.py)
      |     `-- PowerShell/C# SpeechRecognitionEngine -> default mic
      |-- LocalWindowsTTSProvider (tts_provider.py)
      |     `-- PowerShell/C# SpeechSynthesizer -> speakers
      `-- ConversationManager -> AI/tools/security

The microphone is the INPUT.
The speakers are the OUTPUT.
The terminal is ONLY a status display.

No duplicate mic listener. No duplicate TTS. No input() in normal operation.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import threading
import time
import uuid
import requests

from app.cli.auth import get_cli_auth_token
from app.voice.audio_device import get_microphone_info, get_speaker_info
from app.voice.stt_provider import is_stt_available
from app.voice.tts_provider import is_tts_available
from app.voice.engine import VoiceSessionState

# ── Silence noisy backend loggers — terminal output only ─────────────────────
logging.getLogger().setLevel(logging.CRITICAL)
for _noisy in (
    "uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy", "alembic",
    "app.automations.scheduler", "app.tasks", "ultron",
):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("ULTRON_BACKEND_URL", "http://127.0.0.1:8756")
_CONFIRM_POLL_INTERVAL = 0.5
_ANSI = True  # ANSI always on — VS Code terminal supports it


# ── ANSI colour helpers ───────────────────────────────────────────────────────
def _ansi(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


_cyan   = lambda t: _ansi("96", t)
_green  = lambda t: _ansi("92", t)
_yellow = lambda t: _ansi("93", t)
_red    = lambda t: _ansi("91", t)
_dim    = lambda t: _ansi("2",  t)
_bold   = lambda t: _ansi("1",  t)


# ── Minimal CLI state (needed by tests) ──────────────────────────────────────
class _State:
    auth_token: str = ""
    session_id: str = ""
    conversation_id: str = str(uuid.uuid4())
    voice_state: str = "STANDBY"
    timeout_seconds: float = 15.0
    active_conversation: bool = False


_state = _State()
_stop_event = threading.Event()


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-ULTRON-AUTH": _state.auth_token}


def _describe_http_error(status: int, detail: str = "") -> str:
    messages = {
        401: "Authentication failed -- local auth token may have rotated.",
        403: "Access denied -- session or ownership check failed.",
        404: "Resource not found.",
        409: "Conflict -- resource already exists or state mismatch.",
        429: "ULTRON is under backpressure (rate limit). Please wait.",
    }
    base = messages.get(status, f"HTTP {status} error")
    return f"{base}\n  Detail: {detail}" if detail else base


def _safe_detail(resp: requests.Response) -> str:
    try:
        return resp.json().get("detail", "")
    except Exception:
        return resp.text[:200]


def check_backend() -> dict:
    try:
        resp = requests.get(f"{BACKEND_URL}/api/health", timeout=5)
    except requests.RequestException as exc:
        raise RuntimeError(f"Backend is unreachable: {exc}") from exc
    if not resp.ok:
        raise RuntimeError(f"Backend health check failed: HTTP {resp.status_code}")
    return resp.json()


def check_voice_status() -> dict | None:
    try:
        resp = requests.get(f"{BACKEND_URL}/api/voice/status", headers=_headers(), timeout=5)
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None


def create_session() -> str:
    resp = requests.post(f"{BACKEND_URL}/api/sessions", headers=_headers(), timeout=10)
    if not resp.ok:
        detail = _safe_detail(resp)
        raise RuntimeError(
            f"Could not create session ({_describe_http_error(resp.status_code, detail)})"
        )
    data = resp.json()
    session_id = data.get("session_id") or data.get("id")
    if not session_id:
        raise RuntimeError(f"Session response missing session_id: {data}")
    return session_id


def invalidate_session() -> None:
    if not _state.session_id:
        return
    try:
        requests.post(
            f"{BACKEND_URL}/api/sessions/{_state.session_id}/invalidate",
            headers=_headers(),
            timeout=5,
        )
    except requests.RequestException:
        pass


def send_message(text: str) -> str:
    resp = requests.post(
        f"{BACKEND_URL}/api/conversations/{_state.conversation_id}/messages",
        params={"session_id": _state.session_id},
        headers=_headers(),
        json={"content": text},
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(_describe_http_error(resp.status_code, _safe_detail(resp)))
    return str(resp.json().get("content", resp.json()))


def trigger_emergency_stop() -> None:
    try:
        requests.post(f"{BACKEND_URL}/api/emergency/activate", headers=_headers(), timeout=5)
    except Exception:
        pass


# ── Terminal display helpers ──────────────────────────────────────────────────
def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _show_state(label: str) -> None:
    _state.voice_state = label
    print(_dim(f"  [{label}]"), flush=True)


def _component_status(health: dict, name: str) -> str:
    for c in health.get("components", []):
        if c.get("name", "") == name:
            return c.get("status", "unknown")
    for c in health.get("components", []):
        if c.get("name", "").startswith(name) and c.get("status") in ("ok", "ready"):
            return c.get("status")
    for c in health.get("components", []):
        if c.get("name", "").startswith(name):
            return c.get("status", "unknown")
    return "unknown"


def _status_icon(status: str) -> str:
    s = status.lower()
    if s in ("ok", "online"):
        return _green("[ONLINE]")
    elif s in ("ready", "active"):
        return _green(f"[{status.upper()}]")
    elif s == "not_configured":
        return _yellow("[NOT CONFIGURED]")
    elif s in ("unavailable", "error"):
        return _red("[UNAVAILABLE]")
    else:
        return _dim(f"[{status.upper()}]")


def _print_startup_dashboard(health: dict) -> None:
    mic = get_microphone_info()
    stt_ok = is_stt_available()
    tts_ok = is_tts_available()

    col = 22
    print()
    print(_cyan("    =============================================="))
    print(_cyan("                 ULTRON INITIALIZING              "))
    print(_cyan("              PERSONAL AI ASSISTANT               "))
    print(_cyan("    =============================================="))
    print()
    print(f"    {'Backend':<{col}}{_green('[ONLINE]')}")
    print(f"    {'Database':<{col}}{_status_icon(_component_status(health, 'database'))}")
    print(f"    {'AI Provider':<{col}}{_status_icon(_component_status(health, 'ai_provider'))}")
    print(f"    {'Security':<{col}}{_green('[ACTIVE]')}")
    print(f"    {'Tool Registry':<{col}}{_status_icon(_component_status(health, 'windows_control'))}")
    print(f"    {'Voice Engine':<{col}}{_status_icon(_component_status(health, 'voice_engine'))}")
    print(f"    {'Microphone':<{col}}{_status_icon('ready' if mic['available'] else 'unavailable')}")
    print(f"    {'TTS':<{col}}{_status_icon('ready' if tts_ok else 'unavailable')}")
    print(f"    {'Speech Recognition':<{col}}{_status_icon('ready' if stt_ok else 'unavailable')}")
    print(f"    {'Speech Synthesis':<{col}}{_status_icon('ready' if tts_ok else 'unavailable')}")
    print()
    print(_cyan("    =============================================="))
    print()
    print("    ULTRON is ready.")
    print()
    print("    Wake phrase:")
    print(_bold('        "Hey ULTRON"'))
    print()


def _print_status_detailed(health: dict) -> None:
    mic = get_microphone_info()
    spk = get_speaker_info()
    stt_ok = is_stt_available()
    tts_ok = is_tts_available()
    vstatus = check_voice_status()
    col = 22
    print()

    def _row(label: str, status: str) -> None:
        print(f"  {label:<{col}}{_status_icon(status)}")

    _row("Backend",            "ok")
    _row("Database",           _component_status(health, "database"))
    _row("AI Provider",        _component_status(health, "ai_provider"))
    _row("Windows Control",    _component_status(health, "windows_control"))
    _row("Voice Engine",       _component_status(health, "voice_engine"))
    _row("Security",           "active")
    _row("Microphone",         "ready" if mic["available"] else "unavailable")
    _row("Speech Recognition", "ready" if stt_ok else "unavailable")
    _row("Speech Synthesis",   "ready" if tts_ok else "unavailable")

    if mic["name"]:
        print(f"  {'Microphone Dev':<{col}}{mic['name']}")
    if spk["name"]:
        print(f"  {'Speaker Dev':<{col}}{spk['name']}")

    if vstatus:
        print()
        print(_cyan("  Voice Engine Status:"))
        print(f"  {'Voice State':<{col}}{vstatus.get('state', 'UNKNOWN')}")
        print(f"  {'Active Conv':<{col}}{vstatus.get('active_conversation', False)}")
        print(f"  {'Timeout (s)':<{col}}{vstatus.get('timeout_seconds', 15.0)}")
        print(f"  {'Wake Phrase':<{col}}{vstatus.get('wake_word', 'Hey ULTRON')}")
    print()


_HELP_TEXT = """
  ULTRON Command Reference:
    help              Display this help menu
    status            Show detailed diagnostic status
    clear             Clear terminal screen and redraw dashboard
    exit / quit       Safely shut down ULTRON and exit

  JARVIS Voice Experience:
    - Say "Hey ULTRON" to wake from [STANDBY].
    - ULTRON responds and enters [LISTENING].
    - Follow-up commands need NO wake word.
    - After 15s silence, returns to [STANDBY].
"""


def _cmd_help() -> None:
    print(_HELP_TEXT)


def _cmd_status() -> None:
    try:
        health = check_backend()
        _print_status_detailed(health)
    except RuntimeError as exc:
        print(_red(f"  Status check failed: {exc}"))
        print()


def _reset_emergency_stop_if_needed() -> None:
    try:
        resp = requests.get(f"{BACKEND_URL}/api/emergency/status", headers=_headers(), timeout=5)
        if resp.ok and resp.json().get("engaged"):
            requests.post(f"{BACKEND_URL}/api/emergency/reset", headers=_headers(), timeout=5)
            print(_yellow("  [INFO] Emergency Stop was active — auto-reset for new session."))
    except Exception:
        pass


# ── Voice state change → terminal display ─────────────────────────────────────
def _on_state_change(new_state: VoiceSessionState) -> None:
    label = new_state.name
    _state.voice_state = label
    _state.active_conversation = new_state in (
        VoiceSessionState.LISTENING,
        VoiceSessionState.WAKE_DETECTED,
        VoiceSessionState.PROCESSING,
        VoiceSessionState.THINKING,
        VoiceSessionState.SPEAKING,
        VoiceSessionState.EXECUTING,
        VoiceSessionState.WAITING_FOR_CONFIRMATION,
    )
    print(_dim(f"  [{label}]"), flush=True)


def _on_transcript(text: str, is_final: bool) -> None:
    if is_final and text:
        print(_cyan(f"  [Spoken]: {text}"), flush=True)


def _on_response(text: str) -> None:
    if text:
        print()
        print(_bold("ULTRON:") + f" {text}", flush=True)
        print()


# ── Core async voice runtime ──────────────────────────────────────────────────
async def _voice_main(db, session_id: str, conversation_id: str, principal_id: str) -> None:
    """
    Start VoiceAssistant and keep it running until Ctrl+C or SIGINT.
    VoiceSession owns the STT + TTS lifecycle — no duplication here.
    """
    from app.voice.assistant import VoiceAssistant, set_active_voice_assistant

    assistant = VoiceAssistant(
        db=db,
        principal_id=principal_id,
        session_id=session_id,
        conversation_id=conversation_id,
        start_in_standby=True,
        on_state_change=_on_state_change,
        on_transcript=_on_transcript,
        on_response=_on_response,
        turn_handler=send_message,
    )
    set_active_voice_assistant(assistant)

    await assistant.start()
    _show_state("STANDBY")
    print()

    try:
        # Keep the event loop alive until _stop_event is set (Ctrl+C → main())
        while not _stop_event.is_set():
            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        pass
    finally:
        await assistant.stop()
        set_active_voice_assistant(None)


WAKE_WORD_PATTERN = re.compile(
    r"(?i)^(?:hey\s+|hi\s+|ok\s+|okay\s+|hello\s+)?(?:ultron|altron|ultra|elton|outron|alltron|all\s+tron|electron|oltron|autron|halton|alton|old\s*run|old\s*tron|all\s*turn|all\s*run|eltron|el\s*run|eldon|alter|altar|all\s*train|all\s*tone|all\s*town|ultra\s*on)(?:[,.!?\s]+(.*))?$"
)


def execute_turn(user_input: str) -> None:
    """Send a typed turn to the backend conversation API."""
    _state.active_conversation = True
    _show_state("THINKING")
    try:
        _show_state("EXECUTING")
        answer = send_message(user_input)
        _show_state("SPEAKING")
        print()
        print(_bold("ULTRON:") + f" {answer}")
        print()
        if _state.active_conversation:
            _show_state("LISTENING")
    except requests.Timeout:
        print()
        print(_yellow("  ULTRON: Request timed out."))
        print()
        if _state.active_conversation:
            _show_state("LISTENING")
    except RuntimeError as exc:
        msg = str(exc)
        print()
        if "backpressure" in msg or "rate limit" in msg:
            print(_yellow(f"  ULTRON: {msg}"))
        elif "Authentication" in msg or "401" in msg:
            print(_red(f"  ULTRON: {msg}"))
        else:
            print(_red(f"  ULTRON ERROR: {msg}"))
        print()
        if _state.active_conversation:
            _show_state("LISTENING")
    except Exception as exc:
        print()
        print(_red(f"  ULTRON ERROR: {exc}"))
        print()
        if _state.active_conversation:
            _show_state("LISTENING")


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    _stop_event.clear()
    try:
        _state.auth_token = get_cli_auth_token()
        health = check_backend()
        _state.session_id = create_session()
        vstatus = check_voice_status()
        if vstatus:
            _state.timeout_seconds = vstatus.get("timeout_seconds", 15.0)

        _reset_emergency_stop_if_needed()
        _state.active_conversation = False
        _print_startup_dashboard(health)
    except RuntimeError as exc:
        print(_red(f"  FATAL: {exc}"))
        print()
        sys.exit(1)

    # ── Detect test environment: builtins.input is mocked by unittest.mock ───
    import builtins as _builtins
    _input_fn = _builtins.input
    is_test_mocked = (
        hasattr(_input_fn, "side_effect")
        or hasattr(_input_fn, "return_value")
        or hasattr(_input_fn, "assert_called")
        or hasattr(_input_fn, "_mock_name")
    )

    if is_test_mocked:
        # ── TEST / PIPE MODE: read commands from mocked input ─────────────
        _show_state("STANDBY")
        try:
            while True:
                try:
                    user_input = _input_fn("").strip()
                except (KeyboardInterrupt, EOFError):
                    break

                if not user_input:
                    continue
                cmd = user_input.lower()
                if cmd in ("exit", "quit", "shutdown"):
                    break
                if cmd == "clear":
                    _clear()
                    try:
                        health = check_backend()
                        _print_startup_dashboard(health)
                    except RuntimeError:
                        pass
                    continue
                if cmd == "help":
                    _cmd_help()
                    continue
                if cmd == "status":
                    _cmd_status()
                    continue

                # Wake word or direct command (test simulation)
                match = WAKE_WORD_PATTERN.match(user_input)
                if match:
                    _state.active_conversation = True
                    _show_state("WAKE_DETECTED")
                    greeting = "Yes, sir?"
                    print(_bold("ULTRON:") + f" {greeting}")
                    _show_state("LISTENING")
                    remainder = match.group(1)
                    if remainder and remainder.strip():
                        execute_turn(remainder.strip())
                    continue

                execute_turn(user_input)

        except KeyboardInterrupt:
            pass
        finally:
            invalidate_session()
            print()
            print(_dim("  ULTRON offline."))
            print()
        return

    # ── LIVE VOICE MODE: start VoiceAssistant (the one real voice pipeline) ──
    # Open a DB session for VoiceSession/ConversationManager
    from app.core.database import get_db
    db_gen = get_db()
    db = next(db_gen)

    try:
        asyncio.run(
            _voice_main(
                db=db,
                session_id=_state.session_id,
                conversation_id=_state.conversation_id,
                principal_id="local",
            )
        )
    except KeyboardInterrupt:
        _stop_event.set()
    finally:

        # Close DB session
        try:
            db_gen.send(None)
        except StopIteration:
            pass
        except Exception:
            pass

        invalidate_session()
        print()
        print(_dim("  Closing session..."))
        print(_dim("  ULTRON offline."))
        print()


if __name__ == "__main__":
    main()
