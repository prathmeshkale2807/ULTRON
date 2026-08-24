from enum import Enum
from typing import Any
from datetime import datetime
from pydantic import BaseModel, Field

class AgentState(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class MessageType(str, Enum):
    PLAN_PROPOSAL = "PLAN_PROPOSAL"
    RESEARCH_RESULT = "RESEARCH_RESULT"
    TASK_RESULT = "TASK_RESULT"
    REVIEW_RESULT = "REVIEW_RESULT"
    CANCEL = "CANCEL"
    ERROR = "ERROR"

class AgentMessage(BaseModel):
    message_id: str
    sender_agent_id: str
    recipient_agent_id: str
    root_task_id: str
    generation_id: int
    message_type: MessageType
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class PlanProposalPayload(BaseModel):
    proposal_id: str
    plan: dict[str, Any]  # The JSON plan matching PlanDefinition
