"""
ULTRON Terminal CLI — JARVIS Experience (Phase 28 & 29).

Provides single-process interactive terminal with:
  - Startup diagnostic dashboard
  - Spoken TTS announcement on boot
  - Continuous background microphone Speech Recognition (Windows SAPI)
  - JARVIS-style wake word ('Hey ULTRON') activation into [LISTENING]
  - Continuous multi-turn conversation without repeating wake word
  - Automatic return to [STANDBY] after 15s inactivity watchdog
  - Natural confirmation broker resolution ('yes' / 'no')
  - Emergency stop ('ultron stop' / 'emergency stop')
"""
from __future__ import annotations

import base64
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
import requests

from app.cli.auth import get_cli_auth_token
from app.voice.audio_device import get_microphone_info, get_speaker_info
from app.voice.stt_provider import is_stt_available
from app.voice.tts_provider import get_tts_provider, is_tts_available, LocalWindowsTTSProvider

# Silence noisy backend loggers — the CLI has its own clean UI output.
# Backend logs go to backend/logs/backend.log (via launcher) not the terminal.
logging.getLogger().setLevel(logging.CRITICAL)
for _noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy", "alembic",
               "app.automations.scheduler", "app.tasks", "ultron"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("ULTRON_BACKEND_URL", "http://127.0.0.1:8756")
_CONFIRM_POLL_INTERVAL = 0.5
_ANSI = sys.stdout.isatty()

# Serializes TTS playback — one utterance at a time, never overlapping mic.
_tts_lock = threading.Lock()
# Set while SAPI is speaking so mic thread can pause its recognition loop.
_is_speaking = threading.Event()


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
_turn_lock = threading.Lock()
_mic_subprocess: subprocess.Popen | None = None

# Wake word and natural control patterns
WAKE_WORD_PATTERN = re.compile(
    r"(?i)^(?:hey\s+)?(?:ultron|altron|ultra|elton|outron|alltron|all\s+tron)(?:[,.!?\s]+(.*))?$"
)
EMERGENCY_STOP_PATTERN = re.compile(r"(?i)^ultron,?\s+(?:emergency\s+)?stop\.?$")
EXIT_PATTERN = re.compile(
    r"(?i)^(?:goodbye|stop\s+listening|exit\s+conversation|sleep|standby|go\s+to\s+sleep)\.?$"
)
CONFIRM_YES_PATTERN = re.compile(
    r"(?i)^(?:yes(?:,?\s+(?:do\s+it|please|confirm|proceed))?|confirm|go\s+ahead|continue|sure|yep|yeah|proceed|approved|do\s+it|ok|okay)[.!]?$"
)
CONFIRM_NO_PATTERN = re.compile(
    r"(?i)^(?:no(?:,?\s+(?:cancel|stop|don'?t|deny))?|cancel|stop|don'?t\s+do\s+it|deny|never\s+mind|forget\s+it|reject|disapproved)[.!]?$"
)


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
    elif s == "not_implemented":
        return _yellow("[NOT IMPLEMENTED]")
    elif s == "unauthenticated":
        return _yellow("[UNAUTHENTICATED]")
    elif s in ("unavailable", "error"):
        return _red("[UNAVAILABLE]")
    else:
        return _dim(f"[{status.upper()}]")


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


def _do_speak(text: str) -> None:
    """
    Blocking TTS call using Windows SAPI SpeechSynthesizer.
    Runs in its own thread via speak_text().
    Signals _is_speaking so the mic loop can pause during playback.
    """
    if sys.platform != "win32" or not text:
        return
    cleaned = text.replace('"', '""').replace("`", "").replace("$", "")
    if len(cleaned) > 1000:
        cleaned = cleaned[:997] + "..."
    # Microsoft David Desktop: calm, clear, professional male voice (JARVIS-style)
    ps_code = (
        "$ProgressPreference = 'SilentlyContinue'; "
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SelectVoice('Microsoft David Desktop'); "
        "$s.SetOutputToDefaultAudioDevice(); "
        "$s.Rate = -2; "
        "$s.Volume = 100; "
        f'$s.Speak("{cleaned}");'
    )
    try:
        enc = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
            capture_output=True,
            timeout=30,
        )
    except Exception as exc:
        logger.debug(f"TTS speak error: {exc}")


def speak_text(text: str) -> None:
    """
    Speak text through Windows speakers.
    Dispatches to a background thread so it never blocks the caller.
    Pauses the mic subprocess during playback to avoid SAPI device conflicts.
    """
    if not text or not is_tts_available():
        return

    def _worker() -> None:
        with _tts_lock:
            _is_speaking.set()
            try:
                _do_speak(text)
            finally:
                _is_speaking.clear()

    threading.Thread(target=_worker, daemon=True, name="ultron-tts-speaker").start()


