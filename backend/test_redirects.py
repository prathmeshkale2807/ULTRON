import asyncio
import sys
sys.path.append('.')

from app.browser.manager import get_browser_manager
from app.core.config import get_settings
from playwright.async_api import Error

async def main():
    settings = get_settings()
    settings.allow_local_network_browser = False
    
    # We need to temporarily allow the mock server itself
    # but block the redirects. So we will monkeypatch validate_url_safe 
    # to allow port 8001.
    import app.browser.manager as mgr
    original_validate = mgr.validate_url_safe
    
    def mock_validate(url):
        print(f"Intercepting: {url}")
        if "8001" in url:
            return url
        return original_validate(url)
        
    mgr.validate_url_safe = mock_validate
    
    manager = get_browser_manager()
    await manager.startup()
    ctx = await manager.get_or_create_context("test_redirect")
    page = await ctx.new_page()
    
    print("Testing safe URL -> redirect -> private IP")
    try:
        await page.goto("http://127.0.0.1:8001/redirect_private", wait_until="networkidle", timeout=5000)
        print("FAILED (allowed): redirect_private")
    except Exception as e:
        print(f"PASSED (blocked): redirect_private - {e}")
        
    print("Testing safe URL -> redirect -> localhost")
    try:
        await page.goto("http://127.0.0.1:8001/redirect_localhost", wait_until="networkidle", timeout=5000)
        print("FAILED (allowed): redirect_localhost")
    except Exception as e:
        print(f"PASSED (blocked): redirect_localhost - {e}")
        
    print("Testing safe URL -> redirect -> nip.io")
    try:
        await page.goto("http://127.0.0.1:8001/redirect_nip", wait_until="networkidle", timeout=5000)
        print("FAILED (allowed): redirect_nip")
    except Exception as e:
        print(f"PASSED (blocked): redirect_nip - {e}")

    await manager.shutdown()

asyncio.run(main())
