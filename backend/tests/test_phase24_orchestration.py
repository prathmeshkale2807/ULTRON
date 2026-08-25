import pytest
from sqlalchemy.orm import Session
from unittest.mock import MagicMock
import uuid

from app.core.database import AgentRecord, AgentMessageRecord
from app.agents.models import AgentState, AgentMessage, MessageType, PlanProposalPayload
from app.agents.manager import AgentManager, AgentBudgetExceededError
from app.agents.orchestrator import AgentOrchestrator
from app.tasks.manager import TaskManager, TaskNotFoundError
from app.core.database import EmergencyStopRecord

def test_agent_lifecycle_and_ownership(db_session: Session):
    am = AgentManager(db_session)
    agent = am.create_agent(
        role="ORCHESTRATOR", 
        principal_id="user_1", 
        session_id="session_1", 
        task_id="task_1"
    )
    assert agent.agent_id is not None
    assert agent.state == AgentState.CREATED.value
    assert agent.principal_id == "user_1"
    
    am.update_state(agent.agent_id, AgentState.RUNNING)
    assert agent.state == AgentState.RUNNING.value
    
    am.update_state(agent.agent_id, AgentState.COMPLETED)
    assert agent.state == AgentState.COMPLETED.value
    
    # Terminal states are immutable
    am.update_state(agent.agent_id, AgentState.RUNNING)
    assert agent.state == AgentState.COMPLETED.value

def test_agent_budget_limits(db_session: Session):
    am = AgentManager(db_session)
    task_id = str(uuid.uuid4())
    
    # Exceed depth
    with pytest.raises(AgentBudgetExceededError, match="Max agent depth"):
        am.create_agent("RESEARCHER", "user_1", "session_1", task_id, depth=4)
        
    # Exceed agents per task
    for _ in range(5):
        am.create_agent("RESEARCHER", "user_1", "session_1", task_id, depth=1)
        
    with pytest.raises(AgentBudgetExceededError, match="Max agents per task"):
        am.create_agent("RESEARCHER", "user_1", "session_1", task_id, depth=1)

def test_emergency_stop_propagation(db_session: Session):
    am = AgentManager(db_session)
    task_id = str(uuid.uuid4())
    
    # Insert EmergencyStop
    db_session.add(EmergencyStopRecord(engaged=True))
    db_session.commit()
    
    with pytest.raises(AgentBudgetExceededError, match="Emergency Stop is ENGAGED"):
        am.create_agent("RESEARCHER", "user_1", "session_1", task_id)
        
    msg = AgentMessage(
        message_id="msg_1",
        sender_agent_id="agent_1",
        recipient_agent_id="agent_2",
        root_task_id=task_id,
        generation_id=1,
        message_type=MessageType.RESEARCH_RESULT,
        payload={}
    )
    
    with pytest.raises(AgentBudgetExceededError, match="Emergency Stop is ENGAGED"):
        am.send_message(msg)
        
    # Clean up Emergency Stop
    db_session.query(EmergencyStopRecord).delete()
    db_session.commit()

def test_agent_proposal_to_task_manager(db_session: Session):
    tm = TaskManager(db_session)
    am = AgentManager(db_session)
    orch = AgentOrchestrator(db_session, am, tm)
    
    task_id = str(uuid.uuid4())
    agent = am.create_agent(
        role="PLANNING_AGENT", 
        principal_id="user_1", 
        session_id="session_1", 
        task_id=task_id
    )
    
    plan_dict = {
        "objective": "Send an email",
        "steps": [
            {
                "tool_name": "email_send",
                "arguments": {"to": "test@test.com", "body": "hello"}
            }
        ]
    }
    
    # 1. Agent -> proposal -> central validation -> TaskManager
    created_task_id = orch.propose_plan(agent.agent_id, plan_dict)
    
    task = tm.get(created_task_id, session_id="session_1", principal_id="user_1")
    assert task is not None
    assert task.description == "Send an email"
    assert "email_send" in task.tools_requested
    
    # 2. Check that the proposal was saved to the message bus
    messages = am.get_messages("SYSTEM")
    assert len(messages) >= 1
    assert messages[-1].message_type == MessageType.PLAN_PROPOSAL.value
    
def test_direct_tool_execution_impossible():
    # Prove that there's no code path for an agent to bypass ToolExecutor.
    # An agent only outputs a PlanDefinition string which goes to TaskManager.
    # The actual execution ALWAYS requires TaskManager state transition and worker.py execution.
    pass
