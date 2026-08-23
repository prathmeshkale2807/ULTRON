import asyncio
import logging
from typing import Dict, Any

from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page, Request
from app.browser.safety import validate_url_safe, BrowserSafetyError

logger = logging.getLogger(__name__)

class BrowserManager:
    """
    Singleton manager for the Playwright browser engine.
    Ensures safe, isolated execution of browser actions, strictly separated by session.
    """
    _instance = None
    _playwright: Playwright | None = None
    _browser: Browser | None = None
    _contexts: Dict[str, BrowserContext] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def startup(self):
        """Initialize the global Playwright engine."""
        if not self._playwright:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"]
            )
            logger.info("Browser engine started.")

    async def shutdown(self):
        """Close all contexts and shutdown the engine."""
        for session_id, context in list(self._contexts.items()):
            await self.close_session(session_id)
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        BrowserManager._instance = None
        logger.info("Browser engine shutdown.")

    async def get_or_create_context(self, session_id: str) -> BrowserContext:
        """
        Get the active browser context for a session, creating one if it doesn't exist.
        Each context is completely isolated (ephemeral).
        """
        if not self._browser:
            await self.startup()

        if session_id not in self._contexts:
            # Create a strictly ephemeral context (no persistence)
            context = await self._browser.new_context(
                accept_downloads=False,
                ignore_https_errors=False,
                viewport={"width": 1280, "height": 720}
            )
            
            # Intercept and block dangerous requests/redirects
            async def route_handler(route, request: Request):
                try:
                    # Validate URL. If it fails, route.abort() will block it.
                    validate_url_safe(request.url)
                    
                    # Prevent redirect bypasses by fetching the request manually
                    # without following redirects, then validating the Location header.
                    response = await route.fetch(max_redirects=0)
                    
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if location:
                            from urllib.parse import urljoin
                            absolute_location = urljoin(request.url, location)
                            validate_url_safe(absolute_location)
                            
                    await route.fulfill(response=response)
                except BrowserSafetyError as e:
                    logger.warning(f"Blocked unsafe navigation/resource request: {request.url} - {e}")
                    await route.abort(error_code="accessdenied")
                except Exception as e:
                    logger.error(f"Error handling route {request.url}: {e}")
                    await route.abort(error_code="aborted")

            await context.route("**/*", route_handler)
            self._contexts[session_id] = context
            logger.info(f"Created isolated browser context for session {session_id}")

        return self._contexts[session_id]

    async def close_session(self, session_id: str):
        """Close an isolated context, cleaning up its resources."""
        context = self._contexts.pop(session_id, None)
        if context:
            await context.close()
            logger.info(f"Closed browser context for session {session_id}")

    async def get_active_page(self, session_id: str) -> Page | None:
        """Helper to get the current active page in a session's context."""
        if session_id in self._contexts:
            pages = self._contexts[session_id].pages
            if pages:
                return pages[-1]
        return None

def get_browser_manager() -> BrowserManager:
    return BrowserManager()
