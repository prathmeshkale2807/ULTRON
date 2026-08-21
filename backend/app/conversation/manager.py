import json
from sqlalchemy.orm import Session
from app.core.database import ConversationRecord, MessageRecord
from app.conversation.schemas import ConversationStateEnum, MessageRoleEnum
from app.conversation.intent import extract_intent
from app.orchestrator.planner import create_plan
from app.conversation.response import generate_response
from app.tasks.manager import TaskManager
from app.tasks.models import TaskPriority
from app.tools.registry import get_registry
from app.memory.extractor import extract_memory_from_turn
from app.memory.store import MemoryStore

def _trigger_memory_extraction(provider, user_text, response_text, principal_id, db, session_id):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        store = MemoryStore(db, principal_id)
        loop.create_task(
            extract_memory_from_turn(provider, user_text, response_text, principal_id, store, session_id or "unknown")
        )
    except RuntimeError:
        pass # No event loop in this thread, synchronous test


class ConversationManager:
    def __init__(self, db: Session, provider_manager):
        self.db = db
        self.provider = provider_manager
        self.task_manager = TaskManager(db)

    def get_or_create(self, conversation_id: str, session_id: str | None = None) -> ConversationRecord:
        record = self.db.get(ConversationRecord, conversation_id)
        if not record:
            record = ConversationRecord(conversation_id=conversation_id, session_id=session_id)
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
        return record
        
    def add_message(self, conversation_id: str, role: str, content: str, metadata: dict | None = None) -> MessageRecord:
        msg = MessageRecord(
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata_json=json.dumps(metadata) if metadata else None
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def get_history(self, conversation_id: str, limit: int = 10) -> str:
        msgs = self.db.query(MessageRecord).filter_by(conversation_id=conversation_id).order_by(MessageRecord.timestamp.desc()).limit(limit).all()
        history = ""
        for m in reversed(msgs):
            history += f"{m.role.upper()}: {m.content}\n"
        return history

    async def process_turn(self, conversation_id: str, user_text: str, session_id: str | None = None, principal_id: str = "local") -> str:
        conv = self.get_or_create(conversation_id, session_id)
        self.add_message(conversation_id, MessageRoleEnum.USER, user_text)
        
        # Phase 9: Memory Retrieval
        from app.memory.store import MemoryStore
        memory_store = MemoryStore(self.db, principal_id)
        
        # A lightweight relevance heuristic for search query:
        # In a real system, we'd use embeddings. For now, we search words or just get top 5 overall.
        memories = memory_store.search(limit=5, session_id=session_id)
        memory_context = "User Memory Context:\n"
        
        # Determine maximum sensitivity required for the AI call
        max_sensitivity = "INTERNAL"
        sensitivity_levels = {"PUBLIC": 0, "INTERNAL": 1, "SENSITIVE": 2, "PRIVATE": 3}
        current_max = 1
        
        if memories:
            for mem in memories:
                memory_context += f"- [{mem.source_type.value}] ({mem.sensitivity.value}): {mem.content}\n"
                level = sensitivity_levels.get(mem.sensitivity.value, 1)
                if level > current_max:
                    current_max = level
                    max_sensitivity = mem.sensitivity.value
        else:
            memory_context += "None\n"
        
        # 1. Extract Intent
        history = self.get_history(conversation_id)
        
        # We append memory_context to history so intent and planner see it
        enriched_history = f"{memory_context}\nConversation History:\n{history}"
        
        intent = await extract_intent(self.provider, user_text, enriched_history, sensitivity=max_sensitivity)
        
        # 2. Check Cancellation
        if intent.intent_type == "CANCELLATION":
            if conv.active_task_id:
                self.task_manager.cancel(conv.active_task_id, session_id=session_id)
                conv.active_task_id = None
                self.db.commit()
            response_text = await generate_response(self.provider, "User cancelled the ongoing task.", "Task cancelled successfully.", sensitivity=max_sensitivity)
            self.add_message(conversation_id, MessageRoleEnum.ASSISTANT, response_text)
            return response_text
            
        # 3. Check Confidence / Clarification
        if intent.confidence in ["Low", "Medium"] and intent.clarification_needed:
            response_text = await generate_response(self.provider, f"Clarification needed: {intent.clarification_needed}", "", sensitivity=max_sensitivity)
            self.add_message(conversation_id, MessageRoleEnum.ASSISTANT, response_text)
            return response_text
            
        # 4. Plan if action
        if intent.intent_type in ["TOOL_ACTION", "MULTI_STEP_TASK"]:
            if conv.active_task_id:
                try:
                    # Cancel the stale/superseded task before starting a new one
                    old_task = self.task_manager.get(conv.active_task_id, session_id=session_id)
                    if old_task and old_task.state not in ["completed", "failed", "cancelled"]:
                        self.task_manager.cancel(conv.active_task_id, session_id=session_id)
                except Exception:
                    pass
                conv.active_task_id = None
                self.db.commit()

            registry = get_registry()
            tools_schema = json.dumps([{t.name: t.description} for t in registry.list_tools()])
            try:
                plan = await create_plan(self.provider, intent, tools_schema, sensitivity=max_sensitivity)
            except Exception as e:
                return f"Failed to plan: {e}"
                
            if not plan or not plan.steps:
                return "I couldn't figure out how to do that."
                
            # Submit to task manager
            tools_payload = []
            for step in plan.steps:
                tools_payload.append({
                    "tool_name": step.tool_name,
                    "arguments": step.arguments,
                    "target_device": step.target_device
                })
                
            task = self.task_manager.create(
                session_id=session_id,
                description=plan.objective,
                tools_requested=tools_payload
            )
            
            from app.tasks.worker import get_task_worker
            await get_task_worker().submit(task.task_id)
            
            conv.active_task_id = task.task_id
            self.db.commit()
            
            import asyncio
            for _ in range(20):
                self.db.refresh(task)
                if task.state in ["completed", "failed", "cancelled"]:
                    break
                await asyncio.sleep(0.1)
                
            history_entries = self.task_manager.get_audit_history(task.task_id, session_id=session_id)
            exec_results = "\n".join([f"{e.event}: {e.detail}" for e in history_entries])
            if not exec_results:
                exec_results = f"Task finished with state: {task.state}"
                if task.error_summary:
                    exec_results += f" Error: {task.error_summary}"
            
            response_text = await generate_response(self.provider, f"Planned task {task.task_id} with objective: {plan.objective} finished with state {task.state}.", exec_results, sensitivity=max_sensitivity)
            self.add_message(conversation_id, MessageRoleEnum.ASSISTANT, response_text)
            _trigger_memory_extraction(self.provider, user_text, response_text, principal_id, self.db, session_id)
            return response_text
            
        # 5. General conversation response
        response_text = await generate_response(self.provider, f"User asked a general question or conversational intent: {intent.requested_outcome}", "No tools executed.", sensitivity=max_sensitivity)
        self.add_message(conversation_id, MessageRoleEnum.ASSISTANT, response_text)
        _trigger_memory_extraction(self.provider, user_text, response_text, principal_id, self.db, session_id)
        return response_text

