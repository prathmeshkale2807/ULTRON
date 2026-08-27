import asyncio
import base64
import logging
import os
import subprocess
import sys
import threading
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
        self.queue = asyncio.Queue()
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
    through the system audio device without external cloud dependencies.
    Also emits text/audio chunks onto an internal queue for streaming.
    """

    def __init__(self):
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.closed = False
        self._text_buffer: list[str] = []
        self._lock = asyncio.Lock()

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

        await self.queue.put(b"__FLUSH__")

        # Extract full text to speak
        full_text = "".join(self._text_buffer).strip()
        self._text_buffer.clear()

        if not full_text:
            return

        # Perform spoken synthesis asynchronously in background daemon thread
        threading.Thread(
            target=self._speak_sync,
            args=(full_text,),
            daemon=True,
            name="ultron-sapi-tts",
        ).start()

    def _speak_sync(self, text: str) -> None:
        if sys.platform != "win32" or not text:
            return

        # Clean text for PowerShell execution
        cleaned = text.replace('"', '""').replace("`", "")
        # Limit to 1000 characters to prevent excessive duration
        if len(cleaned) > 1000:
            cleaned = cleaned[:997] + "..."

        ps_code = (
            "Add-Type -AssemblyName System.Speech; "
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$synth.SetOutputToDefaultAudioDevice(); "
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
                timeout=15,
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
    # 1. Check for ElevenLabs key
    key = os.getenv("ELEVENLABS_API_KEY")
    if key and key != "not_configured":
        # Placeholder for real ElevenLabs connection
        pass

    # 2. Check for explicit mock flag (for pure headless testing)
    if os.getenv("ULTRON_TEST_MOCK_TTS") == "1":
        return MockTTSProvider()

    # 3. Default to local Windows SAPI TTS on Windows
    if sys.platform == "win32":
        return LocalWindowsTTSProvider()

    return MockTTSProvider()
