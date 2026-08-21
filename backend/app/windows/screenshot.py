"""
Screenshot functionality.
"""
from PIL import ImageGrab
import tempfile
import os
import time
from typing import Any

def take_screenshot() -> dict[str, Any]:
    """Captures the current screen and saves to a temporary file."""
    try:
        # all_screens=True captures all monitors if applicable.
        img = ImageGrab.grab(all_screens=True)
        if not img or img.width == 0 or img.height == 0:
             return {"success": False, "error": "Failed to capture screen, image dimensions are invalid."}
        
        # Save to a temporary file
        temp_dir = tempfile.gettempdir()
        filename = f"ultron_screenshot_{int(time.time())}.png"
        filepath = os.path.join(temp_dir, filename)
        
        img.save(filepath, "PNG")
        
        return {
            "success": True,
            "filepath": filepath,
            "width": img.width,
            "height": img.height
        }
    except Exception as e:
        return {"success": False, "error": f"Screenshot failed: {e}"}
