from enum import Enum
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class MemoryType(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    PROFILE = "PROFILE"
    HABIT = "HABIT"
    PROJECT_CONTEXT = "PROJECT_CONTEXT"
    TASK_CONTEXT = "TASK_CONTEXT"
    RELATIONSHIP_CONTEXT = "RELATIONSHIP_CONTEXT"
    INSTRUCTION = "INSTRUCTION"
    TEMPORARY = "TEMPORARY"

class MemorySensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SENSITIVE = "SENSITIVE"
    PRIVATE = "PRIVATE"

class MemorySource(str, Enum):
    USER_DIRECT = "USER_DIRECT"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    CONVERSATION_INFERENCE = "CONVERSATION_INFERENCE"
    TASK_RESULT = "TASK_RESULT"
    EXTERNAL_DATA = "EXTERNAL_DATA"

class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"

class MemoryCreate(BaseModel):
    memory_type: MemoryType
    content: str
    normalized_content: Optional[str] = None
    importance: float = 1.0
    confidence: float = 1.0
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL
    source_type: MemorySource = MemorySource.CONVERSATION_INFERENCE
    expires_at: Optional[datetime] = None
    session_id: Optional[str] = None

class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    normalized_content: Optional[str] = None
    importance: Optional[float] = None
    confidence: Optional[float] = None
    sensitivity: Optional[MemorySensitivity] = None
    status: Optional[MemoryStatus] = None
    expires_at: Optional[datetime] = None

class MemorySchema(BaseModel):
    memory_id: str
    principal_id: str
    session_id: Optional[str]
    memory_type: MemoryType
    content: str
    normalized_content: Optional[str]
    importance: float
    confidence: float
    sensitivity: MemorySensitivity
    source_type: MemorySource
    status: MemoryStatus
    version: int
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True
