import json
import asyncio
import secrets
import time
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.security.local_auth import get_or_create_local_token, _LOCAL_PRINCIPAL_IDENTITY, Principal, require_local_auth
from app.devices.manager import DeviceManager, DeviceAuthError
from app.voice.engine import VoiceSession
from app.voice.models import VoiceConfig, AudioFormat
from app.voice.assistant import get_active_voice_assistant

router = APIRouter(prefix="/voice", tags=["voice"])

_voice_tickets = {}


class VoiceTicketRequest(BaseModel):
    device_id: str | None = None
    credential: str | None = None


class VoiceStatusResponse(BaseModel):
    status: str
    stt_configured: bool
    tts_configured: bool
    wake_word: str
    timeout_seconds: float
    microphone_available: bool = True
    microphone_name: Optional[str] = None
    speaker_available: bool = True
    speaker_name: Optional[str] = None
    active_session: Optional[dict] = None


@router.get("/status", response_model=VoiceStatusResponse)
def get_voice_status(
    principal: Principal = Depends(require_local_auth),
) -> VoiceStatusResponse:
    import os
    from app.voice.audio_device import get_microphone_info, get_speaker_info
    from app.voice.tts_provider import is_tts_available

    settings = get_settings()
    stt_key = os.getenv("DEEPGRAM_API_KEY")
    stt_ok = bool(stt_key and stt_key != "not_configured")

    mic = get_microphone_info()
    spk = get_speaker_info()
    tts_ok = is_tts_available()

    active_assistant = get_active_voice_assistant()
    active_status = active_assistant.get_status() if active_assistant else None

    return VoiceStatusResponse(
        status="ok",
        stt_configured=stt_ok,
        tts_configured=tts_ok,
        wake_word="Hey ULTRON",
        timeout_seconds=settings.voice_conversation_timeout_seconds,
        microphone_available=mic["available"],
        microphone_name=mic["name"],
        speaker_available=spk["available"],
        speaker_name=spk["name"],
        active_session=active_status,
    )


@router.post("/ticket")
def create_voice_ticket(
    request: VoiceTicketRequest,
    x_ultron_auth: str | None = Header(default=None),
    db: Session = Depends(get_db)
):
    principal_id = None
    if request.device_id and request.credential:
        manager = DeviceManager(db)
        try:
            principal_id = manager.heartbeat(request.device_id, request.credential)
        except DeviceAuthError as e:
            raise HTTPException(status_code=403, detail=str(e))
    elif x_ultron_auth:
        expected = get_or_create_local_token()
        if secrets.compare_digest(x_ultron_auth, expected):
            principal_id = _LOCAL_PRINCIPAL_IDENTITY
        else:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        raise HTTPException(status_code=401, detail="Authentication required")
        
    ticket = secrets.token_urlsafe(32)
    _voice_tickets[ticket] = {
        "principal_id": principal_id,
        "expires_at": time.time() + 30
    }
    return {"ticket": ticket}


@router.websocket("/ws")
async def voice_websocket(
    websocket: WebSocket, 
    ticket: str | None = None,
    db: Session = Depends(get_db)
):
    await websocket.accept()
    
    try:
        if not ticket or ticket not in _voice_tickets:
            await websocket.close(code=4001, reason="Authentication Required")
            return
            
        record = _voice_tickets.pop(ticket)
        if record["expires_at"] < time.time():
            await websocket.close(code=4001, reason="Ticket Expired")
            return
            
        principal_id = record["principal_id"]
        session_id = None

        try:
            config_msg = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            config_data = json.loads(config_msg)
            config = VoiceConfig(**config_data)
            
            supported_codecs = ["pcm", "opus"]
            if config.input_format.codec not in supported_codecs or config.output_format.codec not in supported_codecs:
                await websocket.send_text(json.dumps({"error": "Unsupported codec"}))
                await websocket.close(code=1003, reason="Unsupported codec")
                return
        except Exception:
            await websocket.close(code=1003, reason="Invalid Audio Format Config")
            return
            
        await websocket.send_text(json.dumps({"status": "ready"}))
        
        conversation_id = f"voice-{uuid4().hex[:8]}"
        voice_session = VoiceSession(db, conversation_id, principal_id, session_id)
        await voice_session.start()
        
        async def sender_task():
            try:
                while True:
                    chunk = await voice_session.ws_send_queue.get()
                    if chunk is None:
                        break
                    await websocket.send_bytes(chunk)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        async def receiver_task():
            try:
                while True:
                    data = await websocket.receive_bytes()
                    if len(data) > 1024 * 1024:
                        await websocket.close(code=1009, reason="Message too big")
                        break
                    await voice_session.process_audio_chunk(data)
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        sender = asyncio.create_task(sender_task())
        receiver = asyncio.create_task(receiver_task())

        done, pending = await asyncio.wait(
            [sender, receiver],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()
            
        await voice_session.close()
        
        # If we reach here because sender ended (e.g. emergency stop)
        # we ensure the socket gets closed if not already closed
        try:
            await websocket.close(code=1000)
        except Exception:
            pass

    except Exception:
        raise
