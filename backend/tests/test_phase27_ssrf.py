import pytest
import asyncio
from app.browser.safety import validate_url_safe, BrowserSafetyError
from app.core.config import get_settings
from app.browser.manager import get_browser_manager
from playwright.async_api import Error as PlaywrightError

def test_dns_resolved_private_destination(monkeypatch):
    import socket
    
    def mock_gethostbyname(hostname):
        return "192.168.1.1"
        
    monkeypatch.setattr(socket, "gethostbyname", mock_gethostbyname)
    
    with pytest.raises(BrowserSafetyError) as excinfo:
        validate_url_safe("http://example.com")
        
    assert "resolved to 192.168.1.1" in str(excinfo.value)

def test_dns_rebinding_simulation(monkeypatch):
    import socket
    
    calls = []
    def mock_gethostbyname(hostname):
        calls.append(hostname)
        if len(calls) == 1:
            return "8.8.8.8"
        return "127.0.0.1"
        
    monkeypatch.setattr(socket, "gethostbyname", mock_gethostbyname)
    
    assert validate_url_safe("http://rebind.com") == "http://rebind.com"
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_redirect_to_private_blocked():
    manager = get_browser_manager()
    context = await manager.get_or_create_context("test_ssrf_session")
    page = await context.new_page()
    
    try:
        with pytest.raises(PlaywrightError) as excinfo:
            await page.goto("https://httpbin.org/redirect-to?url=http://127.0.0.1/", wait_until="domcontentloaded", timeout=10000)
            
        assert "ERR_ACCESS_DENIED" in str(excinfo.value)
    finally:
        await manager.close_session("test_ssrf_session")
        await manager.shutdown()
