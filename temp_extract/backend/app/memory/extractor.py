from typing import List, Optional
import json

from app.memory.models import MemoryCreate, MemoryType, MemorySensitivity, MemorySource
from app.memory.store import MemoryStore
from app.browser.safety import check_sensitive_field
from app.ai_providers.manager import ProviderManager
from app.core.logging_config import get_logger

logger = get_logger("memory.extractor")

def is_secret(text: str) -> bool:
    # A lightweight heuristic to avoid storing API keys or passwords.
    # In real systems this would use yara rules, regex, etc.
    # We reuse the concept from Phase 8.
    lower_text = text.lower()
    suspicious = ["password", "api_key", "secret", "token", "cvv", "otp", "auth"]
    for s in suspicious:
        if s in lower_text:
            # simple mock detection
            return True
    return False

async def extract_memory_from_turn(
    provider_manager: ProviderManager,
    user_text: str,
    ai_response: str,
    principal_id: str,
    store: MemoryStore,
    session_id: str
) -> None:
    """
    Extracts durable memories from the conversational turn if appropriate.
    External webpage content must NOT auto-promote itself to memory here
    if passed in via user_text without explicit user instruction.
    """
    
    # Do not extract if it looks like untrusted external content
    if "UNTRUSTED_EXTERNAL_CONTENT" in user_text:
        return
        
    if is_secret(user_text):
        return

    prompt = f"""
    You are a memory extraction engine. Analyze the following conversation turn.
    Decide if there is a durable personal fact, preference, or task context to store.
    If the user explicitly asked to remember or forget something, handle it.
    
    User: {user_text}
    AI: {ai_response}
    
    Return a JSON array of memories to store. Each object should have:
    - action: "STORE", "DELETE"
    - content: string
    - memory_type: "FACT", "PREFERENCE", "PROFILE", "HABIT", "PROJECT_CONTEXT", "TASK_CONTEXT", "RELATIONSHIP_CONTEXT", "INSTRUCTION"
    - sensitivity: "PUBLIC", "INTERNAL", "SENSITIVE", "PRIVATE"
    - confidence: float 0.0 - 1.0 (1.0 for explicit user statements, lower for inference)
    
    If nothing to store, return an empty array [].
    """
    
    try:
        response = await provider_manager.generate(
            prompt=prompt,
            system_prompt="You extract structured JSON arrays of memory operations.",
            sensitivity="INTERNAL"
        )
        
        # parse json
        try:
            # find first [ and last ]
            start = response.find("[")
            end = response.rfind("]")
            if start != -1 and end != -1:
                json_str = response[start:end+1]
                data = json.loads(json_str)
                for item in data:
                    action = item.get("action")
                    if action == "STORE":
                        content = item.get("content")
                        if not content or is_secret(content):
                            continue
                            
                        memory_type = item.get("memory_type", "FACT")
                        try:
                            mtype = MemoryType(memory_type)
                        except:
                            mtype = MemoryType.FACT
                            
                        store.create(MemoryCreate(
                            memory_type=mtype,
                            content=content,
                            importance=1.0,
                            confidence=item.get("confidence", 0.5),
                            sensitivity=MemorySensitivity(item.get("sensitivity", "INTERNAL")),
                            source_type=MemorySource.CONVERSATION_INFERENCE,
                            session_id=session_id
                        ))
        except json.JSONDecodeError:
            pass
            
    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")
