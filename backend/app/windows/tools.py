"""
Windows Tool definitions and handlers.
"""

from typing import Any
import os

from app.tools.models import (
    ExecutionContext,
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
from app.windows.automation import generate_snapshot, click_control, select_control, focus_window, AutomationError, StaleTargetError, SecurityError
from app.windows.system import get_system_info, get_active_window
from app.windows.screenshot import take_screenshot

# ==============================================================================
# Handlers and Verifiers
# ==============================================================================

async def handle_open_application(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return open_application(arguments["app_name"])

async def verify_open_application(ctx: ExecutionContext, arguments: dict[str, Any], result: dict[str, Any]) -> bool:
    if not result.get("success"):
        return False
    
    pid = result.get("pid")
    if not pid:
        return False
        
    # Check if the specific process ID we just spawned is running
    import psutil
    try:
        proc = psutil.Process(pid)
        if proc.is_running():
            return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
        
    return False

async def handle_close_application(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    app_name = arguments.get("app_name")
    pid = arguments.get("pid")
    return close_application(app_name, pid)

async def verify_close_application(ctx: ExecutionContext, arguments: dict[str, Any], result: dict[str, Any]) -> bool:
    if not result.get("success"):
        return False
    app_name = arguments.get("app_name")
    pid = arguments.get("pid")
    if not app_name:
         return False
         
    from app.windows.safety import get_allowed_executable
    executable = get_allowed_executable(app_name)
    if not executable:
        return False
        
    import psutil
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            if proc.is_running() and proc.name().lower() == executable.lower():
                return False # specific targeted instance is still running
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        return True
    
    # If no pid provided, verify all instances are closed
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == executable.lower():
                return False # Still running!
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return True

async def handle_list_running_applications(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return list_running_applications()

async def handle_get_system_info(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return get_system_info()

async def handle_take_screenshot(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return take_screenshot()

async def verify_take_screenshot(ctx: ExecutionContext, arguments: dict[str, Any], result: dict[str, Any]) -> bool:
    if not result.get("success"):
        return False
    if "image_base64_secret" in result and len(result["image_base64_secret"]) > 0:
        return True
    return False

async def handle_get_active_window(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
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
    description="Closes an allowed Windows application gracefully. Prefer providing a specific 'pid' to target a single instance. If only 'app_name' is provided, all running instances of the app will be closed.",
    input_schema={
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "The name of the application."
            },
            "pid": {
                "type": "integer",
                "description": "Optional. The specific process ID to close. Highly recommended."
            }
        },
        "required": ["app_name"]
    },
    output_schema={"type": "object", "additionalProperties": True},
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


async def handle_windows_get_ui_tree(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return generate_snapshot()

async def handle_windows_click_control(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        click_control(
            arguments["snapshot_id"], 
            arguments["control_id"], 
            arguments["expected_app"], 
            arguments["expected_window"]
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def handle_windows_select_control(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        select_control(
            arguments["snapshot_id"], 
            arguments["control_id"], 
            arguments["expected_app"], 
            arguments["expected_window"]
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def handle_windows_focus_window(ctx: ExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        focus_window(arguments["application_name"], arguments["window_title"])
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

tool_get_ui_tree = ToolDefinition(
    name="windows_get_ui_tree",
    description="Extracts the active window's UI hierarchy.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object"},
    risk_level=RiskLevel.LOW,
    permission_category=PermissionCategory.PC_READ,
    confirmation_tier=ConfirmationTier.AUTOMATIC,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_windows_get_ui_tree,
)

tool_click_control = ToolDefinition(
    name="windows_click_control",
    description="Clicks a semantic UI target.",
    input_schema={
        "type": "object",
        "properties": {
            "snapshot_id": {"type": "string"},
            "control_id": {"type": "string"},
            "expected_app": {"type": "string"},
            "expected_window": {"type": "string"}
        },
        "required": ["snapshot_id", "control_id", "expected_app", "expected_window"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.HIGH,
    permission_category=PermissionCategory.PC_INPUT_CONTROL,
    confirmation_tier=ConfirmationTier.ALWAYS_ASK,
    verification_method=VerificationMethod.MANUAL,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_windows_click_control,
)

tool_select_control = ToolDefinition(
    name="windows_select_control",
    description="Selects a semantic UI target.",
    input_schema={
        "type": "object",
        "properties": {
            "snapshot_id": {"type": "string"},
            "control_id": {"type": "string"},
            "expected_app": {"type": "string"},
            "expected_window": {"type": "string"}
        },
        "required": ["snapshot_id", "control_id", "expected_app", "expected_window"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.HIGH,
    permission_category=PermissionCategory.PC_INPUT_CONTROL,
    confirmation_tier=ConfirmationTier.ALWAYS_ASK,
    verification_method=VerificationMethod.MANUAL,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_windows_select_control,
)

tool_focus_window = ToolDefinition(
    name="windows_focus_window",
    description="Brings a known window into the foreground.",
    input_schema={
        "type": "object",
        "properties": {
            "application_name": {"type": "string"},
            "window_title": {"type": "string"}
        },
        "required": ["application_name", "window_title"]
    },
    output_schema={"type": "object"},
    risk_level=RiskLevel.MEDIUM,
    permission_category=PermissionCategory.PC_PROCESS_CONTROL,
    confirmation_tier=ConfirmationTier.ASK_ONCE_PER_SESSION,
    verification_method=VerificationMethod.NONE,
    allowed_devices=[DeviceType.PC],
    retry_policy=RetryPolicy(max_attempts=1),
    handler=handle_windows_focus_window,
)

def register_windows_tools(registry: ToolRegistry) -> None:
    registry.register(tool_open_application, replace=True)
    registry.register(tool_close_application, replace=True)
    registry.register(tool_list_running_applications, replace=True)
    registry.register(tool_get_system_info, replace=True)
    registry.register(tool_take_screenshot, replace=True)
    registry.register(tool_get_active_window, replace=True)
    registry.register(tool_get_ui_tree, replace=True)
    registry.register(tool_click_control, replace=True)
    registry.register(tool_select_control, replace=True)
    registry.register(tool_focus_window, replace=True)

