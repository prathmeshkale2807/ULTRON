import json
import asyncio
import secrets
from uuid import uuid4
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.security.local_auth import get_or_create_local_token, _LOCAL_PRINCIPAL_IDENTITY
from app.devices.manager import DeviceManager, DeviceAuthError
from app.voice.engine import VoiceSession
from app.voice.models import VoiceConfig, AudioFormat

router = APIRouter(prefix="/voice", tags=["voice"])

@router.websocket("/ws")
async def voice_websocket(
    websocket: WebSocket, 
    token: str | None = None,
    device_id: str | None = None,
    credential: str | None = None,
    db: Session = Depends(get_db)
):
    await websocket.accept()
    
    try:
        principal_id = None
        session_id = None
        
        if device_id and credential:
            manager = DeviceManager(db)
            try:
                principal_id = manager.heartbeat(device_id, credential)
            except DeviceAuthError:
                await websocket.close(code=4001, reason="Unauthorized Android Device")
                return
        elif token:
            expected = get_or_create_local_token()
            if secrets.compare_digest(token, expected):
                principal_id = _LOCAL_PRINCIPAL_IDENTITY
            else:
                await websocket.close(code=4001, reason="Unauthorized Desktop Session")
                return
        else:
            await websocket.close(code=4001, reason="Authentication Required")
            return

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
