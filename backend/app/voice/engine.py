"""
ULTRON Voice Engine ? Phase 29: JARVIS-Style Voice Assistant.

State Machine:
  STANDBY -> (Wake word 'Hey ULTRON' or PTT) -> WAKE_DETECTED -> LISTENING
  LISTENING -> (Speech) -> PROCESSING -> (Response generated) -> SPEAKING
  SPEAKING -> (TTS completed) -> LISTENING  (NO WAKE WORD REQUIRED FOR FOLLOW-UPS)
  LISTENING -> (Inactivity timeout) -> STANDBY (or CLOSED if WebSocket single-turn)
  SPEAKING / PROCESSING -> (Barge-in speech) -> INTERRUPTING -> LISTENING

Security:
  - All voice turns route through ConversationManager (preserving SafetyGate,
    ConfirmationBroker, PermissionStore, and AuditLogger).
  - No tool handlers or AI providers are called directly from the voice layer.
  - ConfirmationBroker requests can be resolved naturally via voice ('yes' / 'no').
  - EmergencyStop ('ultron emergency stop' / 'ultron stop') engages the kill-switch.
"""

import asyncio
import logging
import re
from enum import Enum, auto
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.emergency.stop import EmergencyStop
from app.executor.confirmation import get_confirmation_broker
from app.voice.stt_provider import (
    STTEventType,
    STTMessage,
    STTProvider,
    get_stt_provider,
)
from app.voice.tts_provider import TTSProvider, get_tts_provider

logger = logging.getLogger(__name__)


class VoiceSessionState(Enum):
    IDLE = auto()
    STANDBY = auto()
    WAKE_DETECTED = auto()
    LISTENING = auto()
    TRANSCRIBING = auto()
    PROCESSING = auto()
    THINKING = auto()
    WAITING_FOR_CONFIRMATION = auto()
    EXECUTING = auto()
    VERIFYING = auto()
    SPEAKING = auto()
    INTERRUPTING = auto()
    CANCELLING = auto()
    ERROR = auto()
    DISCONNECTED = auto()
    CLOSED = auto()


# Wake words that activate ULTRON from STANDBY
# Kept narrow: only clear ULTRON variants, no short homophones like "ultra/electron/elton"
WAKE_WORD_PATTERN = re.compile(
    r"(?i)^(?:hey\s+|okay\s+|ok\s+)?(?:ultron|altron|outron|oltron|autron|all\s*tron)(?:[,.!?\s]+(.*))?$"
)

# Direct commands that bypass wake word from STANDBY (must start with action verb)
DIRECT_COMMAND_PATTERN = re.compile(
    r"(?i)^(?:open|close|launch|exit|write|type|take|capture|go\s+to|search|turn|send|get|show|run|start|stop|play|pause|set|find|check)\s+.+$"
)

# Natural confirmation patterns
CONFIRM_YES_PATTERN = re.compile(
    r"(?i)^(?:yes(?:,?\s+(?:do\s+it|please|confirm|proceed))?|confirm|go\s+ahead|continue|sure|yep|yeah|proceed|approved|do\s+it|ok|okay)[.!]?$"
)
CONFIRM_NO_PATTERN = re.compile(
    r"(?i)^(?:no(?:,?\s+(?:cancel|stop|don'?t|deny))?|cancel|stop|don'?t\s+do\s+it|deny|never\s+mind|forget\s+it|reject|disapproved)[.!]?$"
)

# Emergency stop pattern
EMERGENCY_STOP_PATTERN = re.compile(r"(?i)^ultron,?\s+(?:emergency\s+)?stop\.?$")

# Exit / Sleep pattern
EXIT_PATTERN = re.compile(
    r"(?i)^(?:goodbye|stop\s+listening|exit\s+conversation|sleep|standby)\.?$"
)


