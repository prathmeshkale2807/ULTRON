import asyncio
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
import os

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

def get_tts_provider() -> TTSProvider:
    # In a real setup, we would read settings.ELEVENLABS_API_KEY
    key = os.getenv("ELEVENLABS_API_KEY")
    if key and key != "not_configured":
        # Placeholder for real ElevenLabs connection
        pass
    return MockTTSProvider()
