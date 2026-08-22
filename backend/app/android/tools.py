from __future__ import annotations

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

# Allowlist for android_open_app
ALLOWED_APPS = {
    "com.android.settings": "Settings",
    "com.google.android.calendar": "Google Calendar",
    "com.google.android.apps.messaging": "Messages",
    "com.android.chrome": "Chrome",
    "com.google.android.gm": "Gmail"
}

async def handle_android_send_sms(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    # SMS must show preview in confirmation, but Confirmation is handled by SafetyGate based on arguments
    # Ensure recipient and message exist
    recipient = arguments.get("phone_number")
    message = arguments.get("message")
    
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_send_sms", {
            "recipient": recipient,
            "message": message
        })
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_get_location(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_get_location", {})
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_get_device_status(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_get_device_status", {})
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_open_app(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    package_name = arguments.get("package_name")
    
    if package_name not in ALLOWED_APPS:
        return {"status": "error", "error": f"App '{package_name}' is not in the allowlist."}
        
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_open_app", {"package_name": package_name})
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_set_volume(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    level = arguments.get("level")
    
    if not isinstance(level, int) or level < 0 or level > 100:
        return {"status": "error", "error": "Volume level must be an integer between 0 and 100."}
        
    transport = get_transport()
    try:
        result = await transport.dispatch(ctx, target_device_id, "android_set_volume", {"level": level})
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

import re

def redact_notification(text: str) -> str:
    patterns = [
        r'(?i)\b(?:otp|verification|auth|security|passcode|code)[\w\s]{0,30}[:\-]?\s*\b((?=[a-z0-9]{4,8}\b)[a-z]*\d[a-z0-9]*)\b',
        r'(?i)\b(?:card|account|acct|ending in|ending with)[\w\s]{0,30}[:\-]?\s*\b(\d{3,5})\b'
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
                # Mark as untrusted external content
                n["_sensitivity"] = "UNTRUSTED_EXTERNAL_CONTENT"
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

ALLOWED_SETTINGS = {"wifi", "bluetooth", "do_not_disturb", "airplane_mode", "flashlight"}

async def handle_android_toggle_setting(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    setting_name = arguments.get("setting_name")
    enable = arguments.get("enable")
    
    if setting_name not in ALLOWED_SETTINGS:
        return {"status": "error", "error": f"Setting '{setting_name}' is not in the allowlist."}
        
    transport = get_transport()
    try:
        await transport.dispatch(ctx, target_device_id, "android_toggle_setting", {"setting_name": setting_name, "enable": enable})
        status = await transport.dispatch(ctx, target_device_id, "android_get_setting", {"setting_name": setting_name})
        if status.get(setting_name) == enable:
            return {"status": "success", "verified": True, "current_state": enable}
        else:
            return {"status": "error", "error": "Setting toggle verification failed."}
    except TransportError as e:
        return {"status": "error", "error": str(e)}

ALLOWED_INTENTS = {
    "VIEW_MAP": "android.intent.action.VIEW",
    "SET_ALARM": "android.intent.action.SET_ALARM"
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


ANDROID_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="android_send_sms",
        description="Sends an SMS message from the paired Android device.",
        risk_level=RiskLevel.HIGH,
        permission_category=PermissionCategory.ANDROID_SMS_SEND,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.MANUAL,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"},
                "phone_number": {"type": "string"},
                "message": {"type": "string"}
            },
            "required": ["target_device_id", "phone_number", "message"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_send_sms
    ),
    ToolDefinition(
        name="android_get_location",
        description="Gets the current GPS location from the paired Android device.",
        risk_level=RiskLevel.MEDIUM,
        permission_category=PermissionCategory.ANDROID_LOCATION_READ,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.NONE,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"}
            },
            "required": ["target_device_id"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_get_location
    ),
    ToolDefinition(
        name="android_get_device_status",
        description="Gets the current status (battery, network, etc) of the paired Android device.",
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.ANDROID_DEVICE_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.NONE,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"}
            },
            "required": ["target_device_id"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_get_device_status
    ),
    ToolDefinition(
        name="android_open_app",
        description="Opens a specific app on the paired Android device. Allowed packages: " + ", ".join(ALLOWED_APPS.keys()),
        risk_level=RiskLevel.MEDIUM,
        permission_category=PermissionCategory.ANDROID_DEVICE_CONTROL,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.MANUAL,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"},
                "package_name": {"type": "string"}
            },
            "required": ["target_device_id", "package_name"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_open_app
    ),
    ToolDefinition(
        name="android_set_volume",
        description="Sets the media volume on the paired Android device (0-100).",
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.ANDROID_DEVICE_CONTROL,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.MANUAL,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"},
                "level": {"type": "integer", "minimum": 0, "maximum": 100}
            },
            "required": ["target_device_id", "level"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_set_volume
    ),
    ToolDefinition(
        name="android_get_notifications",
        description="Reads notifications from the paired Android device.",
        risk_level=RiskLevel.MEDIUM,
        permission_category=PermissionCategory.ANDROID_NOTIFICATION_READ,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.NONE,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"}
            },
            "required": ["target_device_id"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_get_notifications
    ),
    ToolDefinition(
        name="android_toggle_setting",
        description="Toggles allowed settings on the device. Allowed: " + ", ".join(ALLOWED_SETTINGS),
        risk_level=RiskLevel.MEDIUM,
        permission_category=PermissionCategory.ANDROID_DEVICE_CONTROL,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.MANUAL,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"},
                "setting_name": {"type": "string"},
                "enable": {"type": "boolean"}
            },
            "required": ["target_device_id", "setting_name", "enable"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_toggle_setting
    ),
    ToolDefinition(
        name="android_launch_intent",
        description="Launches an approved intent on the device. Allowed: " + ", ".join(ALLOWED_INTENTS.keys()),
        risk_level=RiskLevel.MEDIUM,
        permission_category=PermissionCategory.ANDROID_DEVICE_CONTROL,
        confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.MANUAL,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"},
                "intent_name": {"type": "string"},
                "extras": {"type": "object"}
            },
            "required": ["target_device_id", "intent_name"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_launch_intent
    ),
    ToolDefinition(
        name="android_control_media",
        description="Controls media playback on the device.",
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.ANDROID_DEVICE_CONTROL,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.NONE,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"},
                "action": {"type": "string", "enum": ["play", "pause", "next", "previous"]}
            },
            "required": ["target_device_id", "action"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_control_media
    ),
    ToolDefinition(
        name="android_set_brightness",
        description="Sets the screen brightness (0-100).",
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.ANDROID_DEVICE_CONTROL,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.MANUAL,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"},
                "level": {"type": "integer", "minimum": 0, "maximum": 100}
            },
            "required": ["target_device_id", "level"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_set_brightness
    ),
    ToolDefinition(
        name="android_find_app",
        description="Checks if an app is installed by package name.",
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.ANDROID_DEVICE_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.NONE,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"},
                "package_name": {"type": "string"}
            },
            "required": ["target_device_id", "package_name"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_find_app
    ),
    ToolDefinition(
        name="android_get_battery",
        description="Reads the device battery level and state.",
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.ANDROID_DEVICE_READ,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=[DeviceType.ANDROID],
        verification_method=VerificationMethod.NONE,
        input_schema={
            "type": "object",
            "properties": {
                "target_device_id": {"type": "string"}
            },
            "required": ["target_device_id"],
            "additionalProperties": False
        },
        output_schema={"type": "object", "additionalProperties": True},
        handler=handle_android_get_battery
    )
]
