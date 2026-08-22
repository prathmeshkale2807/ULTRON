from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.security.local_auth import Principal, require_local_auth
from app.devices.models import (
    DevicePairingRequest, DevicePairingCodeResponse, DevicePairRequest, 
    DevicePairResponse, DeviceHeartbeatRequest, DeviceResponse, DeviceStatus
)
from app.devices.manager import DeviceManager, DeviceAuthError

router = APIRouter(prefix="/devices", tags=["devices"])

@router.post("/pairing-code", response_model=DevicePairingCodeResponse)
def generate_pairing_code(
    request: DevicePairingRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth)
):
    manager = DeviceManager(db)
    record = manager.generate_pairing_code(principal.identity, request.device_name_hint)
    return DevicePairingCodeResponse(code=record.code, expires_at=record.expires_at)

@router.post("/pair", response_model=DevicePairResponse)
def pair_device(
    request: DevicePairRequest,
    db: Session = Depends(get_db)
):
    manager = DeviceManager(db)
    try:
        device_id, credential = manager.pair_device(request.code, request.device_name)
        return DevicePairResponse(device_id=device_id, credential=credential)
    except DeviceAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/heartbeat")
def heartbeat(
    request: DeviceHeartbeatRequest,
    db: Session = Depends(get_db)
):
    manager = DeviceManager(db)
    try:
        manager.heartbeat(request.device_id, request.credential)
        return {"status": "ok"}
    except DeviceAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("", response_model=list[DeviceResponse])
def list_devices(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth)
):
    manager = DeviceManager(db)
    devices = manager.list_devices(principal.identity)
    
    return [
        DeviceResponse(
            device_id=d.device_id,
            name=d.name,
            device_type=d.device_type,
            status=DeviceStatus(DeviceManager.get_computed_status(d)),
            last_heartbeat=d.last_heartbeat,
            created_at=d.created_at
        ) for d in devices
    ]
