from app.core.database import EmergencyStopRecord
import json
import uuid
from typing import Any
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.core.database import AgentRecord, AgentMessageRecord
from app.agents.models import AgentState, AgentMessage, MessageType

class AgentBudgetExceededError(Exception):
    pass

def is_emergency_stop_active(db: Session) -> bool:
    record = db.query(EmergencyStopRecord).order_by(EmergencyStopRecord.id.desc()).first()
    return record and record.engaged

class AgentManager:
    MAX_DEPTH = 3
    MAX_AGENTS_PER_TASK = 5
    MAX_MESSAGES_PER_TASK = 50
    
    def __init__(self, db: Session):
        self.db = db
        
    def _check_budgets(self, task_id: str, depth: int):
        if depth > self.MAX_DEPTH:
            raise AgentBudgetExceededError(f"Max agent depth {self.MAX_DEPTH} exceeded.")
            
        agents_count = self.db.query(AgentRecord).filter_by(task_id=task_id).count()
        if agents_count >= self.MAX_AGENTS_PER_TASK:
            raise AgentBudgetExceededError(f"Max agents per task {self.MAX_AGENTS_PER_TASK} exceeded.")
            
    def create_agent(self, role: str, principal_id: str, session_id: str, task_id: str, parent_agent_id: str | None = None, depth: int = 1) -> AgentRecord:
        if is_emergency_stop_active(self.db):
            raise AgentBudgetExceededError("Emergency Stop is ENGAGED. Cannot spawn agents.")
        self._check_budgets(task_id, depth)
        
        # execution_id identifies a specific execution attempt
        execution_id = str(uuid.uuid4())
        
        agent = AgentRecord(
            agent_id=str(uuid.uuid4()),
            parent_agent_id=parent_agent_id,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            execution_id=execution_id,
            role=role,
            state=AgentState.CREATED.value,
            generation_id=1
        )
        self.db.add(agent)
        self.db.commit()
        return agent
        
    def send_message(self, message: AgentMessage):
        if is_emergency_stop_active(self.db):
            raise AgentBudgetExceededError("Emergency Stop is ENGAGED. Cannot send messages.")
        msgs_count = self.db.query(AgentMessageRecord).filter_by(root_task_id=message.root_task_id).count()
        if msgs_count >= self.MAX_MESSAGES_PER_TASK:
            raise AgentBudgetExceededError(f"Max messages per task {self.MAX_MESSAGES_PER_TASK} exceeded.")
            
        record = AgentMessageRecord(
            message_id=message.message_id,
            sender_agent_id=message.sender_agent_id,
            recipient_agent_id=message.recipient_agent_id,
            root_task_id=message.root_task_id,
            generation_id=message.generation_id,
            message_type=message.message_type.value,
            payload_json=json.dumps(message.payload)
        )
        self.db.add(record)
        self.db.commit()
        
    def get_messages(self, agent_id: str) -> list[AgentMessageRecord]:
        return self.db.query(AgentMessageRecord).filter_by(recipient_agent_id=agent_id).order_by(AgentMessageRecord.timestamp.asc()).all()
        
    def update_state(self, agent_id: str, state: AgentState):
        agent = self.db.query(AgentRecord).filter_by(agent_id=agent_id).first()
        if agent:
            # terminal states are immutable
            if agent.state in [AgentState.COMPLETED.value, AgentState.FAILED.value, AgentState.CANCELLED.value]:
                return
            agent.state = state.value
            self.db.commit()

    def cancel_task_agents(self, task_id: str):
        # Propagate cancellation
        agents = self.db.query(AgentRecord).filter_by(task_id=task_id).all()
        for a in agents:
            if a.state not in [AgentState.COMPLETED.value, AgentState.FAILED.value]:
                a.state = AgentState.CANCELLED.value
        self.db.commit()
