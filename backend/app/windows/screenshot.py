"""
Screenshot functionality.
"""
from PIL import ImageGrab
import tempfile
import os
import time
from typing import Any

def take_screenshot() -> dict[str, Any]:
    """Captures the current screen and returns it as a base64 string."""
    try:
        import uuid
        import base64
        # all_screens=True captures all monitors if applicable.
        img = ImageGrab.grab(all_screens=True)
        if not img or img.width == 0 or img.height == 0:
             return {"success": False, "error": "Failed to capture screen, image dimensions are invalid."}
        
        # Save to a temporary file with a collision-resistant name
        temp_dir = os.path.join(tempfile.gettempdir(), "ultron_screenshots")
        os.makedirs(temp_dir, exist_ok=True)
        filename = f"screenshot_{uuid.uuid4().hex}.png"
        filepath = os.path.join(temp_dir, filename)
        
        img.save(filepath, "PNG")
        
        # Verify capture was successful by checking file size
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            if os.path.exists(filepath):
                os.remove(filepath)
            return {"success": False, "error": "Screenshot capture failed: file is empty."}
        
        # "Controlled consumption" - encode to base64
        with open(filepath, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
            
        # Clean up the temporary screenshot file immediately after consumption
        os.remove(filepath)
        
        return {
            "success": True,
            "image_base64_secret": b64_data, # _secret suffix ensures AuditLog redaction
            "width": img.width,
            "height": img.height
        }
    except Exception as e:
        return {"success": False, "error": f"Screenshot failed: {e}"}
