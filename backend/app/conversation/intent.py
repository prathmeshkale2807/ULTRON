import json
from pydantic import BaseModel, Field
from typing import Any
from app.conversation.schemas import IntentTypeEnum
from app.ai_providers.base import ProviderRequest, Message, Sensitivity

class IntentExtraction(BaseModel):
    intent_type: IntentTypeEnum = Field(..., description="The categorized intent of the user message.")
    confidence: str = Field(..., description="High, Medium, or Low")
    entities: dict[str, Any] = Field(default_factory=dict, description="Structured entities referenced, e.g., target_app, query")
    target_device: str | None = Field(None, description="The intended device, e.g., PC or Phone, if mentioned.")
    sensitivity: str = Field("normal", description="The data sensitivity level of the intent.")
    referenced_task_id: str | None = Field(None, description="ID of a task if the user is referring to an ongoing one.")
    requested_outcome: str | None = Field(None, description="A clear summary of what the user wants to achieve.")
    clarification_needed: str | None = Field(None, description="If confidence is Low/Medium, what specifically needs to be clarified?")

async def extract_intent(manager, current_message: str, recent_context: str, sensitivity: str = "INTERNAL") -> IntentExtraction:
    """Uses the provider manager to extract structured intent."""
    system_prompt = (
        "You are the intent resolution engine for ULTRON. Your job is to classify "
        "the user's most recent message into a structured intent based on the conversational context.\n"
        "Return ONLY a raw JSON object matching the IntentExtraction schema. Do not include markdown code blocks.\n"
        "Schema:\n" + IntentExtraction.schema_json()
    )
    
    prompt = f"Context:\n{recent_context}\n\nUser Message: {current_message}"
    
    request = ProviderRequest(
        messages=[Message(role="user", content=prompt)],
        system_prompt=system_prompt,
        sensitivity=Sensitivity[sensitivity],
        max_tokens=500
    )
    
    response = await manager.complete(request, use_tools=False)
    
    # Clean the response text in case the model added markdown
    text = response.text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
        
    try:
        data = json.loads(text.strip())
        return IntentExtraction(**data)
    except Exception as e:
        # Fallback to unknown
        return IntentExtraction(
            intent_type=IntentTypeEnum.UNKNOWN,
            confidence="Low",
            clarification_needed="Failed to parse intent: " + str(e)
        )

