import secrets
import string
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.database import DevicePairingCode, DeviceRecord

HEARTBEAT_TIMEOUT_SECONDS = 300

def _hash_credential(cred: str) -> str:
    return hashlib.sha256(cred.encode()).hexdigest()

class DeviceAuthError(Exception):
    pass

class DeviceManager:
    def __init__(self, db: Session):
        self.db = db
        
    def generate_pairing_code(self, principal_id: str, device_name_hint: str = "") -> DevicePairingCode:
        # Generate 6 digit alphanumeric code
        code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        
        record = DevicePairingCode(
            code=code,
            principal_id=principal_id,
            expires_at=expires_at,
            device_name_hint=device_name_hint
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def pair_device(self, code: str, device_name: str) -> tuple[str, str]:
        # Validate code
        record = self.db.get(DevicePairingCode, code)
        if not record:
            raise DeviceAuthError("Invalid pairing code")
            
        if record.used_at is not None:
            raise DeviceAuthError("Pairing code already used")
            
        now = datetime.now(timezone.utc)
        
        # handle naive vs aware comparison based on db returns
        expires = record.expires_at
        if expires.tzinfo is None:
            now = now.replace(tzinfo=None)
            
        if expires < now:
            raise DeviceAuthError("Pairing code expired")
            
        # Delete code so it is strictly single-use and not stored
        self.db.delete(record)
        
        device_id = str(uuid.uuid4())
        credential = secrets.token_urlsafe(32)
        
        device = DeviceRecord(
            device_id=device_id,
            principal_id=record.principal_id,
            name=device_name,
            device_type="ANDROID",
            credential_hash=_hash_credential(credential),
            status="PAIRED"
        )
        
        self.db.add(device)
        self.db.commit()
        return device_id, credential
        
    def heartbeat(self, device_id: str, credential: str) -> str:
        device = self.db.get(DeviceRecord, device_id)
        if not device:
            raise DeviceAuthError("Device not found")
            
        if device.status == "REVOKED":
            raise DeviceAuthError("Device revoked")
            
        if device.credential_hash != _hash_credential(credential):
            raise DeviceAuthError("Invalid credential")
            
        device.last_heartbeat = datetime.now(timezone.utc)
        self.db.commit()
        return device.principal_id

    def get_device(self, device_id: str, principal_id: str) -> DeviceRecord:
        device = self.db.get(DeviceRecord, device_id)
        if not device or device.principal_id != principal_id:
            raise DeviceAuthError("Device not found or ownership mismatch")
        return device

    def list_devices(self, principal_id: str) -> list[DeviceRecord]:
        return self.db.scalars(select(DeviceRecord).where(DeviceRecord.principal_id == principal_id)).all()
        
    def revoke_device(self, device_id: str, principal_id: str) -> None:
        device = self.get_device(device_id, principal_id)
        device.status = "REVOKED"
        self.db.commit()

    @staticmethod
    def get_computed_status(device: DeviceRecord) -> str:
        if device.status == "REVOKED":
            return "REVOKED"
            
        if not device.last_heartbeat:
            return "PAIRED"
            
        now = datetime.now(timezone.utc)
        last_heartbeat = device.last_heartbeat
        if last_heartbeat.tzinfo is None:
            now = now.replace(tzinfo=None)
            
        if (now - last_heartbeat).total_seconds() <= HEARTBEAT_TIMEOUT_SECONDS:
            return "ONLINE"
        return "OFFLINE"
