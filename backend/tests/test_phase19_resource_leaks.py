import pytest
import asyncio
from app.tasks.manager import TaskManager, register_token, unregister_token, get_token
from app.tasks.models import CancellationToken

@pytest.mark.asyncio
async def test_tokens_cleaned_up(db_session):
    # Register a token
    token = CancellationToken()
    register_token("task_leak_1", token)
    
    assert get_token("task_leak_1") is not None
    
    # Unregister
    unregister_token("task_leak_1")
    
    assert get_token("task_leak_1") is None

@pytest.mark.asyncio
async def test_browser_context_cleanup():
    # If the manager is cancelled, contexts should close
    from app.browser.manager import BrowserManager
    mgr = BrowserManager()
    await mgr.startup()
    try:
        await mgr.get_or_create_context("sess1")
        
        # Close session
        await mgr.close_session("sess1")
        
        assert "sess1" not in mgr._contexts
    finally:
        await mgr.shutdown()
