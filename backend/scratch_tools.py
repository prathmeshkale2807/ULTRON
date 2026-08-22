import re
from typing import Any
from app.tools.models import (
    ConfirmationTier,
    DeviceType,
    PermissionCategory,
    RiskLevel,
    ToolDefinition,
    VerificationMethod,
    ExecutionContext
)
from app.android.transport import get_transport, TransportError

# Notification Redaction
def redact_notification(text: str) -> str:
    patterns = [
        # Context-aware OTP/auth codes
        r'(?i)\b(?:otp|verification|auth|security|passcode|code)[\s\w]{0,20}?[:\-]?\s*\b([0-9A-Z]{4,8})\b',
        # Account/Card fragments
        r'(?i)\b(?:card|account|acct|ending in|ending with)[\s\w]{0,10}?[:\-]?\s*\b(\d{3,5})\b'
    ]
    redacted = text
    for pattern in patterns:
        def replacer(match):
            return match.group(0).replace(match.group(1), "[REDACTED]")
        redacted = re.sub(pattern, replacer, redacted)
    return redacted

async def handle_android_get_notifications(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_get_notifications", {})
        if "notifications" in result:
            for n in result["notifications"]:
                if "text" in n:
                    n["text"] = redact_notification(n["text"])
                if "title" in n:
                    n["title"] = redact_notification(n["title"])
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

ALLOWED_SETTINGS = {
    "wifi", "bluetooth", "do_not_disturb", "airplane_mode", "flashlight"
}

async def handle_android_toggle_setting(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    setting_name = arguments.get("setting_name")
    enable = arguments.get("enable")
    
    if setting_name not in ALLOWED_SETTINGS:
        return {"status": "error", "error": f"Setting '{setting_name}' is not in the allowlist."}
        
    transport = get_transport()
    try:
        await transport.dispatch(ctx, target_device_id, "android_toggle_setting", {"setting_name": setting_name, "enable": enable})
        # Verification Read-back
        status = await transport.dispatch(ctx, target_device_id, "android_get_setting", {"setting_name": setting_name})
        if status.get(setting_name) == enable:
            return {"status": "success", "verified": True, "current_state": enable}
        else:
            return {"status": "error", "error": "Setting toggle verification failed."}
    except TransportError as e:
        return {"status": "error", "error": str(e)}

ALLOWED_INTENTS = {
    "VIEW_MAP": "android.intent.action.VIEW",
    "SET_ALARM": "android.intent.action.SET_ALARM",
    "DIAL_EMERGENCY": "android.intent.action.DIAL"  # Just examples
}

async def handle_android_launch_intent(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    intent_name = arguments.get("intent_name")
    extras = arguments.get("extras", {})
    
    if intent_name not in ALLOWED_INTENTS:
        return {"status": "error", "error": f"Intent '{intent_name}' is not in the allowlist."}
        
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_launch_intent", {
            "action": ALLOWED_INTENTS[intent_name],
            "extras": extras
        })
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_control_media(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    action = arguments.get("action")
    
    if action not in ["play", "pause", "next", "previous"]:
        return {"status": "error", "error": "Invalid media action."}
        
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_control_media", {"action": action})
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_set_brightness(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    level = arguments.get("level")
    
    if not isinstance(level, int) or level < 0 or level > 100:
        return {"status": "error", "error": "Brightness level must be between 0 and 100."}
        
    transport = get_transport()
    try:
        await transport.dispatch(ctx, target_device_id, "android_set_brightness", {"level": level})
        # Verification Read-back
        status = await transport.dispatch(ctx, target_device_id, "android_get_brightness", {})
        if status.get("level") == level:
            return {"status": "success", "verified": True, "level": level}
        else:
            return {"status": "error", "error": "Brightness verification failed."}
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_find_app(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    package_name = arguments.get("package_name")
    
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_find_app", {"package_name": package_name})
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_get_battery(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_get_battery", {})
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

# Re-export tools logic
