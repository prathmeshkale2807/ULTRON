import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.database import MemoryRecord
from app.memory.models import MemoryCreate, MemoryUpdate, MemorySchema, MemoryStatus, MemoryType, MemorySensitivity
from app.core.logging_config import get_logger

logger = get_logger("memory.store")

class MemoryStore:
    def __init__(self, db: DBSession, principal_id: str):
        self.db = db
        self.principal_id = principal_id

    def create(self, data: MemoryCreate) -> MemorySchema:
        now = datetime.now(timezone.utc)
        record = MemoryRecord(
            memory_id=str(uuid.uuid4()),
            principal_id=self.principal_id,
            session_id=data.session_id,
            memory_type=data.memory_type,
            content=data.content,
            normalized_content=data.normalized_content,
            importance=data.importance,
            confidence=data.confidence,
            sensitivity=data.sensitivity,
            source_type=data.source_type,
            status=MemoryStatus.ACTIVE,
            version=1,
            created_at=now,
            updated_at=now,
            last_accessed_at=now,
            expires_at=data.expires_at,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return MemorySchema.model_validate(record)

    def get(self, memory_id: str) -> Optional[MemorySchema]:
        record = self.db.query(MemoryRecord).filter_by(
            memory_id=memory_id,
            principal_id=self.principal_id
        ).first()
        if not record:
            return None
        
        record.last_accessed_at = datetime.now(timezone.utc)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return MemorySchema.model_validate(record)

    def update(self, memory_id: str, data: MemoryUpdate) -> Optional[MemorySchema]:
        record = self.db.query(MemoryRecord).filter_by(
            memory_id=memory_id,
            principal_id=self.principal_id
        ).first()
        if not record:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(record, key, value)
            
        record.version += 1
        record.updated_at = datetime.now(timezone.utc)
        
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return MemorySchema.model_validate(record)

    def delete(self, memory_id: str, hard: bool = False) -> bool:
        record = self.db.query(MemoryRecord).filter_by(
            memory_id=memory_id,
            principal_id=self.principal_id
        ).first()
        if not record:
            return False
            
        if hard:
            self.db.delete(record)
        else:
            record.status = MemoryStatus.DELETED.value
            record.updated_at = datetime.now(timezone.utc)
            self.db.add(record)
            
        self.db.commit()
        return True

    def delete_all(self, hard: bool = False) -> int:
        records = self.db.query(MemoryRecord).filter_by(
            principal_id=self.principal_id
        ).all()
        
        count = len(records)
        if hard:
            for r in records:
                self.db.delete(r)
        else:
            for r in records:
                r.status = MemoryStatus.DELETED.value
                r.updated_at = datetime.now(timezone.utc)
                self.db.add(r)
                
        self.db.commit()
        return count

    def search(
        self,
        query: str = "",
        limit: int = 10,
        memory_types: Optional[List[MemoryType]] = None,
        include_archived: bool = False,
        session_id: Optional[str] = None
    ) -> List[MemorySchema]:
        now = datetime.now(timezone.utc)
        
        q = self.db.query(MemoryRecord).filter_by(principal_id=self.principal_id)
        
        if not include_archived:
            q = q.filter(MemoryRecord.status == MemoryStatus.ACTIVE.value)
        else:
            q = q.filter(MemoryRecord.status != MemoryStatus.DELETED.value)
            
        # Exclude expired
        q = q.filter((MemoryRecord.expires_at == None) | (MemoryRecord.expires_at > now))
        
        # Session scope isolation check
        # A new session can retrieve user's durable memory, but session-only memories remain session-scoped
        # If memory has session_id, it might be session-only if type is TEMPORARY or we enforce strictness.
        # Let's filter session_id if we want strictly session-scoped.
        # Wait, if memory is TEMPORARY, we scope it to the current session.
        if session_id:
            # allow durable memories (no session) OR memories owned by this session
            q = q.filter((MemoryRecord.session_id == None) | (MemoryRecord.session_id == session_id))
        else:
            # no active session context, only get global durable
            q = q.filter(MemoryRecord.session_id == None)

        if memory_types:
            q = q.filter(MemoryRecord.memory_type.in_([t.value for t in memory_types]))
            
        if query:
            # Simple LIKE for now. Vector search comes later.
            q = q.filter(MemoryRecord.content.ilike(f"%{query}%"))
            
        # Prioritize newer and explicit over inferred.
        # We can sort by importance, confidence, and created_at.
        q = q.order_by(
            MemoryRecord.importance.desc(),
            MemoryRecord.confidence.desc(),
            MemoryRecord.updated_at.desc()
        )
        
        records = q.limit(limit).all()
        return [MemorySchema.model_validate(r) for r in records]
