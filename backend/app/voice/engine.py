import re
import logging
import asyncio
from enum import Enum, auto
from typing import Optional
from sqlalchemy.orm import Session
from app.voice.stt_provider import get_stt_provider, STTProvider, STTEventType, STTMessage
from app.voice.tts_provider import get_tts_provider, TTSProvider
from app.conversation.manager import ConversationManager
from app.emergency.stop import EmergencyStop
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class VoiceSessionState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()
    INTERRUPTING = auto()
    CANCELLING = auto()
    DISCONNECTED = auto()
    CLOSED = auto()

class VoiceSession:
    def __init__(self, db: Session, conversation_id: str, principal_id: str, session_id: Optional[str] = None):
        self.db = db
        self.conversation_id = conversation_id
        self.principal_id = principal_id
        self.session_id = session_id
        self.stt: STTProvider = get_stt_provider()
        self.tts: TTSProvider = get_tts_provider()
        
        from app.ai_providers.factory import get_provider_manager
        self.conversation_manager = ConversationManager(db, get_provider_manager())
        
        # Background tasks
        self.stt_task: Optional[asyncio.Task] = None
        self.tts_task: Optional[asyncio.Task] = None
        self.generation_task: Optional[asyncio.Task] = None
        self.watchdog_task: Optional[asyncio.Task] = None
        
        self.ws_send_queue = asyncio.Queue(maxsize=100)
        self.is_closed = False
        self.state = VoiceSessionState.LISTENING
        self.last_activity = asyncio.get_running_loop().time()
        self.timeout_seconds = get_settings().voice_conversation_timeout_seconds
        
        self.generation_id = 0
        self.current_utterance_id = 0

    def _reset_watchdog(self):
        self.last_activity = asyncio.get_running_loop().time()

    async def _watchdog_loop(self):
        try:
            while not self.is_closed:
                await asyncio.sleep(0.5)
                if self.state == VoiceSessionState.LISTENING:
                    now = asyncio.get_running_loop().time()
                    if now - self.last_activity > self.timeout_seconds:
                        logger.info("Voice session inactivity timeout reached.")
                        await self.close()
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Watchdog Error: {e}")

    async def start(self):
        self.stt_task = asyncio.create_task(self._process_stt())
        self.watchdog_task = asyncio.create_task(self._watchdog_loop())
        
    async def process_audio_chunk(self, chunk: bytes):
        if self.is_closed:
            return
        await self.stt.stream_audio(chunk)

    async def _trigger_barge_in(self):
        self.state = VoiceSessionState.INTERRUPTING
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
                
        # Restart TTS
        await self.tts.close()
        self.tts = get_tts_provider()
        
        self.generation_id += 1
        self.state = VoiceSessionState.LISTENING
        self._reset_watchdog()

    async def _process_stt(self):
        try:
            async for stt_event in self.stt.get_transcripts():
                if stt_event.utterance_id < self.current_utterance_id:
                    continue
                
                if stt_event.event_type == STTEventType.SPEECH_STARTED:
                    if stt_event.utterance_id > self.current_utterance_id:
                        self.current_utterance_id = stt_event.utterance_id
                        if self.state in [VoiceSessionState.PROCESSING, VoiceSessionState.SPEAKING]:
                            await self._trigger_barge_in()
                            
                elif stt_event.event_type == STTEventType.FINAL_TRANSCRIPT:
                    text = stt_event.text.strip()
                    if not text:
                        continue
                    
                    if re.match(r"(?i)^ultron,?\s+(emergency\s+)?stop\.?$", text):
                        logger.warning("Voice Emergency Stop triggered!")
                        EmergencyStop(self.db).activate(
                            reason="Voice Kill Switch", 
                            activated_by=self.principal_id
                        )
                        await self.close()
                        break

                    if re.match(r"(?i)^(goodbye|stop listening|exit conversation)\.?$", text):
                        logger.info(f"Graceful exit command recognized: {text}")
                        await self.close()
                        break

                    self._reset_watchdog()
                    self.state = VoiceSessionState.PROCESSING
                    self.generation_id += 1
                    
                    self.generation_task = asyncio.create_task(self._generate_response(text, self.generation_id))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT Error: {e}")

    async def _generate_response(self, text: str, gen_id: int):
        try:
            response = await self.conversation_manager.process_turn(
                conversation_id=self.conversation_id,
                user_text=text,
                session_id=self.session_id,
                principal_id=self.principal_id
            )
            
            if gen_id != self.generation_id:
                logger.info("Generation stale, dropping.")
                return
                
            await self.tts.stream_text(response)
            await self.tts.flush()
            
            if gen_id == self.generation_id:
                self.state = VoiceSessionState.SPEAKING
                self.tts_task = asyncio.create_task(self._stream_tts(gen_id))
                
        except asyncio.CancelledError:
            logger.info("Generation task cancelled via barge-in.")
        except Exception as e:
            logger.error(f"Generation Error: {e}")
            if self.state in [VoiceSessionState.PROCESSING, VoiceSessionState.SPEAKING]:
                self.state = VoiceSessionState.LISTENING
                self._reset_watchdog()

    async def _stream_tts(self, gen_id: int):
        try:
            async for audio_chunk in self.tts.get_audio():
                if self.is_closed or gen_id != self.generation_id:
                    break
                await self.ws_send_queue.put(audio_chunk)
            
            if gen_id == self.generation_id and self.state == VoiceSessionState.SPEAKING:
                self.state = VoiceSessionState.LISTENING
                self._reset_watchdog()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"TTS Streaming Error: {e}")
            if gen_id == self.generation_id and self.state == VoiceSessionState.SPEAKING:
                self.state = VoiceSessionState.LISTENING
                self._reset_watchdog()

    async def close(self):
        self.is_closed = True
        self.state = VoiceSessionState.CLOSED
        
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
