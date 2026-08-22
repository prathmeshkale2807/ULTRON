import asyncio
import uuid
import json
from typing import Any
from fastapi import WebSocket
from app.devices.manager import DeviceManager

class TransportError(Exception):
    pass

class DeviceTimeoutError(TransportError):
    pass

class DeviceOfflineError(TransportError):
    pass


class WebSocketAndroidTransport:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WebSocketAndroidTransport, cls).__new__(cls)
            cls._instance.connections = {}  # device_id -> WebSocket
            cls._instance.pending_requests = {}  # request_id -> Future
        return cls._instance

    async def connect(self, device_id: str, websocket: WebSocket):
        self.connections[device_id] = websocket

    def disconnect(self, device_id: str):
        if device_id in self.connections:
            del self.connections[device_id]
        
        # Cancel all pending requests for this device
        # We need to find requests that belong to this device
        # Wait, if we just cancel them all, that's fine, but how do we know which belong to this device?
        # Let's attach device_id to the future or keep a separate map
        to_cancel = [
            req_id for req_id, fut in self.pending_requests.items()
            if getattr(fut, 'device_id', None) == device_id
        ]
        for req_id in to_cancel:
            fut = self.pending_requests.pop(req_id, None)
            if fut and not fut.done():
                fut.set_exception(DeviceOfflineError("DEVICE_OFFLINE"))

    async def dispatch(self, ctx: Any, device_id: str, action: str, payload: dict, timeout: float = 30.0) -> dict:
        if device_id not in self.connections:
            raise DeviceOfflineError("DEVICE_OFFLINE")
            
        ws = self.connections[device_id]
        # We use our own request_id for transport correlation
        request_id = f"req-{uuid.uuid4()}"
        
        fut = asyncio.get_running_loop().create_future()
        setattr(fut, 'device_id', device_id)
        # Store context attributes for correlation/audit
        setattr(fut, 'task_id', getattr(ctx, 'task_id', None))
        setattr(fut, 'principal_id', getattr(ctx, 'principal_id', None))
        
        self.pending_requests[request_id] = fut
        
        msg = {
            "request_id": request_id,
            "task_id": getattr(ctx, 'task_id', None),
            "principal_id": getattr(ctx, 'principal_id', None),
            "device_id": device_id,
            "action": action,
            "payload": payload
        }
        
        try:
            await ws.send_text(json.dumps(msg))
        except Exception as e:
            self.pending_requests.pop(request_id, None)
            self.disconnect(device_id)
            raise DeviceOfflineError("DEVICE_OFFLINE") from e
            
        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.pending_requests.pop(request_id, None)
            raise DeviceTimeoutError("DEVICE_TIMEOUT")
        except asyncio.CancelledError:
            self.pending_requests.pop(request_id, None)
            try:
                # Fire-and-forget cancellation frame
                asyncio.create_task(ws.send_text(json.dumps({"action": "cancel_task", "request_id": request_id})))
            except Exception:
                pass
            raise
            
    async def handle_response(self, device_id: str, data: dict):
        # Must match exactly
        request_id = data.get("request_id")
        if not request_id or request_id not in self.pending_requests:
            return  # Unknown or stale request ID
            
        fut = self.pending_requests[request_id]
        if getattr(fut, 'device_id', None) != device_id:
            return  # Cross-device mismatch
            
        self.pending_requests.pop(request_id, None)
        
        if not fut.done():
            status = data.get("status")
            if status == "success":
                fut.set_result(data.get("data", {}))
            elif status == "pending":
                pass # not implemented
            else:
                fut.set_exception(TransportError(data.get("error", "Unknown error")))

transport = WebSocketAndroidTransport()

def get_transport() -> WebSocketAndroidTransport:
    return transport
