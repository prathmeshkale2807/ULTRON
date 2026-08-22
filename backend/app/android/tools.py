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
        result = await transport.dispatch(target_device_id, "android_send_sms", {
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
        result = await transport.dispatch(target_device_id, "android_get_location", {})
        return result
    except TransportError as e:
        return {"status": "error", "error": str(e)}

async def handle_android_get_device_status(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target_device_id = arguments.get("target_device_id")
    transport = get_transport()
    try:
        result = await transport.dispatch(target_device_id, "android_get_device_status", {})
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
        result = await transport.dispatch(target_device_id, "android_open_app", {"package_name": package_name})
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
        result = await transport.dispatch(target_device_id, "android_set_volume", {"level": level})
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
    )
]
