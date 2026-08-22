from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

class DeviceStatus(str, Enum):
    PAIRED = "PAIRED"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    REVOKED = "REVOKED"

class DevicePairingRequest(BaseModel):
    device_name_hint: str = Field(default="Android Device", max_length=128)

class DevicePairingCodeResponse(BaseModel):
    code: str
    expires_at: datetime

class DevicePairRequest(BaseModel):
    code: str
    device_name: str = Field(default="Android Device", max_length=128)

class DevicePairResponse(BaseModel):
    device_id: str
    credential: str  # Given once, device must store it securely

class DeviceHeartbeatRequest(BaseModel):
    device_id: str
    credential: str

class DeviceResponse(BaseModel):
    device_id: str
    name: str
    device_type: str
    status: DeviceStatus
    last_heartbeat: datetime | None
    created_at: datetime
