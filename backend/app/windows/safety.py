"""
Safety constraints for Windows control.
"""

from typing import Optional

# Exact-match dictionary of allowed applications.
# Keys are the names exposed to the AI tool.
# Values are the safe executable names or paths to run.
APPLICATION_ALLOWLIST: dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "msedge": "msedge.exe",
    "edge": "msedge.exe",
}

def get_allowed_executable(app_name: str) -> Optional[str]:
    """Returns the executable name if the app is allowed, else None."""
    return APPLICATION_ALLOWLIST.get(app_name.lower().strip())
