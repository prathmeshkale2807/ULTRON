"""
ULTRON Text-To-Speech Providers.

LocalWindowsTTSProvider: real Windows SAPI speech synthesis using
System.Speech.Synthesis.SpeechSynthesizer with 'Microsoft David Desktop' voice.
Synchronous audio playback ensures that transitions to LISTENING only occur
after speaking has fully finished.

MockTTSProvider: echoes text chunks as byte strings for testing.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

from app.voice.audio_device import get_speaker_info

logger = logging.getLogger(__name__)


class TTSProvider(ABC):
    """Abstract interface for streaming Text-To-Speech providers."""

    @abstractmethod
    async def stream_text(self, text_chunk: str) -> None:
        """Pushes text chunk to the TTS provider."""
        pass

    @abstractmethod
    async def get_audio(self) -> AsyncGenerator[bytes, None]:
        """Yields audio chunks."""
        pass

    @abstractmethod
    async def flush(self) -> None:
        """Signals end of text stream."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Closes the connection."""
        pass


class MockTTSProvider(TTSProvider):
    """A mock provider for testing that echoes text as byte strings."""

    def __init__(self):
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False

    async def stream_text(self, text_chunk: str) -> None:
        if not self.closed:
            await self.queue.put(text_chunk.encode("utf-8"))

    async def get_audio(self) -> AsyncGenerator[bytes, None]:
        while not self.closed:
            chunk = await self.queue.get()
            if chunk == b"__FLUSH__":
                break
            yield chunk

    async def flush(self) -> None:
        if not self.closed:
            await self.queue.put(b"__FLUSH__")

    async def close(self) -> None:
        self.closed = True
        await self.queue.put(b"__FLUSH__")


class LocalWindowsTTSProvider(TTSProvider):
    """
    Local Windows SAPI Text-To-Speech Provider.

    Uses Windows native System.Speech.Synthesis.SpeechSynthesizer to speak
    through the system audio device. Audio playback blocks during flush() so
    the voice session only transitions to LISTENING after the speaker is silent.
    """

    def __init__(self):
        self.queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self.closed = False
        self._text_buffer: list[str] = []

    async def stream_text(self, text_chunk: str) -> None:
        if not self.closed and text_chunk:
            self._text_buffer.append(text_chunk)
            await self.queue.put(text_chunk.encode("utf-8"))

    async def get_audio(self) -> AsyncGenerator[bytes, None]:
        while not self.closed:
            chunk = await self.queue.get()
            if chunk is None or chunk == b"__FLUSH__":
                break
            yield chunk

    async def flush(self) -> None:
        if self.closed:
            return

        # Extract full text to speak
        full_text = "".join(self._text_buffer).strip()
        self._text_buffer.clear()

        if full_text:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._speak_sync, full_text)

        await self.queue.put(b"__FLUSH__")

    def _speak_sync(self, text: str) -> None:
        if sys.platform != "win32" or not text:
            return

        cleaned = text.replace('"', '""').replace("`", "").replace("$", "")
        if len(cleaned) > 1000:
            cleaned = cleaned[:997] + "..."

        ps_code = (
            "$ProgressPreference = 'SilentlyContinue'; "
            "Add-Type -AssemblyName System.Speech; "
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$synth.SelectVoice('Microsoft David Desktop'); "
            "$synth.SetOutputToDefaultAudioDevice(); "
            "$synth.Rate = -2; "
            "$synth.Volume = 100; "
            f'$synth.Speak("{cleaned}");'
        )
        try:
            enc = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    enc,
                ],
                capture_output=True,
                timeout=30,
            )
        except Exception as e:
            logger.warning(f"Local TTS Speak error: {e}")

    async def close(self) -> None:
        self.closed = True
        self._text_buffer.clear()
        await self.queue.put(None)


def is_tts_available() -> bool:
    """Check if any TTS engine is functional."""
    eleven_key = os.getenv("ELEVENLABS_API_KEY")
    if eleven_key and eleven_key != "not_configured":
        return True
    if sys.platform == "win32":
        speakers = get_speaker_info()
        return speakers.get("available", False)
    return False


def get_tts_provider() -> TTSProvider:
    # 1. Explicit mock flag or running inside test suite
    if (
        os.getenv("ULTRON_TEST_MOCK_TTS") == "1"
        or "pytest" in sys.modules
        or os.getenv("PYTEST_CURRENT_TEST")
    ):
        return MockTTSProvider()

    # 2. ElevenLabs key
    key = os.getenv("ELEVENLABS_API_KEY")
    if key and key != "not_configured":
        pass

    # 3. Default to local Windows SAPI TTS on Windows
    if sys.platform == "win32":
        return LocalWindowsTTSProvider()

    return MockTTSProvider()
