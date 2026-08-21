import json
import logging
from typing import Any

from app.tools.registry import ToolRegistry
from app.tools.models import (
    ToolDefinition, 
    PermissionCategory, 
    ConfirmationTier, 
    RiskLevel, 
    DeviceType, 
    VerificationMethod,
    RetryPolicy
)
from app.browser.manager import get_browser_manager
from app.browser.safety import wrap_untrusted_content, check_sensitive_field

logger = logging.getLogger(__name__)

async def browser_open_handler(args: dict[str, Any], context: dict[str, Any] = None) -> dict[str, Any]:
    """Open or get the isolated browser context for this session."""
    context = context or {}
    session_id = context.get("session_id")
    if not session_id:
        return {"error": "No session_id provided."}
    
    manager = get_browser_manager()
    context_obj = await manager.get_or_create_context(session_id)
    page = await manager.get_active_page(session_id)
    if not page:
        page = await context_obj.new_page()
    
    return {"status": "success", "message": "Browser session active."}

async def browser_navigate_handler(args: dict[str, Any], context: dict[str, Any] = None) -> dict[str, Any]:
    context = context or {}
    session_id = context.get("session_id")
    url = args.get("url")
    if not session_id or not url:
        return {"error": "Missing session_id or url."}
    
    manager = get_browser_manager()
    page = await manager.get_active_page(session_id)
    if not page:
        context_obj = await manager.get_or_create_context(session_id)
        page = await context_obj.new_page()
        
    response = await page.goto(url, wait_until="domcontentloaded")
    
    if not response:
        return {"error": "Failed to navigate. No response."}
        
    return {
        "status": "success",
        "url": page.url,
        "status_code": response.status
    }

async def browser_get_page_handler(args: dict[str, Any], context: dict[str, Any] = None) -> dict[str, Any]:
    context = context or {}
    session_id = context.get("session_id")
    if not session_id:
        return {"error": "No session_id provided."}
        
    manager = get_browser_manager()
    page = await manager.get_active_page(session_id)
    if not page:
        return {"error": "No active browser page."}
        
    title = await page.title()
    return {
        "url": page.url,
        "title": wrap_untrusted_content(title),
        "is_untrusted_data": True
    }

async def browser_extract_text_handler(args: dict[str, Any], context: dict[str, Any] = None) -> dict[str, Any]:
    context = context or {}
    session_id = context.get("session_id")
    selector = args.get("selector", "body")
    if not session_id:
        return {"error": "No session_id provided."}
        
    manager = get_browser_manager()
    page = await manager.get_active_page(session_id)
    if not page:
        return {"error": "No active browser page."}
        
    try:
        element = await page.wait_for_selector(selector, state="visible", timeout=3000)
        if not element:
            return {"error": f"Selector '{selector}' not found or not visible."}
        
        text = await element.inner_text()
        return {
            "content": wrap_untrusted_content(text),
            "is_untrusted_data": True
        }
    except Exception as e:
        return {"error": f"Failed to extract: {str(e)}"}

async def browser_click_handler(args: dict[str, Any], context: dict[str, Any] = None) -> dict[str, Any]:
    context = context or {}
    session_id = context.get("session_id")
    selector = args.get("selector")
    if not session_id or not selector:
        return {"error": "Missing session_id or selector."}
        
    manager = get_browser_manager()
    page = await manager.get_active_page(session_id)
    if not page:
        return {"error": "No active browser page."}
        
    try:
        await page.click(selector, timeout=3000)
        return {"status": "success", "message": f"Clicked {selector}."}
    except Exception as e:
        return {"error": f"Failed to click: {str(e)}"}

async def browser_type_handler(args: dict[str, Any], context: dict[str, Any] = None) -> dict[str, Any]:
    context = context or {}
    session_id = context.get("session_id")
    selector = args.get("selector")
    text = args.get("text")
    if not session_id or not selector or text is None:
        return {"error": "Missing session_id, selector, or text."}
        
    manager = get_browser_manager()
    page = await manager.get_active_page(session_id)
    if not page:
        return {"error": "No active browser page."}
        
    try:
        element = await page.wait_for_selector(selector, state="attached", timeout=3000)
        if not element:
            return {"error": f"Selector '{selector}' not found."}
            
        js_handle = await element.evaluate_handle("el => el")
        properties = await js_handle.get_properties()
        attrs = {}
        if "type" in properties:
            attrs["type"] = await properties["type"].json_value()
        if "name" in properties:
            attrs["name"] = await properties["name"].json_value()
        if "id" in properties:
            attrs["id"] = await properties["id"].json_value()
        if "nodeName" in properties:
            attrs["nodeName"] = await properties["nodeName"].json_value()
            
        is_sensitive = check_sensitive_field(attrs)
        
        await page.fill(selector, text, timeout=3000)
        
        reported_text = "***REDACTED***" if is_sensitive else text
        return {"status": "success", "message": f"Typed '{reported_text}' into {selector}."}
    except Exception as e:
        return {"error": f"Failed to type: {str(e)}"}

