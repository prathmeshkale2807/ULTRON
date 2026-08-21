"""
Windows Tool definitions and handlers.
"""

from typing import Any
import os

from app.tools.models import (
    ToolDefinition,
    RiskLevel,
    PermissionCategory,
    ConfirmationTier,
    VerificationMethod,
    DeviceType,
    RetryPolicy,
)
from app.tools.registry import ToolRegistry
from app.windows.applications import open_application, close_application, list_running_applications
from app.windows.system import get_system_info, get_active_window
from app.windows.screenshot import take_screenshot

# ==============================================================================
# Handlers and Verifiers
# ==============================================================================

async def handle_open_application(arguments: dict[str, Any]) -> dict[str, Any]:
    return open_application(arguments["app_name"])

async def verify_open_application(arguments: dict[str, Any], result: dict[str, Any]) -> bool:
    if not result.get("success"):
        return False
    app_name = arguments.get("app_name")
    if not app_name:
        return False
        
    from app.windows.safety import get_allowed_executable
    executable = get_allowed_executable(app_name)
    if not executable:
        return False
        
    # Check if a process matching the executable is running
    import psutil
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == executable.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

async def handle_close_application(arguments: dict[str, Any]) -> dict[str, Any]:
    return close_application(arguments["app_name"])

async def verify_close_application(arguments: dict[str, Any], result: dict[str, Any]) -> bool:
    if not result.get("success"):
        return False
    app_name = arguments.get("app_name")
    if not app_name:
         return False
         
    from app.windows.safety import get_allowed_executable
    executable = get_allowed_executable(app_name)
    if not executable:
        return False
        
    import psutil
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == executable.lower():
                return False # Still running!
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return True

async def handle_list_running_applications(arguments: dict[str, Any]) -> dict[str, Any]:
    return list_running_applications()

async def handle_get_system_info(arguments: dict[str, Any]) -> dict[str, Any]:
    return get_system_info()

async def handle_take_screenshot(arguments: dict[str, Any]) -> dict[str, Any]:
    return take_screenshot()

async def verify_take_screenshot(arguments: dict[str, Any], result: dict[str, Any]) -> bool:
    if not result.get("success"):
        return False
    filepath = result.get("filepath")
    if filepath and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return True
    return False

async def handle_get_active_window(arguments: dict[str, Any]) -> dict[str, Any]:
    return get_active_window()

# ==============================================================================
# Tool Definitions
# ==============================================================================

tool_open_application = ToolDefinition(
    name="windows_open_application",
    description="Opens an allowed Windows application by name.",
    input_schema={
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "The name of the application to open (e.g., 'notepad', 'calculator')."
            }
        },
        "required": ["app_name"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.MEDIUM,
    permission_category=PermissionCategory.PC_PROCESS_CONTROL,
    confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
    verification_method=VerificationMethod.CALLBACK,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_open_application,
    verifier=verify_open_application,
)

tool_close_application = ToolDefinition(
    name="windows_close_application",
    description="Closes all instances of an allowed Windows application.",
    input_schema={
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "The name of the application to close."
            }
        },
        "required": ["app_name"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.HIGH,
    permission_category=PermissionCategory.PC_PROCESS_CONTROL,
    confirmation_tier=ConfirmationTier.ALWAYS_ASK,
    verification_method=VerificationMethod.CALLBACK,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_close_application,
    verifier=verify_close_application,
)

tool_list_running_applications = ToolDefinition(
    name="windows_list_running_applications",
    description="Lists safe running applications and their PIDs.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
    risk_level=RiskLevel.LOW,
    permission_category=PermissionCategory.PC_READ,
    confirmation_tier=ConfirmationTier.AUTOMATIC,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_list_running_applications,
)

tool_get_system_info = ToolDefinition(
    name="windows_get_system_info",
    description="Returns system information such as CPU, RAM, OS, and battery.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
    risk_level=RiskLevel.LOW,
    permission_category=PermissionCategory.PC_READ,
    confirmation_tier=ConfirmationTier.AUTOMATIC,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_get_system_info,
)

tool_take_screenshot = ToolDefinition(
    name="windows_take_screenshot",
    description="Captures the current screen. Treats screenshots as sensitive.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
    risk_level=RiskLevel.HIGH,
    permission_category=PermissionCategory.PC_SCREEN_CAPTURE,
    confirmation_tier=ConfirmationTier.ALWAYS_ASK,
    verification_method=VerificationMethod.CALLBACK,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_take_screenshot,
    verifier=verify_take_screenshot,
)

tool_get_active_window = ToolDefinition(
    name="windows_get_active_window",
    description="Returns the title of the currently active (foreground) window.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
    risk_level=RiskLevel.LOW,
    permission_category=PermissionCategory.PC_READ,
    confirmation_tier=ConfirmationTier.AUTOMATIC,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_get_active_window,
)

# ==============================================================================
# Registration
# ==============================================================================

def register_windows_tools(registry: ToolRegistry) -> None:
    registry.register(tool_open_application, replace=True)
    registry.register(tool_close_application, replace=True)
    registry.register(tool_list_running_applications, replace=True)
    registry.register(tool_get_system_info, replace=True)
    registry.register(tool_take_screenshot, replace=True)
    registry.register(tool_get_active_window, replace=True)
