from app.core.database import AgentRecord
import json
import uuid
from typing import Any
from sqlalchemy.orm import Session
from app.agents.manager import AgentManager, AgentBudgetExceededError
from app.agents.models import AgentState, AgentMessage, MessageType, PlanProposalPayload
from app.tasks.manager import TaskManager, TaskPriority
from app.orchestrator.planner import PlanDefinition, StepDefinition

class AgentOrchestrator:
    def __init__(self, db: Session, agent_manager: AgentManager, task_manager: TaskManager):
        self.db = db
        self.agent_manager = agent_manager
        self.task_manager = task_manager

    def propose_plan(self, agent_id: str, plan_definition_dict: dict[str, Any]) -> str:
        """Called by PLANNING_AGENT to propose a plan to the orchestrator/system."""
        plan = PlanDefinition(**plan_definition_dict)
        
        # Validates schema by instantiating PlanDefinition.
        
        # In a real system, Orchestrator would review it. For now, it just submits to TaskManager.
        agent = self.agent_manager.db.query(AgentRecord).filter_by(agent_id=agent_id).first()
        if not agent:
            raise ValueError("Agent not found")
            
        proposal_id = str(uuid.uuid4())
        payload = PlanProposalPayload(proposal_id=proposal_id, plan=plan_definition_dict)
        
        msg = AgentMessage(
            message_id=f"proposal_{proposal_id}_{agent.generation_id}",
            sender_agent_id=agent.agent_id,
            recipient_agent_id="SYSTEM",
            root_task_id=agent.task_id,
            generation_id=agent.generation_id,
            message_type=MessageType.PLAN_PROPOSAL,
            payload=payload.model_dump()
        )
        self.agent_manager.send_message(msg)
        
        # Forward to TaskManager
        tools_requested = [step.tool_name for step in plan.steps]
        task_record = self.task_manager.create(
            session_id=agent.session_id,
            description=plan.objective,
            priority=TaskPriority.NORMAL,
            tools_requested=tools_requested,
            actor=agent.principal_id
        )
        return task_record.task_id