class VoiceSession:
    """
    Full-duplex, JARVIS-style voice session supporting wake-word activation,
    continuous active conversation without repeated wake-words, barge-in,
    watchdog timeouts, and natural voice confirmation.
    """

    def __init__(
        self,
        db: Session,
        conversation_id: str,
        principal_id: str,
        session_id: Optional[str] = None,
        *,
        start_in_standby: bool = False,
        close_on_timeout: bool = True,
        on_state_change: Optional[Callable[[VoiceSessionState], None]] = None,
        on_transcript: Optional[Callable[[str, bool], None]] = None,
        on_response: Optional[Callable[[str], None]] = None,
        turn_handler: Optional[Callable[[str], Any]] = None,
    ):
        self.db = db
        self.conversation_id = conversation_id
        self.principal_id = principal_id
        self.session_id = session_id

        self.start_in_standby = start_in_standby
        self.close_on_timeout = close_on_timeout
        self.on_state_change = on_state_change
        self.on_transcript = on_transcript
        self.on_response = on_response
        self.turn_handler = turn_handler

        self.stt: STTProvider = get_stt_provider()
        self.tts: TTSProvider = get_tts_provider()

        from app.ai_providers.factory import get_provider_manager
        from app.conversation.manager import ConversationManager

        self.conversation_manager = ConversationManager(
            db, get_provider_manager()
        )

        # Background tasks
        self.stt_task: Optional[asyncio.Task] = None
        self.tts_task: Optional[asyncio.Task] = None
        self.generation_task: Optional[asyncio.Task] = None
        self.watchdog_task: Optional[asyncio.Task] = None

        self.ws_send_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.is_closed = False

        if start_in_standby:
            self.state = VoiceSessionState.STANDBY
            self.active_conversation = False
        else:
            self.state = VoiceSessionState.LISTENING
            self.active_conversation = True

        try:
            self.last_activity = asyncio.get_running_loop().time()
        except RuntimeError:
            import time
            self.last_activity = time.time()
        self.timeout_seconds = (
            get_settings().voice_conversation_timeout_seconds
        )

        self.generation_id = 0
        self.current_utterance_id = 0

    def set_state(self, new_state: VoiceSessionState) -> None:
        self.state = new_state
        if self.on_state_change:
            try:
                self.on_state_change(new_state)
            except Exception as e:
                logger.warning(f"State change callback error: {e}")

        # Wire STT grammar mode to voice state:
        # LISTENING/PROCESSING/SPEAKING → dictation (free speech)
        # STANDBY → wake-word only (no hallucination)
        if new_state in (
            VoiceSessionState.LISTENING,
            VoiceSessionState.PROCESSING,
            VoiceSessionState.THINKING,
            VoiceSessionState.EXECUTING,
            VoiceSessionState.SPEAKING,
            VoiceSessionState.WAKE_DETECTED,
        ):
            self.stt.set_listening_mode()
        elif new_state in (
            VoiceSessionState.STANDBY,
            VoiceSessionState.IDLE,
            VoiceSessionState.CLOSED,
        ):
            self.stt.set_standby_mode()

    def _reset_watchdog(self) -> None:
        try:
            self.last_activity = asyncio.get_running_loop().time()
        except RuntimeError:
            import time
            self.last_activity = time.time()

    async def _watchdog_loop(self) -> None:
        try:
            while not self.is_closed:
                await asyncio.sleep(0.5)
                if self.state == VoiceSessionState.LISTENING:
                    now = asyncio.get_running_loop().time()
                    if now - self.last_activity > self.timeout_seconds:
                        logger.info(
                            "Voice session inactivity timeout reached."
                        )
                        if self.close_on_timeout:
                            await self.close()
                            break
                        else:
                            # In persistent local mode, transition from LISTENING to STANDBY
                            self.active_conversation = False
                            self.set_state(VoiceSessionState.STANDBY)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Watchdog Error: {e}")

    async def start(self) -> None:
        self.stt_task = asyncio.create_task(self._process_stt())
        self.watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def process_audio_chunk(self, chunk: bytes) -> None:
        if self.is_closed:
            return
        await self.stt.stream_audio(chunk)

    def trigger_push_to_talk(self) -> None:
        """Push-to-talk activation: transitions from STANDBY to LISTENING."""
        if self.is_closed:
            return
        self.active_conversation = True
        self.set_state(VoiceSessionState.LISTENING)
        self._reset_watchdog()
        logger.info("Push-to-talk activated: entered LISTENING state.")

    async def _trigger_barge_in(self) -> None:
        self.set_state(VoiceSessionState.INTERRUPTING)
        logger.info("Barge-in detected via speech start.")

        if self.generation_task and not self.generation_task.done():
            self.generation_task.cancel()
        if self.tts_task and not self.tts_task.done():
            self.tts_task.cancel()

        # Flush the WS queue
        while not self.ws_send_queue.empty():
            try:
                self.ws_send_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Restart TTS provider
        await self.tts.close()
        self.tts = get_tts_provider()

        self.generation_id += 1
        self.set_state(VoiceSessionState.LISTENING)
        self._reset_watchdog()

    async def _process_stt(self) -> None:
        try:
            async for stt_event in self.stt.get_transcripts():
                if stt_event.utterance_id < self.current_utterance_id:
                    continue

                if stt_event.event_type == STTEventType.SPEECH_STARTED:
                    if stt_event.utterance_id > self.current_utterance_id:
                        self.current_utterance_id = stt_event.utterance_id
                        # When speaking aloud, any speech cuts in
                        if self.state == VoiceSessionState.SPEAKING:
                            await self._trigger_barge_in()

                elif stt_event.event_type == STTEventType.PARTIAL_TRANSCRIPT:
                    if self.on_transcript and stt_event.text:
                        self.on_transcript(stt_event.text, False)
                    # Explicit stop/cancel keywords interrupt even during processing
                    p_text = (stt_event.text or "").lower()
                    if any(kw in p_text for kw in ("stop", "cancel", "halt", "abort", "quiet")):
                        if self.state in [
                            VoiceSessionState.PROCESSING,
                            VoiceSessionState.THINKING,
                            VoiceSessionState.SPEAKING,
                        ]:
                            await self._trigger_barge_in()

                elif stt_event.event_type == STTEventType.FINAL_TRANSCRIPT:
                    text = stt_event.text.strip()
                    if not text:
                        continue

                    if self.on_transcript:
                        self.on_transcript(text, True)

                    # 1. Check Emergency Stop Kill Switch
                    if EMERGENCY_STOP_PATTERN.match(text):
                        logger.warning("Voice Emergency Stop triggered!")
                        EmergencyStop(self.db).activate(
                            reason="Voice Kill Switch",
                            activated_by=self.principal_id,
                        )
                        await self.close()
                        break

                    # 2. Check Graceful Exit / Sleep
                    if EXIT_PATTERN.match(text):
                        logger.info(f"Graceful exit command recognized: {text}")
                        if self.close_on_timeout:
                            await self.close()
                            break
                        else:
                            self.active_conversation = False
                            self.set_state(VoiceSessionState.STANDBY)
                            continue

                    # 3. STANDBY mode: Check for Wake Word or Direct Command
                    if (
                        self.state == VoiceSessionState.STANDBY
                        or not self.active_conversation
                    ):
                        match = WAKE_WORD_PATTERN.match(text)
                        if match:
                            self.active_conversation = True
                            self.set_state(VoiceSessionState.WAKE_DETECTED)
                            remainder = match.group(1)

                            if remainder and remainder.strip():
                                # Wake word + command spoken together ('Hey ULTRON open Chrome')
                                self._reset_watchdog()
                                self.set_state(VoiceSessionState.PROCESSING)
                                self.generation_id += 1
                                self.generation_task = asyncio.create_task(
                                    self._generate_response(
                                        remainder.strip(), self.generation_id
                                    )
                                )
                            else:
                                # Just wake word spoken ('Hey ULTRON') -> Greet user and listen
                                self._reset_watchdog()
                                self.generation_id += 1
                                self.generation_task = asyncio.create_task(
                                    self._speak_activation_greeting(
                                        self.generation_id
                                    )
                                )
                        elif DIRECT_COMMAND_PATTERN.match(text):
                            # Direct command spoken in STANDBY without explicit wake word prefix ('Close Chrome', 'Write hello')
                            self.active_conversation = True
                            self._reset_watchdog()
                            self.set_state(VoiceSessionState.PROCESSING)
                            self.generation_id += 1
                            self.generation_task = asyncio.create_task(
                                self._generate_response(
                                    text.strip(), self.generation_id
                                )
                            )
                        else:
                            # Ignored in STANDBY (background noise / unaddressed speech)
                            logger.debug(
                                f"Ignoring speech in STANDBY without wake word: {text}"
                            )
                            continue

                    # 4. ACTIVE CONVERSATION MODE: Process command directly without wake word
                    else:
                        self._reset_watchdog()

                        # Check if a confirmation is pending on ConfirmationBroker
                        broker = get_confirmation_broker()
                        pending = [
                            req
                            for req in broker.list_pending()
                            if req.principal_id == self.principal_id
                        ]

                        if pending:
                            pending_req = pending[0]
                            if CONFIRM_YES_PATTERN.match(text):
                                broker.resolve(
                                    pending_req.id,
                                    True,
                                    resolved_by="voice_user",
                                )
                                self._reset_watchdog()
                                self.generation_id += 1
                                self.generation_task = asyncio.create_task(
                                    self._speak_quick_ack(
                                        "Confirmed.", self.generation_id
                                    )
                                )
                                continue
                            elif CONFIRM_NO_PATTERN.match(text):
                                broker.resolve(
                                    pending_req.id,
                                    False,
                                    resolved_by="voice_user",
                                )
                                self._reset_watchdog()
                                self.generation_id += 1
                                self.generation_task = asyncio.create_task(
                                    self._speak_quick_ack(
                                        "Cancelled.", self.generation_id
                                    )
                                )
                                continue

                        # Clean any redundant wake-word prefix if user said it anyway
                        clean_text = text
                        wake_match = WAKE_WORD_PATTERN.match(text)
                        if wake_match and wake_match.group(1):
                            clean_text = wake_match.group(1).strip()

                        self.set_state(VoiceSessionState.PROCESSING)
                        self.generation_id += 1
                        self.generation_task = asyncio.create_task(
                            self._generate_response(
                                clean_text, self.generation_id
                            )
                        )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT Error: {e}")

    async def _speak_activation_greeting(self, gen_id: int) -> None:
        """Speak natural JARVIS activation acknowledgement and transition to LISTENING."""
        greeting = "Yes, sir?"
        try:
            if self.on_response:
                self.on_response(greeting)
            await self.tts.stream_text(greeting)
            await self.tts.flush()

            if gen_id == self.generation_id:
                self.set_state(VoiceSessionState.SPEAKING)
                self.tts_task = asyncio.create_task(self._stream_tts(gen_id))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Greeting Error: {e}")
            if gen_id == self.generation_id:
                self.set_state(VoiceSessionState.LISTENING)
                self._reset_watchdog()

    async def _speak_quick_ack(self, ack_text: str, gen_id: int) -> None:
        """Speak quick acknowledgement for confirmation/cancellation."""
        try:
            if self.on_response:
                self.on_response(ack_text)
            await self.tts.stream_text(ack_text)
            await self.tts.flush()

            if gen_id == self.generation_id:
                self.set_state(VoiceSessionState.SPEAKING)
                self.tts_task = asyncio.create_task(self._stream_tts(gen_id))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Quick Ack Error: {e}")
            if gen_id == self.generation_id:
                self.set_state(VoiceSessionState.LISTENING)
                self._reset_watchdog()

    async def _generate_response(self, text: str, gen_id: int) -> None:
        try:
            if self.turn_handler:
                if asyncio.iscoroutinefunction(self.turn_handler):
                    response = await self.turn_handler(text)
                else:
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(None, self.turn_handler, text)
            else:
                response = await self.conversation_manager.process_turn(
                    conversation_id=self.conversation_id,
                    user_text=text,
                    session_id=self.session_id,
                    principal_id=self.principal_id,
                )

            if gen_id != self.generation_id:
                logger.info("Generation stale, dropping.")
                return

            # Ensure response is always a non-empty string
            if not response or not str(response).strip():
                response = "Done."

            response = str(response).strip()

            if self.on_response:
                self.on_response(response)

            await self.tts.stream_text(response)
            await self.tts.flush()

            if gen_id == self.generation_id:
                self.set_state(VoiceSessionState.SPEAKING)
                self.tts_task = asyncio.create_task(self._stream_tts(gen_id))

        except asyncio.CancelledError:
            logger.info("Generation task cancelled via barge-in.")
        except Exception as e:
            logger.error(f"Generation Error: {e}")
            # Always recover to LISTENING so ULTRON doesn't get stuck
            if gen_id == self.generation_id and self.state in [
                VoiceSessionState.PROCESSING,
                VoiceSessionState.THINKING,
                VoiceSessionState.SPEAKING,
            ]:
                error_msg = "I encountered an error. Please try again."
                try:
                    await self.tts.stream_text(error_msg)
                    await self.tts.flush()
                    self.set_state(VoiceSessionState.SPEAKING)
                    self.tts_task = asyncio.create_task(self._stream_tts(gen_id))
                except Exception:
                    self.set_state(VoiceSessionState.LISTENING)
                    self._reset_watchdog()

    async def _stream_tts(self, gen_id: int) -> None:
        try:
            async for audio_chunk in self.tts.get_audio():
                if self.is_closed or gen_id != self.generation_id:
                    break
                await self.ws_send_queue.put(audio_chunk)

            # CRITICAL JARVIS BEHAVIOUR:
            # When speaking finishes, automatically return to LISTENING and reset the watchdog
            if (
                gen_id == self.generation_id
                and self.state == VoiceSessionState.SPEAKING
            ):
                self.set_state(VoiceSessionState.LISTENING)
                self._reset_watchdog()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"TTS Streaming Error: {e}")
            if (
                gen_id == self.generation_id
                and self.state == VoiceSessionState.SPEAKING
            ):
                self.set_state(VoiceSessionState.LISTENING)
                self._reset_watchdog()

    async def close(self) -> None:
        self.is_closed = True
        self.set_state(VoiceSessionState.CLOSED)

        current_task = asyncio.current_task()
        tasks_to_await = []
        if self.watchdog_task and self.watchdog_task != current_task:
            self.watchdog_task.cancel()
            tasks_to_await.append(self.watchdog_task)
        if self.stt_task and self.stt_task != current_task:
            self.stt_task.cancel()
            tasks_to_await.append(self.stt_task)
        if self.generation_task and self.generation_task != current_task:
            self.generation_task.cancel()
            tasks_to_await.append(self.generation_task)
        if self.tts_task and self.tts_task != current_task:
            self.tts_task.cancel()
            tasks_to_await.append(self.tts_task)

        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

        await self.stt.close()
        await self.tts.close()

        await self.ws_send_queue.put(None)
