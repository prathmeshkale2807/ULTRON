import asyncio
import os
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from enum import Enum, auto
from pydantic import BaseModel

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

def get_stt_provider() -> STTProvider:
    key = os.getenv("DEEPGRAM_API_KEY")
    if key and key != "not_configured":
        pass
    return MockSTTProvider()
