from __future__ import annotations

import os
import sys
import threading
import time
import uuid
import re
import requests

from app.cli.auth import get_cli_auth_token
from app.voice.audio_device import get_microphone_info, get_speaker_info
from app.voice.tts_provider import get_tts_provider, is_tts_available, LocalWindowsTTSProvider

BACKEND_URL = os.getenv("ULTRON_BACKEND_URL", "http://127.0.0.1:8756")
_CONFIRM_POLL_INTERVAL = 0.5
_ANSI = sys.stdout.isatty()


def _ansi(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ANSI else text


_cyan = lambda t: _ansi("96", t)
_green = lambda t: _ansi("92", t)
_yellow = lambda t: _ansi("93", t)
_red = lambda t: _ansi("91", t)
_dim = lambda t: _ansi("2", t)
_bold = lambda t: _ansi("1", t)


class _State:
    auth_token = ""
    session_id = ""
    conversation_id = str(uuid.uuid4())
    voice_mode = False
    voice_state = "STANDBY"
    last_activity = time.time()
    timeout_seconds = 15.0
    active_conversation = False


_state = _State()
_seen_confirmations: set[str] = set()
_stop_workers = threading.Event()

# Wake word pattern
WAKE_WORD_PATTERN = re.compile(r"(?i)^(?:hey\s+)?ultron(?:[,.!?\s]+(.*))?$")
EMERGENCY_STOP_PATTERN = re.compile(r"(?i)^ultron,?\s+(?:emergency\s+)?stop\.?$")


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-ULTRON-AUTH": _state.auth_token}


def _describe_http_error(status: int, detail: str = "") -> str:
    messages = {
        401: "Authentication failed -- local auth token may have rotated.",
        403: "Access denied -- session or ownership check failed.",
        404: "Resource not found.",
        409: "Conflict -- resource already exists or state mismatch.",
        429: "ULTRON is under backpressure (Phase 26 rate limit). Please wait.",
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


def _component_status(health: dict, name_prefix: str) -> str:
    for c in health.get("components", []):
        if c.get("name", "").startswith(name_prefix):
            return c.get("status", "unknown")
    return "unknown"


def _status_icon(status: str) -> str:
    mapping = {
        "ok": _green("ONLINE"),
        "ready": _green("READY"),
        "active": _green("ACTIVE"),
        "not_configured": _yellow("NOT CONFIGURED"),
        "not_implemented": _yellow("NOT IMPLEMENTED"),
        "unauthenticated": _yellow("UNAUTHENTICATED"),
        "unavailable": _red("UNAVAILABLE"),
        "unknown": _dim("UNKNOWN"),
    }
    return mapping.get(status.lower(), _yellow(status.upper()))


def create_session() -> str:
    resp = requests.post(f"{BACKEND_URL}/api/sessions", headers=_headers(), timeout=10)
    if not resp.ok:
        detail = _safe_detail(resp)
        raise RuntimeError(f"Could not create session ({_describe_http_error(resp.status_code, detail)})")
    data = resp.json()
    session_id = data.get("session_id") or data.get("id")
    if not session_id:
        raise RuntimeError(f"Session response missing session_id: {data}")
    return session_id


def invalidate_session() -> None:
    if not _state.session_id:
        return
    try:
        requests.post(f"{BACKEND_URL}/api/sessions/{_state.session_id}/invalidate", headers=_headers(), timeout=5)
    except requests.RequestException:
        pass


def speak_text(text: str) -> None:
    """Speak text aloud through system audio device if TTS is available."""
    if not text or not is_tts_available():
        return
    tts = get_tts_provider()
    if isinstance(tts, LocalWindowsTTSProvider):
        tts._speak_sync(text)
    else:
        # Fallback for mock or other providers
        pass


def _poll_confirmations_once() -> list[dict]:
    try:
        resp = requests.get(f"{BACKEND_URL}/api/confirmations/pending", headers=_headers(), timeout=3)
        if not resp.ok:
            return []
        return [c for c in resp.json() if c["id"] not in _seen_confirmations]
    except Exception:
        return []


def _resolve_confirmation(request_id: str, approved: bool) -> None:
    try:
        requests.post(
            f"{BACKEND_URL}/api/confirmations/{request_id}/resolve",
            headers=_headers(),
            json={"approved": approved, "resolved_by": "cli_user"},
            timeout=5,
        )
    except Exception:
        pass


def handle_pending_confirmations() -> None:
    for conf in _poll_confirmations_once():
        cid = conf["id"]
        if cid in _seen_confirmations:
            continue
        _seen_confirmations.add(cid)
        _show_state("WAITING FOR CONFIRMATION")
        print()
        print(_yellow("+----- CONFIRMATION REQUIRED ------------------+"))
        tool_name = conf.get("tool_name", "?")
        action = conf.get("action", "?")
        reason = conf.get("reason", "?")
        consequence = conf.get("important_consequence", "")
        risk = conf.get("risk", "")
        print(_yellow(f"|  Tool   : {tool_name}"))
        print(_yellow(f"|  Action : {action}"))
        print(_yellow(f"|  Reason : {reason}"))
        if consequence:
            print(_yellow(f"|  Impact : {consequence}"))
        if risk:
            print(_yellow(f"|  Risk   : {risk}"))
        print(_yellow("+----------------------------------------------+"))
        print()

        # Speak confirmation request
        speak_text("This action requires your confirmation. Do you want me to continue?")

        while True:
            try:
                ans = input(_bold("  Confirm? [y/N]: ")).strip().lower()
            except (KeyboardInterrupt, EOFError):
                ans = "n"
            if ans in ("y", "yes", "confirm", "proceed", "go ahead", "do it"):
                _resolve_confirmation(cid, True)
                speak_text("Confirmed.")
                print(_green("  Approved."))
                _show_state("EXECUTING")
                break
            else:
                _resolve_confirmation(cid, False)
                speak_text("Cancelled.")
                print(_red("  Denied."))
                break
        print()


def _confirmation_poll_worker() -> None:
    while not _stop_workers.is_set():
        if _state.session_id:
            handle_pending_confirmations()
        _stop_workers.wait(timeout=_CONFIRM_POLL_INTERVAL)


def _watchdog_worker() -> None:
    """Inactivity watchdog returning LISTENING state to STANDBY."""
    while not _stop_workers.is_set():
        if _state.voice_state == "LISTENING" and _state.active_conversation:
            now = time.time()
            if now - _state.last_activity > _state.timeout_seconds:
                _state.active_conversation = False
                _state.voice_state = "STANDBY"
                sys.stdout.write(f"\n{_dim('  [STANDBY]')}\n")
                sys.stdout.flush()
        _stop_workers.wait(timeout=0.5)


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
    """Engage emergency kill-switch."""
    try:
        requests.post(f"{BACKEND_URL}/api/emergency/activate", headers=_headers(), timeout=5)
    except Exception:
        pass


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _show_state(label: str) -> None:
    _state.voice_state = label
    print(_dim(f"  [{label}]"), flush=True)


def _print_startup_dashboard(health: dict) -> None:
    mic = get_microphone_info()
    spk = get_speaker_info()
    tts_ok = is_tts_available()

    col = 16
    print()
    print(_cyan("  ============================================"))
    print(_cyan("               ULTRON INITIALIZING           "))
    print(_cyan("  ============================================"))
    print()
    print(f"  {'Backend':<{col}}: {_green('ONLINE')}")
    print(f"  {'Database':<{col}}: {_status_icon(_component_status(health, 'database'))}")
    print(f"  {'AI Provider':<{col}}: {_status_icon(_component_status(health, 'ai_provider'))}")
    print(f"  {'Voice Engine':<{col}}: {_green('ONLINE')}")
    print(f"  {'Microphone':<{col}}: {_status_icon('READY' if mic['available'] else 'UNAVAILABLE')}")
    print(f"  {'TTS':<{col}}: {_status_icon('READY' if tts_ok else 'UNAVAILABLE')}")
    print(f"  {'Authentication':<{col}}: {_green('READY')}")
    print()
    print(_cyan("  ============================================"))
    print(_cyan("                  U L T R O N                 "))
    print(_cyan("             PERSONAL AI ASSISTANT            "))
    print(_cyan("  ============================================"))
    print()
    print(f"  {'Backend':<{col}}: {_green('ONLINE')}")
    print(f"  {'AI Provider':<{col}}: {_status_icon(_component_status(health, 'ai_provider'))}")
    print(f"  {'Voice':<{col}}: {_green('ONLINE')}")
    print(f"  {'Microphone':<{col}}: {_status_icon('READY' if mic['available'] else 'UNAVAILABLE')}")
    print(f"  {'TTS':<{col}}: {_status_icon('READY' if tts_ok else 'UNAVAILABLE')}")
    print()
    print("  Say:")
    print()
    print(_bold('      "Hey ULTRON"'))
    print()
    _show_state("STANDBY")
    print()


def _print_status_detailed(health: dict) -> None:
    mic = get_microphone_info()
    spk = get_speaker_info()
    tts_ok = is_tts_available()
    vstatus = check_voice_status()

    col = 20
    print()
    def _row(label: str, status: str) -> None:
        print(f"  {label:<{col}}{_status_icon(status)}")

    _row("Backend",           "ok")
    _row("Database",          _component_status(health, "database"))
    _row("AI Provider",       _component_status(health, "ai_provider"))
    _row("Windows Control",   _component_status(health, "windows_control"))
    _row("Device Manager",    _component_status(health, "device_manager"))
    _row("Android Companion", _component_status(health, "android_companion"))
    _row("Voice Engine",      _component_status(health, "voice_engine"))
    _row("Security",          "active")
    _row("Microphone",        "ready" if mic["available"] else "unavailable")
    _row("TTS",               "ready" if tts_ok else "unavailable")
    _row("Session",           "ok" if _state.session_id else "unavailable")

    if mic["name"]:
        print(f"  Microphone Dev      {mic['name']}")
    if spk["name"]:
        print(f"  Speaker Dev         {spk['name']}")

    if vstatus:
        print(f"  Voice Wake Word     {vstatus.get('wake_word', 'Hey ULTRON')}")
        print(f"  Voice Timeout       {vstatus.get('timeout_seconds', 15.0)}s")
    print(f"  Voice State         {_state.voice_state}")
    print(f"  Active Conversation {_state.active_conversation}")
    print(f"  Backend URL         {BACKEND_URL}")
    if _state.session_id:
        print("  Session ID          [active]")
    print(f"  Conversation        {_state.conversation_id}")
    print()


_HELP_TEXT = """
  ULTRON CLI -- Available commands:

    help       Show this help message
    status     Display live backend, voice, and session status
    clear      Clear the terminal screen
    voice      Enter interactive JARVIS voice mode
    voice off  Exit voice mode back to text mode
    ptt        Activate push-to-talk (Enter LISTENING mode)
    exit       Cleanly invalidate session and exit
    quit       Same as exit
    shutdown   Same as exit

  JARVIS Voice Experience:
    - Say "Hey ULTRON" to wake the assistant.
    - ULTRON responds "Yes, sir?" and enters LISTENING mode.
    - Follow-up commands do NOT require the wake word!
    - After speaking a response, ULTRON automatically returns to LISTENING.
    - After 15s of inactivity, ULTRON returns to STANDBY.

  Security note:
    All commands and voice requests route through the standard
    ULTRON security pipeline (SafetyGate, ConfirmationBroker,
    PermissionStore, and AuditLogger). The CLI never auto-approves.
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


def execute_turn(user_input: str) -> None:
    """Process a natural language user turn."""
    _state.last_activity = time.time()
    _show_state("THINKING")

    # Check emergency stop command
    if EMERGENCY_STOP_PATTERN.match(user_input.strip()):
        trigger_emergency_stop()
        speak_text("Emergency stop activated.")
        print()
        print(_bold("ULTRON:") + " Emergency stop activated.")
        print()
        _state.active_conversation = False
        _show_state("STANDBY")
        return

    try:
        answer = send_message(user_input)
        handle_pending_confirmations()
        _show_state("SPEAKING")
        print()
        print(_bold("ULTRON:") + f" {answer}")
        print()
        speak_text(answer)
        _state.last_activity = time.time()
        if _state.active_conversation:
            _show_state("LISTENING")
    except requests.Timeout:
        print()
        print(_yellow("  ULTRON: Request timed out. The backend may still be processing."))
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
            print(_red("  Session may have expired. Restart ULTRON to re-authenticate."))
        else:
            print(_red(f"  ULTRON ERROR: {msg}"))
        print()
        if _state.active_conversation:
            _show_state("LISTENING")
    except Exception as exc:
        print()
        print(_red(f"  ULTRON ERROR: Unexpected error -- {exc}"))
        print()
        if _state.active_conversation:
            _show_state("LISTENING")


def run_voice_loop() -> str:
    """Interactive JARVIS voice loop in CLI."""
    _state.voice_mode = True
    print()
    print(_cyan("  +==========================================+"))
    print(_cyan("  |") + _bold("             ULTRON VOICE MODE            ") + _cyan("|"))
    print(_cyan("  |") + "         JARVIS Voice Interaction         " + _cyan("|"))
    print(_cyan("  +==========================================+"))
    print()
    print('  Wake phrase   : "Hey ULTRON" / "ULTRON"')
    print("  Follow-ups    : Wake word NOT required once active")
    print("  Inactivity    : Automatic return to STANDBY after timeout")
    print("  Push-To-Talk  : Type 'ptt'")
    print("  Exit voice    : Type 'voice off'")
    print()
    _show_state("STANDBY")
    print()

    try:
        while _state.voice_mode:
            try:
                user_input = input(_bold("VOICE > ")).strip()
            except (KeyboardInterrupt, EOFError):
                print()
                break

            if not user_input:
                continue

            lowered = user_input.lower()

            if lowered in ("voice off", "exit voice", "stop voice"):
                _state.voice_mode = False
                _state.active_conversation = False
                _show_state("STANDBY")
                print(_yellow("  Exited voice mode."))
                break

            if lowered in ("exit", "quit", "shutdown"):
                _state.voice_mode = False
                return "exit"

            if lowered == "help":
                _cmd_help()
                continue

            if lowered == "status":
                _cmd_status()
                continue

            if lowered == "clear":
                _clear()
                continue

            # Push-To-Talk trigger
            if lowered == "ptt":
                _state.active_conversation = True
                _state.last_activity = time.time()
                _show_state("LISTENING")
                print(_green("  [Push-To-Talk Active] Speak your command:"))
                try:
                    spoken = input(_bold("  Speak > ")).strip()
                except (KeyboardInterrupt, EOFError):
                    _state.active_conversation = False
                    _show_state("STANDBY")
                    continue
                if not spoken:
                    continue
                user_input = spoken
                lowered = spoken.lower()

            # In STANDBY: check wake word
            if not _state.active_conversation or _state.voice_state == "STANDBY":
                match = WAKE_WORD_PATTERN.match(user_input)
                if match:
                    _state.active_conversation = True
                    _state.last_activity = time.time()
                    _show_state("WAKE_DETECTED")
                    greeting = "Yes, sir?"
                    print(_bold("ULTRON:") + f" {greeting}")
                    speak_text(greeting)
                    _show_state("LISTENING")

                    remainder = match.group(1)
                    if remainder and remainder.strip():
                        execute_turn(remainder.strip())
                    continue
                else:
                    print(_dim('  [Ignored in STANDBY -- say "Hey ULTRON" or type "ptt"]'))
                    continue

            # In LISTENING: follow-up commands do NOT require wake word
            match = WAKE_WORD_PATTERN.match(user_input)
            if match and match.group(1):
                user_input = match.group(1).strip()

            execute_turn(user_input)

    finally:
        _state.voice_mode = False

    return "continue"


def main() -> None:
    try:
        _state.auth_token = get_cli_auth_token()
        health = check_backend()
        _state.session_id = create_session()
        vstatus = check_voice_status()
        if vstatus:
            _state.timeout_seconds = vstatus.get("timeout_seconds", 15.0)

        _print_startup_dashboard(health)
    except RuntimeError as exc:
        print(_red(f"  FATAL: {exc}"))
        print()
        sys.exit(1)

    confirm_thread = threading.Thread(
        target=_confirmation_poll_worker, daemon=True, name="ultron-confirm-poll"
    )
    confirm_thread.start()

    watchdog_thread = threading.Thread(
        target=_watchdog_worker, daemon=True, name="ultron-inactivity-watchdog"
    )
    watchdog_thread.start()

    try:
        while True:
            try:
                user_input = input(_bold("\nULTRON > ")).strip()
            except KeyboardInterrupt:
                print()
                break
            except EOFError:
                print()
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
            if cmd == "ptt":
                _state.active_conversation = True
                _state.last_activity = time.time()
                _show_state("LISTENING")
                print(_green("  [Push-To-Talk Active] Speak your command:"))
                try:
                    spoken = input(_bold("  Speak > ")).strip()
                except (KeyboardInterrupt, EOFError):
                    _state.active_conversation = False
                    _show_state("STANDBY")
                    continue
                if not spoken:
                    continue
                user_input = spoken
                cmd = spoken.lower()
            if cmd == "voice":
                res = run_voice_loop()
                if res == "exit":
                    break
                continue

            # Check if wake word in general CLI
            match = WAKE_WORD_PATTERN.match(user_input)
            if match:
                _state.active_conversation = True
                _state.last_activity = time.time()
                _show_state("WAKE_DETECTED")
                greeting = "Yes, sir?"
                print(_bold("ULTRON:") + f" {greeting}")
                speak_text(greeting)
                _show_state("LISTENING")

                remainder = match.group(1)
                if remainder and remainder.strip():
                    execute_turn(remainder.strip())
                continue

            # In continuous conversation mode or standard CLI text execution
            if _state.active_conversation:
                execute_turn(user_input)
            else:
                # In standard text CLI mode, execute directly
                execute_turn(user_input)

    finally:
        _stop_workers.set()
        print()
        print(_dim("  Closing session..."))
        invalidate_session()
        print(_dim("  ULTRON offline."))
        print()


if __name__ == "__main__":
    main()
