"""
ULTRON Speech-To-Text Providers.

Two-mode SAPI bridge:
  - STANDBY mode: narrow fixed grammar (wake words only) → no hallucinations
  - LISTENING mode: free dictation grammar → captures any spoken command

Mode switching is done via stdin commands sent to the bridge process.

MockSTTProvider: accepts raw text bytes for unit testing.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import queue as stdlib_queue
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
from enum import Enum, auto

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class STTEventType(Enum):
    SPEECH_STARTED = auto()
    PARTIAL_TRANSCRIPT = auto()
    SPEECH_ENDED = auto()
    FINAL_TRANSCRIPT = auto()


class STTMessage(BaseModel):
    event_type: STTEventType
    utterance_id: int
    text: str = ""


class STTProvider(ABC):
    """Abstract interface for streaming Speech-To-Text providers."""

    @abstractmethod
    async def stream_audio(self, audio_chunk: bytes) -> None:
        """Pushes raw audio bytes to the STT provider."""
        pass

    @abstractmethod
    async def get_transcripts(self) -> AsyncGenerator[STTMessage, None]:
        """Yields STT events with utterance isolation."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Closes the connection."""
        pass

    def set_listening_mode(self) -> None:
        """Switch to free dictation (LISTENING state). Override in implementations."""
        pass

    def set_standby_mode(self) -> None:
        """Switch to wake-word-only grammar (STANDBY state). Override in implementations."""
        pass


class MockSTTProvider(STTProvider):
    """A mock provider for testing that yields string transcripts from byte strings."""

    def __init__(self):
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False
        self._utterance_counter = 0

    async def stream_audio(self, audio_chunk: bytes) -> None:
        if not self.closed:
            await self.queue.put(audio_chunk)

    async def get_transcripts(self) -> AsyncGenerator[STTMessage, None]:
        while not self.closed:
            chunk = await self.queue.get()
            if chunk == b"__CLOSE__":
                break
            text = chunk.decode("utf-8", errors="ignore").strip()
            if not text:
                continue
            self._utterance_counter += 1
            curr_id = self._utterance_counter
            if text.startswith("PARTIAL:"):
                yield STTMessage(event_type=STTEventType.SPEECH_STARTED, utterance_id=curr_id)
                yield STTMessage(event_type=STTEventType.PARTIAL_TRANSCRIPT, utterance_id=curr_id, text=text[8:].strip())
            else:
                yield STTMessage(event_type=STTEventType.SPEECH_STARTED, utterance_id=curr_id)
                yield STTMessage(event_type=STTEventType.FINAL_TRANSCRIPT, utterance_id=curr_id, text=text)
                yield STTMessage(event_type=STTEventType.SPEECH_ENDED, utterance_id=curr_id)

    async def close(self) -> None:
        self.closed = True
        await self.queue.put(b"__CLOSE__")


