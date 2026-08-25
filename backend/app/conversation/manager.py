from fastapi.concurrency import run_in_threadpool
import base64
import asyncio
from app.core.images import process_image
from app.conversation.attachments import save_attachment, get_attachment
from app.ai_providers.base import ContentPart
from app.tasks.worker import get_task_worker
from app.tasks.manager import _volatile_tool_results
from app.core.database import TaskRecord
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

    
    async def process_turn(self, conversation_id: str, user_text: str, session_id: str | None, principal_id: str, metadata: dict | None = None) -> str:
        from app.tools.registry import get_registry
    
        # --- Phase 1: Sync Context Prep ---
        def _prepare_context():
            conv = self.get_or_create(conversation_id, session_id)
            
            stored_refs = []
            if metadata and "attachments" in metadata:
                raw_attachments = metadata.pop("attachments")
                for att in raw_attachments:
                    try:
                        data = base64.b64decode(att["data_base64"])
                        mime, norm_data = process_image(data)
                        record = save_attachment(
                            db=self.db,
                            principal_id=principal_id,
                            conversation_id=conversation_id,
                            mime_type=mime,
                            data=norm_data
                        )
                        stored_refs.append({"attachment_id": record.attachment_id, "mime_type": mime})
                    except Exception as e:
                        logger.warning(f"Failed to process attachment: {e}")
                        
            if stored_refs:
                metadata["attachments"] = stored_refs
    
            msg = self.add_message(
                conversation_id, 
                MessageRoleEnum.USER, 
                user_text,
                metadata=metadata
            )
            
            # Update message_id on the saved attachments
            if stored_refs:
                from app.core.database import AttachmentRecord
                from sqlalchemy import update
                self.db.execute(
                    update(AttachmentRecord)
                    .where(AttachmentRecord.attachment_id.in_([r["attachment_id"] for r in stored_refs]))
                    .values(message_id=msg.id)
                )
                self.db.commit()
    
            memory_store = MemoryStore(self.db, principal_id)
            memories = memory_store.search(limit=5, session_id=session_id)
            memory_context = "User Memory Context:\n"
            
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
                
            history = self.get_history(conversation_id)
            enriched_history = f"{memory_context}\nConversation History:\n{history}"
            
            current_message = user_text
            if stored_refs:
                parts = [ContentPart(type="text", text=user_text)]
                for ref in stored_refs:
                    try:
                        _, data = get_attachment(self.db, ref["attachment_id"], principal_id)
                        parts.append(ContentPart(type="image", mime_type=ref["mime_type"], data=data))
                    except Exception:
                        pass
                current_message = parts
                
            return conv.active_task_id, enriched_history, current_message, max_sensitivity
            
        active_task_id, enriched_history, current_message, max_sensitivity = await run_in_threadpool(_prepare_context)
        
        intent = await extract_intent(self.provider, current_message, enriched_history, sensitivity=max_sensitivity)
        
        # --- Phase 2: Intent Handling ---
        if intent.intent_type == "CANCELLATION":
            def _cancel_and_get_response():
                if active_task_id:
                    self.task_manager.cancel(active_task_id, session_id=session_id)
                    conv = self.get_or_create(conversation_id, session_id)
                    conv.active_task_id = None
                    self.db.commit()
            await run_in_threadpool(_cancel_and_get_response)
            
            response_text = await generate_response(self.provider, "User cancelled the ongoing task.", "Task cancelled successfully.", sensitivity=max_sensitivity)
            await run_in_threadpool(self.add_message, conversation_id, MessageRoleEnum.ASSISTANT, response_text)
            return response_text
            
        if intent.confidence in ["Low", "Medium"] and intent.clarification_needed:
            response_text = await generate_response(self.provider, f"Clarification needed: {intent.clarification_needed}", "", sensitivity=max_sensitivity)
            await run_in_threadpool(self.add_message, conversation_id, MessageRoleEnum.ASSISTANT, response_text)
            return response_text
            
        if intent.intent_type in ["TOOL_ACTION", "MULTI_STEP_TASK"]:
            def _cleanup_old_task():
                if active_task_id:
                    try:
                        old_task = self.task_manager.get(active_task_id, session_id=session_id)
                        if old_task and old_task.state not in ["completed", "failed", "cancelled"]:
                            self.task_manager.cancel(active_task_id, session_id=session_id)
                    except Exception:
                        pass
                    conv = self.get_or_create(conversation_id, session_id)
                    conv.active_task_id = None
                    self.db.commit()
            await run_in_threadpool(_cleanup_old_task)
    
            registry = get_registry()
            tools_schema = json.dumps([{t.name: t.description} for t in registry.list_tools()])
            try:
                plan = await create_plan(self.provider, intent, tools_schema, sensitivity=max_sensitivity, current_message=current_message)
            except Exception as e:
                return f"Failed to plan: {e}"
                
            if not plan or not plan.steps:
                return "I couldn't figure out how to do that."
                
            tools_payload = [{"tool_name": s.tool_name, "arguments": s.arguments, "target_device": s.target_device} for s in plan.steps]
            
            def _create_task():
                t = self.task_manager.create(
                    session_id=session_id,
                    description=plan.objective,
                    tools_requested=tools_payload
                )
                conv = self.get_or_create(conversation_id, session_id)
                conv.active_task_id = t.task_id
                self.db.commit()
                return t.task_id
                
            new_task_id = await run_in_threadpool(_create_task)
            await get_task_worker().submit(new_task_id)
            
            # Async polling using threadpool to prevent blocking the event loop
            task_state = "queued"
            task_error = None
            for _ in range(20):
                def _check_status():
                    t = self.db.get(TaskRecord, new_task_id)
                    return getattr(t, "state", "unknown"), getattr(t, "error_summary", None)
                task_state, task_error = await run_in_threadpool(_check_status)
                if task_state in ["completed", "failed", "cancelled"]:
                    break
                await asyncio.sleep(0.1)
                
            def _get_history_and_results():
                history_entries = self.task_manager.get_audit_history(new_task_id, session_id=session_id, principal_id=principal_id)
                volatile_results = _volatile_tool_results.pop(new_task_id, [])
                return history_entries, volatile_results
                
            history_entries, volatile_results = await run_in_threadpool(_get_history_and_results)
            
            exec_results = ""
            visual_context = []
            for e in history_entries:
                try:
                    detail_data = json.loads(e.detail)
                    exec_results += f"{e.event}: {json.dumps(detail_data)}\n"
                except Exception:
                    exec_results += f"{e.event}: {e.detail}\n"
                    
            for res in volatile_results:
                out = res.get("output", {})
                if isinstance(out, dict) and "image_base64_secret" in out:
                    b64 = out.pop("image_base64_secret")
                    try:
                        decoded = base64.b64decode(b64)
                        visual_context.append(ContentPart(type="image", mime_type="image/png", data=decoded))
                    except Exception:
                        pass
                exec_results += f"Tool {res.get('tool_name')} result: {json.dumps(out)}\n"
                    
            if not exec_results.strip():
                exec_results = f"Task finished with state: {task_state}"
                if task_error:
                    exec_results += f" Error: {task_error}"
            
            response_text = await generate_response(
                self.provider, 
                f"Planned task {new_task_id} with objective: {plan.objective} finished with state {task_state}.", 
                exec_results, 
                sensitivity=max_sensitivity,
                visual_context=visual_context if visual_context else None
            )
            await run_in_threadpool(self.add_message, conversation_id, MessageRoleEnum.ASSISTANT, response_text)
            from app.conversation.manager import _trigger_memory_extraction
            _trigger_memory_extraction(self.provider, user_text, response_text, principal_id, self.db, session_id)
            return response_text
            
        response_text = await generate_response(self.provider, f"User asked a general question or conversational intent: {intent.requested_outcome}", "No tools executed.", sensitivity=max_sensitivity)
        await run_in_threadpool(self.add_message, conversation_id, MessageRoleEnum.ASSISTANT, response_text)
        from app.conversation.manager import _trigger_memory_extraction
        _trigger_memory_extraction(self.provider, user_text, response_text, principal_id, self.db, session_id)
        return response_text
    