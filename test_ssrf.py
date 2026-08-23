import sys
from app.browser.safety import validate_url_safe, BrowserSafetyError
from app.core.config import get_settings

get_settings().allow_local_network_browser = False

test_cases = [
    "http://localtest.me",
    "http://169.254.169.254.nip.io",
    "http://localhost",
    "http://127.0.0.1.nip.io",
    "http://127.0.0.1",
    "http://169.254.169.254"
]

for url in test_cases:
    try:
        validate_url_safe(url)
        print(f"FAILED (allowed): {url}")
    except BrowserSafetyError as e:
        print(f"PASSED (blocked): {url} - {e}")