def speak_text_blocking(text: str) -> None:
    """
    Like speak_text but blocks the calling thread until playback completes.
    Used in execute_turn_locked so LISTENING state is only shown after ULTRON finishes speaking.
    """
    if not text or not is_tts_available():
        return
    with _tts_lock:
        _is_speaking.set()
        try:
            _do_speak(text)
        finally:
            _is_speaking.clear()


def _poll_confirmations_once() -> list[dict]:
    try:
        resp = requests.get(f"{BACKEND_URL}/api/confirmations/pending", headers=_headers(), timeout=3)
        if not resp.ok:
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
        return [c for c in data if isinstance(c, dict) and "id" in c and c["id"] not in _seen_confirmations]
    except Exception:
        return []


def _resolve_confirmation(confirmation_id: str, approved: bool) -> bool:
    endpoint = "approve" if approved else "deny"
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/confirmations/{confirmation_id}/{endpoint}",
            headers=_headers(),
            timeout=5,
        )
        return resp.ok
    except Exception:
        return False


def handle_pending_confirmations() -> None:
    """Check for security confirmations requiring human approval."""
    pending = _poll_confirmations_once()
    for req in pending:
        cid = req.get("id")
        if not cid:
            continue
        _seen_confirmations.add(cid)
        action = req.get("action", "execute tool")
        risk = req.get("risk_level", "medium").upper()
        tool_name = req.get("tool_name", "")
        params = req.get("parameters", {})

        print()
        print(_yellow("  +--------------------------------------------------+"))
        print(_yellow("  |") + _bold(f"  SECURITY CONFIRMATION REQUIRED  [{risk}]") + _yellow("        |"))
        print(_yellow("  +--------------------------------------------------+"))
        print(f"  Action   : {action}")
        if tool_name:
            print(f"  Tool     : {tool_name}")
        if params:
            print(f"  Params   : {params}")
        print()

        msg = f"Confirmation required: {action}. Proceed?"
        speak_text(msg)
        _show_state("WAITING_FOR_CONFIRMATION")

        while not _stop_workers.is_set():
            try:
                ans = input(_bold("  Approve? [y/N] > ")).strip().lower()
            except (KeyboardInterrupt, EOFError):
                ans = "n"

            if ans in ("y", "yes", "confirm", "proceed"):
                _resolve_confirmation(cid, True)
                speak_text("Approved.")
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
        _stop_workers.wait(timeout=_CONFIRM_POLL_INTERVAL)



def _watchdog_worker() -> None:
    """Inactivity watchdog returning LISTENING state to STANDBY after timeout."""
    while not _stop_workers.is_set():
        if _state.voice_state == "LISTENING" and _state.active_conversation:
            now = time.time()
            if now - _state.last_activity > _state.timeout_seconds:
                _state.active_conversation = False
                _state.voice_state = "STANDBY"
                sys.stdout.write(f"\n{_dim('  [STANDBY]')}\n\n")
                sys.stdout.flush()
        _stop_workers.wait(timeout=0.5)


def _mic_listener_worker() -> None:
    """Background continuous Speech Recognition worker using Windows SAPI."""
    global _mic_subprocess
    if sys.platform != "win32" or not get_microphone_info().get("available"):
        return

    ps_code = """
$ProgressPreference = 'SilentlyContinue'
$csharp = @"
using System;
using System.Speech.Recognition;

public class UltronMicBridge {
    private SpeechRecognitionEngine engine;

    public void Start() {
        try {
            engine = new SpeechRecognitionEngine(
                new System.Globalization.CultureInfo("en-US")
            );
            engine.SetInputToDefaultAudioDevice();

            engine.UpdateRecognizerSetting("CFGConfidenceRejectionThreshold", 20);

            Choices choices = new Choices();
            choices.Add(new string[] {
                "Hey ULTRON", "ULTRON", "Hey Ultron", "Ultron",
                "Hey Altron", "Altron", "Hey Ultra", "Ultra",
                "Hey Elton", "Elton", "Hey Alltron", "Alltron",
                "Open Notepad", "Close Notepad", "Open Chrome", "Close Chrome",
                "Take screenshot", "Take a screenshot", "Go to YouTube",
                "Search for Iron Man", "What time is it", "Stop", "Emergency stop",
                "yes", "no", "confirm", "cancel", "proceed", "goodbye"
            });
            GrammarBuilder gb = new GrammarBuilder(choices);
            Grammar custom = new Grammar(gb);
            custom.Priority = 127;
            engine.LoadGrammar(custom);

            DictationGrammar dictation = new DictationGrammar();
            engine.LoadGrammar(dictation);

            engine.SpeechRecognized += (s, e) => {
                if (e.Result != null && !string.IsNullOrWhiteSpace(e.Result.Text)) {
                    Console.WriteLine("MIC_TRANSCRIPT:" + e.Result.Text);
                    Console.Out.Flush();
                }
            };

            engine.RecognizeAsync(RecognizeMode.Multiple);
            Console.WriteLine("MIC_READY");
            Console.Out.Flush();
        } catch (Exception ex) {
            Console.WriteLine("MIC_ERROR:" + ex.Message);
            Console.Out.Flush();
        }
    }
}
"@

try {
    Add-Type -TypeDefinition $csharp -ReferencedAssemblies "System.Speech" -ErrorAction Stop
} catch {
    Write-Host "MIC_ERROR: $_"
    exit 1
}

$bridge = New-Object UltronMicBridge
$bridge.Start()

while ($true) {
    [System.Threading.Thread]::Sleep(100)
}
"""
    try:
        enc = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
        _mic_subprocess = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        while not _stop_workers.is_set():
            if _mic_subprocess.poll() is not None:
                break
            line = _mic_subprocess.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line.startswith("MIC_TRANSCRIPT:"):
                continue

            transcript = line[len("MIC_TRANSCRIPT:"):].strip()
            if not transcript:
                continue

            # Skip if ULTRON is actively speaking through the speakers (echo suppression)
            if _is_speaking.is_set():
                continue

            _handle_spoken_input(transcript)

    except Exception as e:
        logger.debug(f"Mic listener error: {e}")
    finally:
        if _mic_subprocess and _mic_subprocess.poll() is None:
            try:
                _mic_subprocess.terminate()
            except Exception:
                pass


