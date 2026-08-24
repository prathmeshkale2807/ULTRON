import json
from pydantic import BaseModel, Field
from typing import Any
from app.conversation.intent import IntentExtraction
from app.ai_providers.base import ProviderRequest, Message, Sensitivity

from app.ai_providers.base import ProviderRequest, Message, Sensitivity, ContentPart

class StepDefinition(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    target_device: str = "pc"

class PlanDefinition(BaseModel):
    objective: str
    steps: list[StepDefinition]
    expected_verification: str | None = None

async def create_plan(manager, intent: IntentExtraction, available_tools_schema: str, sensitivity: str = "INTERNAL", current_message: str | list[ContentPart] | None = None) -> PlanDefinition | None:
    if intent.intent_type not in ["TOOL_ACTION", "MULTI_STEP_TASK"]:
        return None
        
    system_prompt = (
        "You are the Planning Engine. Convert the user's requested outcome into a sequence of tool calls.\n"
        "Return ONLY a raw JSON object matching the PlanDefinition schema. Do not include markdown code blocks.\n"
        "Schema:\n" + PlanDefinition.schema_json() + "\n\n"
        "Available Tools:\n" + available_tools_schema
    )
    
    if isinstance(current_message, list):
        parts = [ContentPart(type="text", text=f"Objective: {intent.requested_outcome}\nEntities: {intent.entities}\nUser Message: ")]
        parts.extend(current_message)
        messages = [Message(role="user", content=parts)]
    else:
        prompt = f"Objective: {intent.requested_outcome}\nEntities: {intent.entities}"
        if current_message:
            prompt += f"\nUser Message: {current_message}"
        messages = [Message(role="user", content=prompt)]
    
    request = ProviderRequest(
        messages=messages,
        system_prompt=system_prompt,
        sensitivity=Sensitivity[sensitivity], 
        max_tokens=800
    )
    
    response = await manager.complete(request, use_tools=False)
    
    text = response.text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
        
    try:
        data = json.loads(text.strip())
        return PlanDefinition(**data)
    except Exception as e:
        raise ValueError(f"Failed to generate valid plan: {e}")

