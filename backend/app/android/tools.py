from __future__ import annotations

import json
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

async def handle_android_send_sms(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    # Phase 11 constraint: Do not fake success.
    # Must return PENDING or NOT_CONNECTED, since the real app isn't built yet.
    return {
        "status": "pending",
        "detail": "Android action queued. Not verified."
    }

async def handle_android_get_location(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    # Phase 11 constraint: Do not fake success.
    return {
        "status": "not_implemented",
        "detail": "Android companion cannot return live data yet."
    }

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
        output_schema={
            "type": "object",
            "additionalProperties": True
        },
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
        output_schema={
            "type": "object",
            "additionalProperties": True
        },
        handler=handle_android_get_location
    )
]