def _handle_spoken_input(text: str) -> None:
    """Handle recognized speech from the microphone."""
    with _turn_lock:
        if not text:
            return

        # Check emergency stop
        if EMERGENCY_STOP_PATTERN.match(text) or text.lower().strip() in ("stop", "emergency stop"):
            trigger_emergency_stop()
            print()
            print(_bold("ULTRON:") + " Emergency stop activated.")
            speak_text_blocking("Emergency stop activated.")
            print()
            _state.active_conversation = False
            _show_state("STANDBY")
            return

        # Check graceful sleep/standby
        if EXIT_PATTERN.match(text) and _state.active_conversation:
            print()
            print(_bold("ULTRON:") + " Going to standby, sir.")
            speak_text_blocking("Going to standby, sir.")
            print()
            _state.active_conversation = False
            _show_state("STANDBY")
            return

        # In STANDBY: requires wake word
        if not _state.active_conversation or _state.voice_state == "STANDBY":
            match = WAKE_WORD_PATTERN.match(text)
            if match:
                _state.active_conversation = True
                _state.last_activity = time.time()
                _show_state("WAKE_DETECTED")
                greeting = "Yes, sir?"
                print()
                print(_bold("ULTRON:") + f" {greeting}")
                speak_text_blocking(greeting)   # must finish speaking before LISTENING
                _show_state("LISTENING")

                remainder = match.group(1)
                if remainder and remainder.strip():
                    execute_turn_locked(remainder.strip())
            return

        # In ACTIVE CONVERSATION (LISTENING):
        clean_text = text
        match = WAKE_WORD_PATTERN.match(text)
        if match and match.group(1):
            clean_text = match.group(1).strip()

        print()
        print(_cyan(f"  [Spoken Input]: {clean_text}"))
        execute_turn_locked(clean_text)


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
    stt_ok = is_stt_available()
    tts_ok = is_tts_available()

    col = 20
    print()
    print(_cyan("    =============================================="))
    print(_cyan("                 ULTRON INITIALIZING              "))
    print(_cyan("              PERSONAL AI ASSISTANT               "))
    print(_cyan("    =============================================="))
    print()
    print("    Initializing core systems...")
    print(f"    {'Database':<{col}}{_status_icon(_component_status(health, 'database'))}")
    print(f"    {'Backend':<{col}}{_green('[ONLINE]')}")
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
    _state.active_conversation = False
    _show_state("STANDBY")
    print()
    # Spoken announcement on boot
    speak_text("ULTRON is online and ready, sir.")


def _print_status_detailed(health: dict) -> None:
    mic = get_microphone_info()
    spk = get_speaker_info()
    stt_ok = is_stt_available()
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
    _row("Speech Recognition","ready" if stt_ok else "unavailable")
    _row("Speech Synthesis",  "ready" if tts_ok else "unavailable")
    _row("Session",           "ok" if _state.session_id else "unavailable")

    if mic["name"]:
        print(f"  Microphone Dev      {mic['name']}")
    if spk["name"]:
        print(f"  Speaker Dev         {spk['name']}")

    if vstatus:
        print()
        print(_cyan("  Voice Engine Status:"))
        print(f"  Voice State         {vstatus.get('state', 'UNKNOWN')}")
        print(f"  Active Conv         {vstatus.get('active_conversation', False)}")
        print(f"  Timeout (s)         {vstatus.get('timeout_seconds', 15.0)}")
        print(f"  Wake Phrase         {vstatus.get('wake_word', 'Hey ULTRON')}")

    print()


