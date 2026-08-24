from app.ai_providers.base import ProviderRequest, Message, Sensitivity, ContentPart

async def generate_response(manager, state_context: str, execution_results: str, sensitivity: str = "INTERNAL", visual_context: list[ContentPart] | None = None) -> str:
    """Generates a natural, concise, conversational response."""
    system_prompt = (
        "You are ULTRON, a concise, confident, and natural AI assistant. "
        "Based on the conversation state and the latest execution results, provide a brief response to the user.\n"
        "Rules:\n"
        "- Do not use robotic phrases like 'EXECUTION_STATUS = SUCCESS'.\n"
        "- If a task succeeded, be brief (e.g. 'Done - Notepad is open.').\n"
        "- If a task requires confirmation, explain why gracefully.\n"
        "- Do not invent unverified results.\n"
        "- Be concise."
    )
    
    prompt_text = f"State Context:\n{state_context}\n\nExecution/Task Results:\n{execution_results}"
    
    if visual_context:
        content = [ContentPart(type="text", text=prompt_text)] + visual_context
        msg = Message(role="user", content=content)
    else:
        msg = Message(role="user", content=prompt_text)
    
    request = ProviderRequest(
        messages=[msg],
        system_prompt=system_prompt,
        sensitivity=Sensitivity[sensitivity], 
        max_tokens=200
    )
    
    response = await manager.complete(request, use_tools=False)
    return response.text.strip()