# Two-mode SAPI bridge:
#   CMD_STANDBY  → load only wake-word grammar (narrow, no hallucination)
#   CMD_LISTEN   → load dictation grammar (free speech for commands)
_SAPI_BRIDGE_PS = r"""
$ProgressPreference = 'SilentlyContinue'
$csharp = @"
using System;
using System.Speech.Recognition;
using System.Threading;

public class UltronSTTBridge {
    private SpeechRecognitionEngine _engine;
    private Grammar _wakeGrammar;
    private Grammar _dictGrammar;
    private bool _dictMode = false;
    private readonly object _lock = new object();

    public void Start() {
        try {
            _engine = new SpeechRecognitionEngine(
                new System.Globalization.CultureInfo("en-US")
            );
            _engine.SetInputToDefaultAudioDevice();
            _engine.UpdateRecognizerSetting("CFGConfidenceRejectionThreshold", 30);
            _engine.EndSilenceTimeout = TimeSpan.FromSeconds(0.8);
            _engine.BabbleTimeout = TimeSpan.FromSeconds(0.0);

            // --- Wake-word grammar (narrow, high confidence) ---
            var wakeChoices = new Choices(new string[] {
                "Hey ULTRON", "Hey Ultron", "ULTRON", "Ultron",
                "Hey Ultra", "Ultra run", "Okay ULTRON", "OK ULTRON"
            });
            var gbWake = new GrammarBuilder(wakeChoices);
            _wakeGrammar = new Grammar(gbWake) { Name = "Wake", Priority = 127 };

            // --- Dictation grammar (free speech) ---
            _dictGrammar = new DictationGrammar();
            _dictGrammar.Name = "Dictation";
            _dictGrammar.Priority = 100;

            // Start in standby mode: wake words only
            _engine.LoadGrammar(_wakeGrammar);

            _engine.SpeechRecognized += (s, e) => {
                if (e.Result != null
                    && !string.IsNullOrWhiteSpace(e.Result.Text)
                    && e.Result.Confidence >= 0.30f) {
                    Console.WriteLine("MIC_TRANSCRIPT:" + e.Result.Text);
                    Console.Out.Flush();
                }
            };

            _engine.RecognizeAsync(RecognizeMode.Multiple);
            Console.WriteLine("MIC_READY");
            Console.Out.Flush();

            // Read mode-switch commands from stdin on a background thread
            Thread stdinReader = new Thread(() => {
                string line;
                while ((line = Console.In.ReadLine()) != null) {
                    line = line.Trim().ToUpperInvariant();
                    if (line == "CMD_LISTEN") {
                        SetDictationMode(true);
                    } else if (line == "CMD_STANDBY") {
                        SetDictationMode(false);
                    }
                }
            });
            stdinReader.IsBackground = true;
            stdinReader.Start();

            // Keep alive
            while (true) { Thread.Sleep(100); }

        } catch (Exception ex) {
            Console.WriteLine("MIC_ERROR:" + ex.Message);
            Console.Out.Flush();
        }
    }

    private void SetDictationMode(bool dictation) {
        lock (_lock) {
            if (dictation == _dictMode) return;
            _dictMode = dictation;
            try {
                _engine.RecognizeAsyncStop();
                _engine.UnloadAllGrammars();
                if (dictation) {
                    _engine.LoadGrammar(_dictGrammar);
                    _engine.LoadGrammar(_wakeGrammar);
                } else {
                    _engine.LoadGrammar(_wakeGrammar);
                }
                _engine.RecognizeAsync(RecognizeMode.Multiple);
                Console.WriteLine(dictation ? "MODE_LISTEN" : "MODE_STANDBY");
                Console.Out.Flush();
            } catch (Exception ex) {
                Console.WriteLine("MIC_ERROR:ModeSwitch:" + ex.Message);
                Console.Out.Flush();
            }
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

$bridge = New-Object UltronSTTBridge
$bridge.Start()
"""


def launch_sapi_bridge() -> Optional[subprocess.Popen]:
    """Launch the PowerShell/C# SAPI mic bridge. Returns Popen or None."""
    if sys.platform != "win32":
        return None
    try:
        enc = base64.b64encode(_SAPI_BRIDGE_PS.encode("utf-16le")).decode("ascii")
        return subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        logger.error(f"SAPI bridge launch failed: {e}")
        return None


