"""
System information and window management functions.
"""
import platform
import psutil
import ctypes
from typing import Any

def get_system_info() -> dict[str, Any]:
    """Returns safe system information."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        
        info = {
            "success": True,
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "cpu_percent": cpu_percent,
            "ram_total_gb": round(ram.total / (1024**3), 2),
            "ram_percent": ram.percent,
        }

        if hasattr(psutil, "sensors_battery"):
            battery = psutil.sensors_battery()
            if battery:
                info["battery_percent"] = battery.percent
                info["power_plugged"] = battery.power_plugged

        return info
    except Exception:
        return {"success": False, "error": "Failed to retrieve system information."}

def get_active_window() -> dict[str, Any]:
    """Returns the title of the currently active (foreground) window."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return {"success": False, "error": "No foreground window found."}
            
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return {"success": True, "title": ""}
            
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        
        return {"success": True, "title": buff.value}
    except Exception:
        return {"success": False, "error": "Failed to retrieve active window title."}