async def browser_screenshot_handler(args: dict[str, Any], context: dict[str, Any] = None) -> dict[str, Any]:
    context = context or {}
    session_id = context.get("session_id")
    if not session_id:
        return {"error": "No session_id provided."}
        
    manager = get_browser_manager()
    page = await manager.get_active_page(session_id)
    if not page:
        return {"error": "No active browser page."}
        
    try:
        import tempfile
        import os
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"browser_screenshot_{session_id}_{timestamp}.png")
        
        await page.screenshot(path=file_path)
        
        return {
            "status": "success",
            "message": f"Screenshot captured at {file_path}",
            "file_path": file_path
        }
    except Exception as e:
        return {"error": f"Failed to capture screenshot: {str(e)}"}

tool_browser_open = ToolDefinition(
    name="browser_open",
    description="Open a browser session.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
    risk_level=RiskLevel.LOW,
    permission_category=PermissionCategory.BROWSER_NAVIGATE,
    confirmation_tier=ConfirmationTier.AUTOMATIC,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.BROWSER],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=browser_open_handler
)

tool_browser_navigate = ToolDefinition(
    name="browser_navigate",
    description="Navigate to a URL.",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to"}
        },
        "required": ["url"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.MEDIUM,
    permission_category=PermissionCategory.BROWSER_NAVIGATE,
    confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.BROWSER],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=browser_navigate_handler
)

tool_browser_get_page = ToolDefinition(
    name="browser_get_page",
    description="Get page title and URL.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
    risk_level=RiskLevel.LOW,
    permission_category=PermissionCategory.BROWSER_READ,
    confirmation_tier=ConfirmationTier.AUTOMATIC,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.BROWSER],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=browser_get_page_handler
)

tool_browser_extract_text = ToolDefinition(
    name="browser_extract_text",
    description="Extract text from a CSS selector on the page.",
    input_schema={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector to extract"}
        },
        "required": ["selector"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.LOW,
    permission_category=PermissionCategory.BROWSER_READ,
    confirmation_tier=ConfirmationTier.AUTOMATIC,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.BROWSER],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=browser_extract_text_handler
)

tool_browser_click = ToolDefinition(
    name="browser_click",
    description="Click an element on the page.",
    input_schema={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector to click"}
        },
        "required": ["selector"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.MEDIUM,
    permission_category=PermissionCategory.BROWSER_INTERACT,
    confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.BROWSER],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=browser_click_handler
)

tool_browser_type = ToolDefinition(
    name="browser_type",
    description="Type text into an element on the page.",
    input_schema={
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector of the input field"},
            "text": {"type": "string", "description": "Text to type"}
        },
        "required": ["selector", "text"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.HIGH,
    permission_category=PermissionCategory.BROWSER_SENSITIVE_INPUT,
    confirmation_tier=ConfirmationTier.ALWAYS_ASK,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.BROWSER],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=browser_type_handler
)

tool_browser_screenshot = ToolDefinition(
    name="browser_screenshot",
    description="Capture a screenshot of the browser viewport.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
    risk_level=RiskLevel.MEDIUM,
    permission_category=PermissionCategory.BROWSER_SCREENSHOT,
    confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.BROWSER],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=browser_screenshot_handler
)

def register_browser_tools(registry: ToolRegistry) -> None:
    registry.register(tool_browser_open, replace=True)
    registry.register(tool_browser_navigate, replace=True)
    registry.register(tool_browser_get_page, replace=True)
    registry.register(tool_browser_extract_text, replace=True)
    registry.register(tool_browser_click, replace=True)
    registry.register(tool_browser_type, replace=True)
    registry.register(tool_browser_screenshot, replace=True)
