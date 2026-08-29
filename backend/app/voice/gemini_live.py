"""
ULTRON Gemini Live Voice Engine.

Replaces SAPI STT + pyttsx3 TTS with Gemini Live bidirectional audio streaming.
This is the same pipeline as the reference JARVIS project but wired into
ULTRON's ConversationManager, tools, security, and audit system.

Architecture:
  sounddevice mic (PCM 16kHz) --> Gemini Live session --> PCM 24kHz audio out
                                        |
                               ULTRON tool calls via ConversationManager

No wake word required — Gemini Live handles natural turn detection.
ULTRON is always listening once started.
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
from collections import deque
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Audio constants ────────────────────────────────────────────────────────────
INPUT_SAMPLE_RATE  = 16000   # mic → Gemini Live
OUTPUT_SAMPLE_RATE = 24000   # Gemini Live → speaker
CHANNELS           = 1
INPUT_BLOCK_SIZE   = 1600    # 100ms chunks at 16kHz
SILENCE_DURATION_MS = 800    # how long silence before Gemini considers turn done
PREFIX_PADDING_MS   = 160    # pre-speech audio kept before VAD triggers

# Voice used for ULTRON — deep, informative, JARVIS-like
ULTRON_VOICE = os.getenv("ULTRON_LIVE_VOICE", "charon")

ULTRON_SYSTEM_PROMPT = """You are ULTRON, a JARVIS-style personal AI assistant. 
You are direct, precise, and highly capable. You speak naturally and conversationally — 
short sentences, no filler. When asked to do something on the PC or phone, you do it 
immediately and confirm concisely. You refer to the user as 'sir'. 
Keep all spoken responses brief and natural — 1-3 sentences maximum unless explaining something complex.
Never say 'As an AI...' or 'I cannot...'. Just do it or explain why briefly."""

# Gemini Live model — confirmed working with AUDIO modality
LIVE_MODEL = os.getenv("ULTRON_LIVE_MODEL", "models/gemini-3.1-flash-live-preview")


class AudioEngine:
    """
    Minimal audio engine using sounddevice.
    Mic → queue for streaming to Gemini Live.
    Speaker ← PCM data from Gemini Live.
    Auto-mutes mic during playback to prevent feedback.
    """

    def __init__(self):
        self.mic_queue:      queue.Queue = queue.Queue(maxsize=300)
        self.playback_queue: queue.Queue = queue.Queue(maxsize=1000)
        self.stop_event  = threading.Event()
        self.mic_paused  = threading.Event()
        self.speaking    = threading.Event()
        self.recent_audio: deque = deque(maxlen=120)
        self._mic_stream = None
        self._spk_stream = None
        self._player_thread: Optional[threading.Thread] = None
        self.started = False

    def _mic_callback(self, indata, frames, time_info, status):
        if self.stop_event.is_set() or self.mic_paused.is_set() or self.speaking.is_set():
            return
        data = bytes(indata)
        self.recent_audio.append(data)
        try:
            self.mic_queue.put_nowait(data)
        except queue.Full:
            try:
                self.mic_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.mic_queue.put_nowait(data)
            except queue.Full:
                pass

    def start(self) -> None:
        if self.started:
            return
        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError(
                "sounddevice is not installed. Run: pip install sounddevice"
            )

        self.stop_event.clear()
        self._mic_stream = sd.RawInputStream(
            samplerate=INPUT_SAMPLE_RATE,
            blocksize=INPUT_BLOCK_SIZE,
            dtype="int16",
            channels=CHANNELS,
            callback=self._mic_callback,
        )
        self._mic_stream.start()

        self._spk_stream = sd.RawOutputStream(
            samplerate=OUTPUT_SAMPLE_RATE,
            blocksize=2400,
            dtype="int16",
            channels=CHANNELS,
        )
        self._spk_stream.start()

        self._player_thread = threading.Thread(
            target=self._playback_loop, daemon=True, name="ultron-audio-player"
        )
        self._player_thread.start()
        self.started = True

    def play_audio(self, data: bytes) -> None:
        if self.stop_event.is_set() or not data:
            return
        if self.playback_queue.empty():
            self._clear_mic()
        self.speaking.set()
        try:
            self.playback_queue.put_nowait(data)
        except queue.Full:
            self._clear_playback()
            try:
                self.playback_queue.put_nowait(data)
            except queue.Full:
                pass

    def _playback_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                data = self.playback_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if data is None:
                break
            try:
                self._spk_stream.write(data)
            except Exception:
                pass
            finally:
                if self.playback_queue.empty():
                    self.speaking.clear()
                    self._clear_mic()
        self.speaking.clear()

    def get_mic_audio(self, timeout: float = 0.15) -> Optional[bytes]:
        if self.mic_paused.is_set() or self.stop_event.is_set():
            return None
        try:
            return self.mic_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def pause_mic(self, paused: bool = True) -> None:
        if paused:
            self.mic_paused.set()
        else:
            self.mic_paused.clear()
        self._clear_mic()

    def _clear_mic(self) -> None:
        while True:
            try:
                self.mic_queue.get_nowait()
            except queue.Empty:
                break

    def _clear_playback(self) -> None:
        while True:
            try:
                self.playback_queue.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        if not self.started:
            return
        self.stop_event.set()
        self._clear_playback()
        self._clear_mic()
        try:
            self.playback_queue.put_nowait(None)
        except queue.Full:
            pass
        for stream in (self._mic_stream, self._spk_stream):
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        if self._player_thread:
            self._player_thread.join(timeout=2)
        self.started = False


class UltronLive:
    """
    Gemini Live voice session for ULTRON.

    Streams mic audio to Gemini Live, receives audio responses, and routes
    tool calls through ULTRON's ConversationManager (preserving SafetyGate,
    ConfirmationBroker, PermissionStore, and AuditLogger).
    """

    def __init__(
        self,
        audio: AudioEngine,
        send_message_fn: Callable[[str], str],
        on_transcript: Optional[Callable[[str, bool], None]] = None,
        on_response: Optional[Callable[[str], None]] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
    ):
        self.audio = audio
        self.send_message = send_message_fn
        self.on_transcript = on_transcript
        self.on_response = on_response
        self.on_state_change = on_state_change
        self.running = False
        self.session = None
        self._mic_task = None
        self._rx_task  = None

    def _emit_state(self, state: str) -> None:
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception:
                pass

    def _get_config(self):
        from google.genai import types

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=ULTRON_VOICE
                    )
                )
            ),
            # automatic_activity_detection is the correct field in genai 2.20
            # Leave as default (enabled) — Gemini handles VAD natively
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(
                parts=[types.Part(text=ULTRON_SYSTEM_PROMPT)]
            ),
        )

    async def _mic_loop(self) -> None:
        from google.genai import types
        while self.running:
            try:
                data = await asyncio.to_thread(self.audio.get_mic_audio, 0.15)
            except asyncio.CancelledError:
                break
            if not data or not self.session:
                continue
            try:
                await self.session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                )
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)

    async def _receive_loop(self) -> None:
        while self.running:
            try:
                await self._receive_one_turn()
                if self.running:
                    await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self.running:
                    logger.warning(f"Gemini Live receiver error: {exc}")
                break

    async def _receive_one_turn(self) -> None:
        async for response in self.session.receive():
            if not self.running:
                return

            content = response.server_content
            if not content:
                continue

            # Show what user said (input transcription)
            if content.input_transcription and content.input_transcription.text:
                text = content.input_transcription.text.strip()
                if text:
                    self._emit_state("LISTENING")
                    if self.on_transcript:
                        self.on_transcript(text, True)

            # Show what ULTRON is saying (output transcription)
            if content.output_transcription and content.output_transcription.text:
                text = content.output_transcription.text.strip()
                if text and self.on_response:
                    self.on_response(text)

            # Play audio from Gemini
            if content.model_turn:
                for part in content.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        self._emit_state("SPEAKING")
                        self.audio.play_audio(part.inline_data.data)

            # Barge-in: user spoke while ULTRON was talking
            if content.interrupted:
                self.audio._clear_playback()
                self._emit_state("LISTENING")

            # Turn complete → back to listening
            if content.turn_complete:
                self._emit_state("LISTENING")

    async def run(self) -> None:
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in backend/.env")

        client = genai.Client(api_key=api_key)

        self.running = True
        reconnect_delay = 0.5

        while self.running:
            self._emit_state("STANDBY")
            logger.info(f"Connecting to Gemini Live ({LIVE_MODEL})...")

            try:
                async with client.aio.live.connect(
                    model=LIVE_MODEL, config=self._get_config()
                ) as session:
                    self.session = session
                    self._emit_state("LISTENING")
                    logger.info("Gemini Live connected. ULTRON is listening.")

                    self._mic_task = asyncio.create_task(self._mic_loop())
                    self._rx_task  = asyncio.create_task(self._receive_loop())

                    while self.running and not self._rx_task.done():
                        await asyncio.sleep(0.1)

                    for task in (self._mic_task, self._rx_task):
                        if task:
                            task.cancel()
                    await asyncio.gather(
                        self._mic_task, self._rx_task, return_exceptions=True
                    )
                    self.session = None
                    reconnect_delay = 0.5

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.session = None
                if not self.running:
                    break
                logger.warning(f"Gemini Live error: {exc}. Reconnecting in {reconnect_delay:.1f}s...")
                self._emit_state("STANDBY")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 10.0)

        self.running = False
        self._emit_state("CLOSED")

    def stop(self) -> None:
        self.running = False