class LocalWindowsSTTProvider(STTProvider):
    """
    Local Windows SAPI Speech-To-Text Provider.

    Two-mode: STANDBY (wake words only, narrow grammar) and
    LISTENING (DictationGrammar + wake words, free speech).
    Mode switching via stdin commands to the bridge process.
    """

    def __init__(self):
        self._sync_queue: stdlib_queue.Queue[Optional[STTMessage]] = stdlib_queue.Queue()
        self.closed = False
        self._utterance_counter = 0
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._mode = "standby"
        if sys.platform == "win32":
            self._start()

    def _start(self) -> None:
        self._process = launch_sapi_bridge()
        if not self._process:
            logger.error("LocalWindowsSTTProvider: failed to launch SAPI bridge")
            return
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="ultron-stt-provider-reader",
        )
        self._reader_thread.start()

    def _read_loop(self) -> None:
        try:
            while not self.closed and self._process:
                if self._process.poll() is not None:
                    logger.warning("STT SAPI bridge process exited")
                    break
                line = self._process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if line == "MIC_READY":
                    logger.info("STT provider: microphone bridge ready")
                elif line in ("MODE_LISTEN", "MODE_STANDBY"):
                    logger.info(f"STT bridge: {line}")
                elif line.startswith("MIC_TRANSCRIPT:"):
                    text = line[len("MIC_TRANSCRIPT:"):].strip()
                    if text:
                        self._utterance_counter += 1
                        uid = self._utterance_counter
                        self._sync_queue.put(STTMessage(
                            event_type=STTEventType.SPEECH_STARTED, utterance_id=uid))
                        self._sync_queue.put(STTMessage(
                            event_type=STTEventType.FINAL_TRANSCRIPT, utterance_id=uid, text=text))
                        self._sync_queue.put(STTMessage(
                            event_type=STTEventType.SPEECH_ENDED, utterance_id=uid))
                elif line.startswith("MIC_ERROR:"):
                    logger.error(f"STT bridge error: {line}")
        except Exception as e:
            logger.debug(f"STT reader loop ended: {e}")

    def _send_command(self, cmd: str) -> None:
        """Send a mode-switch command to the bridge via stdin."""
        if self._process and self._process.poll() is None:
            try:
                self._process.stdin.write(cmd + "\n")
                self._process.stdin.flush()
            except Exception as e:
                logger.debug(f"STT stdin write error: {e}")

    def set_listening_mode(self) -> None:
        """Switch bridge to DictationGrammar (free speech for commands)."""
        if self._mode != "listen":
            self._mode = "listen"
            self._send_command("CMD_LISTEN")
            logger.info("STT: switched to LISTEN mode (dictation)")

    def set_standby_mode(self) -> None:
        """Switch bridge to wake-word-only grammar."""
        if self._mode != "standby":
            self._mode = "standby"
            self._send_command("CMD_STANDBY")
            logger.info("STT: switched to STANDBY mode (wake words only)")

    async def stream_audio(self, audio_chunk: bytes) -> None:
        """
        Accepts audio chunks for tests/simulated input.
        Real audio is captured directly by the SAPI bridge.
        """
        if not self.closed and audio_chunk:
            try:
                text = audio_chunk.decode("utf-8", errors="ignore").strip()
                if text:
                    self._utterance_counter += 1
                    uid = self._utterance_counter
                    self._sync_queue.put(STTMessage(
                        event_type=STTEventType.SPEECH_STARTED, utterance_id=uid))
                    self._sync_queue.put(STTMessage(
                        event_type=STTEventType.FINAL_TRANSCRIPT, utterance_id=uid, text=text))
                    self._sync_queue.put(STTMessage(
                        event_type=STTEventType.SPEECH_ENDED, utterance_id=uid))
            except Exception:
                pass

    async def get_transcripts(self) -> AsyncGenerator[STTMessage, None]:
        loop = asyncio.get_running_loop()
        while not self.closed:
            try:
                msg: Optional[STTMessage] = await loop.run_in_executor(
                    None,
                    lambda: self._sync_queue.get(timeout=0.5),
                )
                if msg is None:
                    break
                yield msg
            except stdlib_queue.Empty:
                continue

    async def close(self) -> None:
        self.closed = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass
        self._sync_queue.put(None)


def is_stt_available() -> bool:
    """Check if any STT engine is functional."""
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    if deepgram_key and deepgram_key != "not_configured":
        return True
    if sys.platform == "win32":
        from app.voice.audio_device import get_microphone_info
        mic = get_microphone_info()
        return mic.get("available", False)
    return False


def get_stt_provider() -> STTProvider:
    # 1. Explicit mock flag or running inside test suite
    if (
        os.getenv("ULTRON_TEST_MOCK_STT") == "1"
        or "pytest" in sys.modules
        or os.getenv("PYTEST_CURRENT_TEST")
    ):
        return MockSTTProvider()

    # 2. Deepgram (cloud STT) — if API key is set
    key = os.getenv("DEEPGRAM_API_KEY")
    if key and key != "not_configured":
        pass  # future: return DeepgramSTTProvider()

    # 3. Local Windows SAPI (default on Windows for live runtime)
    if sys.platform == "win32":
        return LocalWindowsSTTProvider()

    return MockSTTProvider()
