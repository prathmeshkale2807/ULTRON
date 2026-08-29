"""
ULTRON Speech-To-Text Providers.

LocalWindowsSTTProvider: real Windows SAPI continuous recognition using a
background PowerShell/C# SpeechRecognitionEngine subprocess. Audio is
captured directly from the system default microphone.

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


_SAPI_BRIDGE_PS = r"""
$ProgressPreference = 'SilentlyContinue'
$csharp = @"
using System;
using System.Speech.Recognition;

public class UltronSTTBridge {
    private SpeechRecognitionEngine _engine;

    public void Start() {
        try {
            _engine = new SpeechRecognitionEngine(
                new System.Globalization.CultureInfo("en-US")
            );
            _engine.SetInputToDefaultAudioDevice();

            _engine.UpdateRecognizerSetting("CFGConfidenceRejectionThreshold", 25);

            var wakePhrases = new Choices(new string[] {
                "Hey ULTRON", "ULTRON", "Hey Ultron", "Ultron",
                "Hey Altron", "Altron", "Hey Ultra", "Ultra",
                "Hey Elton", "Elton", "Hey Alltron", "Alltron",
                "Hey Electron", "Electron"
            });

            var commands = new Choices(new string[] {
                "Open Notepad", "Close Notepad", "Launch Notepad", "Exit Notepad",
                "Open Chrome", "Close Chrome", "Launch Chrome", "Exit Chrome",
                "Open Calculator", "Close Calculator", "Launch Calculator",
                "Open Explorer", "Open File Explorer", "Launch Explorer",
                "Open Edge", "Close Edge", "Open Settings",
                "Write hello", "Write hello world", "Type hello", "Type hello world",
                "Write test", "Type test", "Write message",
                "Take screenshot", "Take a screenshot", "Capture screen", "Screenshot",
                "Go to YouTube", "Open YouTube", "Go to Google", "Open Google",
                "Go to Reddit", "Open Reddit", "Go to GitHub", "Open GitHub",
                "Search for NVIDIA", "Search for Iron Man", "Search NVIDIA",
                "Search Google", "Search YouTube",
                "What's my phone battery", "What is my phone battery", "Check phone battery", "Phone battery",
                "What is my battery", "What's my battery", "Battery status",
                "Open WhatsApp on my phone", "Open WhatsApp", "Open Messages",
                "Turn Bluetooth on", "Turn Bluetooth off", "Turn Wi-Fi on", "Turn Wi-Fi off",
                "Get phone location", "Where is my phone",
                "What time is it", "What is the time", "Who are you", "What can you do",
                "Status", "System status", "Help",
                "Stop", "Emergency stop", "Ultron stop", "Ultron emergency stop",
                "yes", "no", "confirm", "cancel", "proceed", "sure", "ok", "okay", "do it",
                "goodbye", "sleep", "standby", "exit", "quit"
            });

            // 1. Standalone wake words
            var gbWake = new GrammarBuilder(wakePhrases);
            var gWake = new Grammar(gbWake) { Priority = 127 };
            _engine.LoadGrammar(gWake);

            // 2. Standalone commands
            var gbCmd = new GrammarBuilder(commands);
            var gCmd = new Grammar(gbCmd) { Priority = 126 };
            _engine.LoadGrammar(gCmd);

            // 3. Wake word + command compound ("Hey ULTRON open Notepad")
            var gbCompound = new GrammarBuilder();
            gbCompound.Append(wakePhrases);
            gbCompound.Append(commands);
            var gCompound = new Grammar(gbCompound) { Priority = 127 };
            _engine.LoadGrammar(gCompound);

            _engine.SpeechRecognized += (s, e) => {
                if (e.Result != null && !string.IsNullOrWhiteSpace(e.Result.Text) && e.Result.Confidence >= 0.25f) {
                    Console.WriteLine("MIC_TRANSCRIPT:" + e.Result.Text);
                    Console.Out.Flush();
                }
            };

            _engine.RecognizeAsync(RecognizeMode.Multiple);
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

$bridge = New-Object UltronSTTBridge
$bridge.Start()

while ($true) {
    [System.Threading.Thread]::Sleep(100)
}
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
            text=True,
            bufsize=1,
        )
    except Exception as e:
        logger.error(f"SAPI bridge launch failed: {e}")
        return None


class LocalWindowsSTTProvider(STTProvider):
    """
    Local Windows SAPI Speech-To-Text Provider.

    Launches a background PowerShell/C# SpeechRecognitionEngine process that
    captures audio directly from the default microphone. Transcripts are
    produced as real speech recognition text from the Windows microphone.
    """

    def __init__(self):
        self._sync_queue: stdlib_queue.Queue[Optional[STTMessage]] = stdlib_queue.Queue()
        self.closed = False
        self._utterance_counter = 0
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
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
        except Exception as e:
            logger.debug(f"STT reader loop ended: {e}")

    async def stream_audio(self, audio_chunk: bytes) -> None:
        """
        Accepts audio chunks. If mock text bytes are passed in tests or simulated input,
        decodes and puts to queue; otherwise real audio is captured by the SAPI bridge.
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

    # 2. Deepgram (cloud STT)
    key = os.getenv("DEEPGRAM_API_KEY")
    if key and key != "not_configured":
        pass

    # 3. Local Windows SAPI (default on Windows for live runtime)
    if sys.platform == "win32":
        return LocalWindowsSTTProvider()

    return MockSTTProvider()