_HELP_TEXT = """
  ULTRON Command Reference:
    help              Display this help menu
    status            Show detailed diagnostic status of all components
    clear             Clear terminal screen and redraw status dashboard
    ptt               Push-To-Talk: activate microphone directly without wake word
    voice             Enter full-screen voice interaction mode
    exit / quit       Safely shut down ULTRON session and exit

  JARVIS Voice Experience:
    - Say "Hey ULTRON" to wake the assistant from [STANDBY].
    - ULTRON responds "Yes, sir?" and enters [LISTENING] mode.
    - Follow-up commands do NOT require repeating the wake word!
    - After speaking each response, ULTRON automatically returns to [LISTENING].
    - After 15s of silence/inactivity, ULTRON automatically returns to [STANDBY].

  Security note:
    All commands route through the standard ULTRON security pipeline
    (SafetyGate, ConfirmationBroker, PermissionStore, AuditLogger).
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


def execute_turn_locked(user_input: str) -> None:
    """Process a natural language user turn with lock."""
    _state.last_activity = time.time()
    _show_state("THINKING")

    # Check emergency stop command
    if EMERGENCY_STOP_PATTERN.match(user_input.strip()):
        trigger_emergency_stop()
        speak_text_blocking("Emergency stop activated.")
        print()
        print(_bold("ULTRON:") + " Emergency stop activated.")
        print()
        _state.active_conversation = False
        _show_state("STANDBY")
        return

    try:
        _show_state("EXECUTING")
        answer = send_message(user_input)
        handle_pending_confirmations()
        _show_state("SPEAKING")
        print()
        print(_bold("ULTRON:") + f" {answer}")
        print()
        speak_text_blocking(answer)   # blocks until audio done -> then LISTENING
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


def execute_turn(user_input: str) -> None:
    with _turn_lock:
        execute_turn_locked(user_input)


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
        while _state.voice_mode and not _stop_workers.is_set():
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
                    print()
                    print(_bold("ULTRON:") + f" {greeting}")
                    speak_text_blocking(greeting)
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


def _reset_emergency_stop_if_needed() -> None:
    """Clear a stale Emergency Stop left over from tests or previous sessions."""
    try:
        resp = requests.get(f"{BACKEND_URL}/api/emergency/status", headers=_headers(), timeout=5)
        if resp.ok and resp.json().get("engaged"):
            requests.post(f"{BACKEND_URL}/api/emergency/reset", headers=_headers(), timeout=5)
            print(_yellow("  [INFO] Emergency Stop was active — auto-reset for new session."))
    except Exception:
        pass


def main() -> None:
    _stop_workers.clear()
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

    confirm_thread = threading.Thread(
        target=_confirmation_poll_worker, daemon=True, name="ultron-confirm-poll"
    )
    confirm_thread.start()

    watchdog_thread = threading.Thread(
        target=_watchdog_worker, daemon=True, name="ultron-inactivity-watchdog"
    )
    watchdog_thread.start()

    mic_thread = threading.Thread(
        target=_mic_listener_worker, daemon=True, name="ultron-mic-listener"
    )
    mic_thread.start()

    try:
        while not _stop_workers.is_set():
            try:
                user_input = input(_bold("\nULTRON > ")).strip()
            except KeyboardInterrupt:
                break
            except EOFError:
                time.sleep(0.5)
                continue

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

            # Typed wake word or general command
            match = WAKE_WORD_PATTERN.match(user_input)
            if match:
                _state.active_conversation = True
                _state.last_activity = time.time()
                _show_state("WAKE_DETECTED")
                greeting = "Yes, sir?"
                print(_bold("ULTRON:") + f" {greeting}")
                speak_text_blocking(greeting)
                _show_state("LISTENING")

                remainder = match.group(1)
                if remainder and remainder.strip():
                    execute_turn(remainder.strip())
                continue

            # If in active conversation or typed directly
            execute_turn(user_input)

    except KeyboardInterrupt:
        pass
    finally:
        _stop_workers.set()
        global _mic_subprocess
        if _mic_subprocess and _mic_subprocess.poll() is None:
            try:
                _mic_subprocess.terminate()
            except Exception:
                pass
        print()
        print(_dim("  Closing session..."))
        invalidate_session()
        print(_dim("  ULTRON offline."))
        print()


if __name__ == "__main__":
    main()

