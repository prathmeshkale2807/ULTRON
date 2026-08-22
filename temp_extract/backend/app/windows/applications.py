"""
Application management functions.
"""
import subprocess
import psutil
from typing import Any

from app.windows.safety import get_allowed_executable


def open_application(app_name: str) -> dict[str, Any]:
    """Opens an allowed application."""
    executable = get_allowed_executable(app_name)
    if not executable:
        return {"success": False, "error": f"Application '{app_name}' is not in the allowlist."}

    try:
        # shell=False prevents shell injection. 
        # Using subprocess.Popen allows it to run detached.
        process = subprocess.Popen([executable], shell=False)
        return {
            "success": True,
            "pid": process.pid,
            "message": f"Started {executable} (PID: {process.pid})"
        }
    except FileNotFoundError:
        return {"success": False, "error": f"Executable '{executable}' not found on PATH."}
    except PermissionError:
        return {"success": False, "error": "Access denied when attempting to launch application."}
    except Exception:
        return {"success": False, "error": "An unexpected error occurred while launching the application."}


def close_application(app_name: str, target_pid: int | None = None) -> dict[str, Any]:
    """Closes instances of an allowed application gracefully. Targets a specific PID if provided."""
    executable = get_allowed_executable(app_name)
    if not executable:
        return {"success": False, "error": f"Application '{app_name}' is not in the allowlist."}

    closed_count = 0
    errors = []

    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == executable.lower():
                if target_pid is not None and proc.info['pid'] != target_pid:
                    continue
                proc.terminate() # Graceful termination
                closed_count += 1
                if target_pid is not None:
                    break # Stop if we found the exact pid
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            errors.append("Access denied or process already terminated.")
        except Exception:
            errors.append("Unexpected error terminating process.")

    if closed_count > 0:
        target_msg = f" (PID {target_pid})" if target_pid else " instances"
        return {"success": True, "message": f"Closed {closed_count}{target_msg} of {executable}."}
    
    if errors:
        return {"success": False, "error": "Failed to close application instances. Ensure permissions are sufficient."}
        
    return {"success": False, "error": f"No running instances of '{executable}' found to close."}


def list_running_applications() -> dict[str, Any]:
    """Lists running processes. Filters out empty names to reduce noise."""
    processes = []
    
    # We only expose basic info to avoid leaking sensitive command line args by default
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name']:
                processes.append({
                    "pid": proc.info['pid'],
                    "name": proc.info['name']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    # Sort by name
    processes.sort(key=lambda x: x["name"].lower())
    
    return {
        "success": True,
        "processes": processes,
        "count": len(processes)
    }
