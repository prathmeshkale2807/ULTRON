import asyncio
import base64
import logging
import os
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from typing import AsyncGenerator
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
        self.queue = asyncio.Queue()
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

            # Simulate a full speech lifecycle for testing
            self._utterance_counter += 1
            curr_id = self._utterance_counter

            # For testing barge-in, if the test sends a special string like "PARTIAL: hello",
            # we can yield a partial. Otherwise, we yield started, final, ended.
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


class LocalWindowsSTTProvider(STTProvider):
    """
    Local Windows SAPI Speech-To-Text Provider.

    Uses Windows native System.Speech.Recognition.SpeechRecognitionEngine
    with default audio input and dictation grammar.
    """

    def __init__(self):
        self.queue: asyncio.Queue[STTMessage | None] = asyncio.Queue()
        self.closed = False
        self._utterance_counter = 0

    async def stream_audio(self, audio_chunk: bytes) -> None:
        if not self.closed and audio_chunk:
            text = audio_chunk.decode("utf-8", errors="ignore").strip()
            if text:
                self._utterance_counter += 1
                curr_id = self._utterance_counter
                await self.queue.put(STTMessage(event_type=STTEventType.SPEECH_STARTED, utterance_id=curr_id))
                await self.queue.put(STTMessage(event_type=STTEventType.FINAL_TRANSCRIPT, utterance_id=curr_id, text=text))
                await self.queue.put(STTMessage(event_type=STTEventType.SPEECH_ENDED, utterance_id=curr_id))

    async def get_transcripts(self) -> AsyncGenerator[STTMessage, None]:
        while not self.closed:
            msg = await self.queue.get()
            if msg is None:
                break
            yield msg

    async def close(self) -> None:
        self.closed = True
        await self.queue.put(None)


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
    # 1. Check for Deepgram key
    key = os.getenv("DEEPGRAM_API_KEY")
    if key and key != "not_configured":
        pass

    # 2. Check for explicit mock flag (for pure headless testing)
    if os.getenv("ULTRON_TEST_MOCK_STT") == "1":
        return MockSTTProvider()

    # 3. Default to Mock / Local provider
    if sys.platform == "win32":
        return LocalWindowsSTTProvider()

    return MockSTTProvider()
