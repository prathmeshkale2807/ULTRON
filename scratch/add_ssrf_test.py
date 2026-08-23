with open("backend/tests/test_phase18_security.py", "a") as f:
    f.write('''
def test_browser_ssrf_dns_hardening(monkeypatch):
    """
    Test that browser URL validation resolves DNS and blocks SSRF targets.
    """
    from app.browser.safety import validate_url_safe, BrowserSafetyError
    import socket
    
    # Mock DNS resolution to return 127.0.0.1
    def mock_gethostbyname(hostname):
        return "127.0.0.1"
        
    monkeypatch.setattr(socket, "gethostbyname", mock_gethostbyname)
    
    # Ensure local network is not allowed
    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_LOCAL_NETWORK_BROWSER", "False")
    
    import pytest
    with pytest.raises(BrowserSafetyError, match="strictly forbidden"):
        validate_url_safe("http://evil.com/admin")
        
    # Unresolvable hostname
    def mock_gethostbyname_fail(hostname):
        raise socket.gaierror("Name or service not known")
    monkeypatch.setattr(socket, "gethostbyname", mock_gethostbyname_fail)
    
    with pytest.raises(BrowserSafetyError, match="Could not resolve"):
        validate_url_safe("http://nonexistent.internal")
''')
