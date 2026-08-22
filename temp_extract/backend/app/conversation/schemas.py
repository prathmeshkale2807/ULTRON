from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any

class ConversationStateEnum(str, Enum):
    IDLE = "IDLE"
    RECEIVING = "RECEIVING"
    UNDERSTANDING = "UNDERSTANDING"
    CLARIFYING = "CLARIFYING"
    PLANNING = "PLANNING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    WAITING_FOR_RESULT = "WAITING_FOR_RESULT"
    RESPONDING = "RESPONDING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

class IntentTypeEnum(str, Enum):
    CONVERSATION = "CONVERSATION"
    QUESTION = "QUESTION"
    TOOL_ACTION = "TOOL_ACTION"
    MULTI_STEP_TASK = "MULTI_STEP_TASK"
    CLARIFICATION = "CLARIFICATION"
    CONFIRMATION = "CONFIRMATION"
    CANCELLATION = "CANCELLATION"
    CORRECTION = "CORRECTION"
    STATUS_REQUEST = "STATUS_REQUEST"
    FOLLOW_UP = "FOLLOW_UP"
    UNKNOWN = "UNKNOWN"

class MessageRoleEnum(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"

class MessageCreate(BaseModel):
    content: str
    metadata: dict[str, Any] | None = None

class MessageSchema(BaseModel):
    id: int
    conversation_id: str
    role: MessageRoleEnum
    content: str
    metadata_json: str | None
    timestamp: datetime

    class Config:
        from_attributes = True

class ConversationSchema(BaseModel):
    conversation_id: str
    session_id: str | None
    state: ConversationStateEnum
    active_task_id: str | None
    active_plan_id: str | None
    pending_confirmation_id: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

