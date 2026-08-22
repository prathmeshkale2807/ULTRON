import ipaddress
import re
from urllib.parse import urlparse
from app.core.config import get_settings

class BrowserSafetyError(Exception):
    """Raised when a browser action violates a safety policy."""
    pass

def validate_url_safe(url: str) -> str:
    """
    Validates that a URL is safe to navigate to.
    Rejects non-http(s) schemes, and handles local network blocks
    based on the ALLOW_LOCAL_NETWORK_BROWSER setting.
    """
    if not url:
        raise BrowserSafetyError("URL cannot be empty.")
    
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise BrowserSafetyError(f"Scheme '{parsed.scheme}' is strictly forbidden.")

    # Check for private IP ranges if the setting is false
    settings = get_settings()
    if not settings.allow_local_network_browser:
        hostname = parsed.hostname
        if hostname:
            if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
                raise BrowserSafetyError("Localhost access is strictly forbidden by policy.")
            
            # Check if hostname is an IP address
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    raise BrowserSafetyError(f"Private/local network access is strictly forbidden by policy: {hostname}")
            except ValueError:
                # Not an IP literal, could still resolve to local but we block obvious ones
                pass

    return url

def check_sensitive_field(html_element: dict) -> bool:
    """
    Heuristic check if a field is likely sensitive (password, card, etc).
    This is defense-in-depth and does not replace explicit confirmation gates.
    """
    sensitive_keywords = ["password", "card", "cvv", "credit", "debit", "secret", "token", "otp"]
    
    # If the tag is an input of type password
    node_name = html_element.get("nodeName", "").lower()
    input_type = html_element.get("type", "").lower()
    name = html_element.get("name", "").lower()
    id_attr = html_element.get("id", "").lower()
    
    if node_name == "input" and input_type == "password":
        return True
        
    # Check attributes for sensitive names
    for attr in [name, id_attr]:
        for kw in sensitive_keywords:
            if kw in attr:
                return True
                
    return False

def wrap_untrusted_content(content: str) -> str:
    """
    Mandatory wrapper for all extracted webpage content to prevent prompt injection.
    """
    return f"\n--- UNTRUSTED_EXTERNAL_CONTENT START ---\n{content}\n--- UNTRUSTED_EXTERNAL_CONTENT END ---\n"
