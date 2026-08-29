"""
ULTRON Voice Assistant ? Local & CLI Voice Controller (Phase 29).

Provides high-level management of JARVIS-style voice interactions for:
  - CLI voice mode ('ULTRON > voice')
  - Desktop background voice listener
  - Push-to-talk activation
  - State tracking and callbacks
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.voice.engine import VoiceSession, VoiceSessionState

logger = logging.getLogger(__name__)

# Active singleton voice assistant instance to prevent duplicate concurrent sessions
_active_assistant: Optional[VoiceAssistant] = None
_voice_event_subscribers: list[asyncio.Queue] = []


def subscribe_voice_events() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _voice_event_subscribers.append(q)
    return q


def unsubscribe_voice_events(q: asyncio.Queue) -> None:
    if q in _voice_event_subscribers:
        _voice_event_subscribers.remove(q)


def broadcast_voice_event(event: dict) -> None:
    for q in list(_voice_event_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass


class VoiceAssistant:
    """
    High-level controller for ULTRON JARVIS-Style Voice Assistant.

    Manages lifecycle, push-to-talk triggers, audio streams, and callbacks.
    Ensures single active voice session across CLI and desktop layers.
    """

    def __init__(
        self,
        db: Session,
        principal_id: str = "local",
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        *,
        start_in_standby: bool = True,
        on_state_change: Optional[Callable[[VoiceSessionState], None]] = None,
        on_transcript: Optional[Callable[[str, bool], None]] = None,
        on_response: Optional[Callable[[str], None]] = None,
        turn_handler: Optional[Callable[[str], Any]] = None,
    ):
        self.db = db
        self.principal_id = principal_id
        self.session_id = session_id
        self.conversation_id = conversation_id or f"voice-{asyncio.get_event_loop().time()}"

        self.start_in_standby = start_in_standby
        self._user_on_state_change = on_state_change
        self._user_on_transcript = on_transcript
        self._user_on_response = on_response
        self.turn_handler = turn_handler

        self.session: Optional[VoiceSession] = None
        self._is_running = False

    def _handle_state_change(self, state: VoiceSessionState) -> None:
        broadcast_voice_event({"type": "state", "state": state.name})
        if self._user_on_state_change:
            self._user_on_state_change(state)

    def _handle_transcript(self, text: str, is_final: bool) -> None:
        broadcast_voice_event({"type": "transcript", "text": text, "is_final": is_final})
        if self._user_on_transcript:
            self._user_on_transcript(text, is_final)

    def _handle_response(self, text: str) -> None:
        broadcast_voice_event({"type": "response", "text": text})
        if self._user_on_response:
            self._user_on_response(text)

    @property
    def is_running(self) -> bool:
        return self._is_running and self.session is not None and not self.session.is_closed

    @property
    def state(self) -> VoiceSessionState:
        if self.session:
            return self.session.state
        return VoiceSessionState.CLOSED

    @property
    def is_active_conversation(self) -> bool:
        return bool(self.session and self.session.active_conversation)

    async def start(self) -> None:
        """Start the voice assistant session."""
        if self.is_running:
            logger.warning("Voice assistant already running.")
            return

        self.session = VoiceSession(
            db=self.db,
            conversation_id=self.conversation_id,
            principal_id=self.principal_id,
            session_id=self.session_id,
            start_in_standby=self.start_in_standby,
            close_on_timeout=False,  # Persist in STANDBY on timeout instead of disconnecting
            on_state_change=self._handle_state_change,
            on_transcript=self._handle_transcript,
            on_response=self._handle_response,
            turn_handler=self.turn_handler,
        )
        await self.session.start()
        self._is_running = True
        logger.info(f"Voice assistant started in state={self.session.state.name}")

    async def stop(self) -> None:
        """Stop and cleanly close the voice assistant session."""
        if self.session:
            await self.session.close()
            self.session = None
        self._is_running = False
        logger.info("Voice assistant stopped.")

    def push_to_talk(self) -> None:
        """Trigger push-to-talk activation directly into LISTENING state."""
        if not self.is_running or not self.session:
            raise RuntimeError("Voice assistant is not running.")
        self.session.trigger_push_to_talk()

    async def send_audio_chunk(self, chunk: bytes) -> None:
        """Feed raw audio bytes to STT."""
        if not self.is_running or not self.session:
            raise RuntimeError("Voice assistant is not running.")
        await self.session.process_audio_chunk(chunk)

    async def send_text(self, text: str) -> None:
        """Simulate spoken input through the voice pipeline."""
        if not self.is_running or not self.session:
            raise RuntimeError("Voice assistant is not running.")
        await self.session.process_audio_chunk(text.encode("utf-8"))

    def get_status(self) -> dict:
        """Return detailed voice engine status."""
        if not self.session:
            return {
                "running": False,
                "state": "CLOSED",
                "active_conversation": False,
                "conversation_id": None,
                "session_id": None,
                "wake_word": "Hey ULTRON",
                "timeout_seconds": 15.0,
            }

        return {
            "running": self._is_running and not self.session.is_closed,
            "state": self.session.state.name,
            "active_conversation": self.session.active_conversation,
            "conversation_id": self.session.conversation_id,
            "session_id": self.session.session_id,
            "wake_word": "Hey ULTRON",
            "timeout_seconds": self.session.timeout_seconds,
        }


def get_active_voice_assistant() -> Optional[VoiceAssistant]:
    global _active_assistant
    return _active_assistant


def set_active_voice_assistant(assistant: Optional[VoiceAssistant]) -> None:
    global _active_assistant
    _active_assistant = assistant
