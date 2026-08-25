import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def secure_directory_windows(target_dir: Path) -> None:
    """
    Enforces strict Windows ACLs on a directory so that only the current user,
    SYSTEM, and Administrators have access. Disables inheritance to prevent
    broader access.
    """
    if os.name != 'nt':
        return

    try:
        username = os.environ.get("USERNAME")
        if not username:
            logger.warning("USERNAME env var missing, cannot secure directory ACLs.")
            return

        # /inheritance:r removes all inherited ACEs
        # /grant USER:(OI)(CI)F grants full control to user, object inherit, container inherit
        
        target_str = str(target_dir.resolve())
        
        # Grant Administrators and SYSTEM full control just in case
        cmds = [
            ["icacls", target_str, "/inheritance:r"],
            ["icacls", target_str, "/grant", f"{username}:(OI)(CI)F"],
            ["icacls", target_str, "/grant", "SYSTEM:(OI)(CI)F"],
            ["icacls", target_str, "/grant", "Administrators:(OI)(CI)F"]
        ]
        
        for cmd in cmds:
            subprocess.run(
                cmd, 
                check=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
        logger.info(f"Secured Windows ACLs for {target_str}")
        
    except Exception as e:
        logger.warning(f"Failed to set strict ACLs on {target_dir}: {e}")
