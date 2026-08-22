"""
Centralized Tool Registry.

This is the ONLY place tools may be looked up from. The AI/orchestrator
layer never holds a direct reference to a tool's handler -- it asks the
registry for a ToolDefinition (metadata only, in practice via the
executor), and only ToolExecutor ever calls .handler(). See
app/executor/executor.py for the enforcement of "the AI must never
execute a tool directly".

Phase 3 registry is in-process and in-memory, rebuilt from source at
startup (tools are code, not user data) -- enabled/disabled *state* is
the only mutable, potentially-persisted piece, and Phase 3 keeps that
in-memory too (a later phase can back it with the database without
changing this class's public surface).
"""

from __future__ import annotations

import threading

from app.core.logging_config import get_logger
from app.tools.models import ToolDefinition

logger = get_logger("tools.registry")


class ToolAlreadyRegisteredError(Exception):
    """Raised when registering a tool name that already exists. Silent
    overwrite of a tool's safety metadata is never allowed."""


class ToolNotFoundError(Exception):
    """Raised when looking up a tool name that isn't registered."""


class ToolRegistry:
    """Thread-safe registry of ToolDefinitions, keyed by unique name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._lock = threading.Lock()

    def register(self, tool: ToolDefinition, *, replace: bool = False) -> None:
        """Register a tool. Raises ToolAlreadyRegisteredError unless
        replace=True is passed explicitly (used only by tests that need
        to swap a mock tool's handler between cases)."""
        with self._lock:
            if tool.name in self._tools and not replace:
                raise ToolAlreadyRegisteredError(
                    f"tool '{tool.name}' is already registered"
                )
            self._tools[tool.name] = tool
        logger.info("Tool registered: %s (risk=%s)", tool.name, tool.risk_level.value)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition:
        with self._lock:
            tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"unknown tool: '{name}'")
        return tool

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._tools

    def list_tools(self, *, enabled_only: bool = False) -> list[ToolDefinition]:
        with self._lock:
            tools = list(self._tools.values())
        if enabled_only:
            tools = [t for t in tools if t.enabled]
        return sorted(tools, key=lambda t: t.name)

    def set_enabled(self, name: str, enabled: bool) -> ToolDefinition:
        with self._lock:
            tool = self._tools.get(name)
            if tool is None:
                raise ToolNotFoundError(f"unknown tool: '{name}'")
            updated = tool.model_copy(update={"enabled": enabled})
            self._tools[name] = updated
        logger.info("Tool %s: %s", "enabled" if enabled else "disabled", name)
        return updated

    def clear(self) -> None:
        """Test-only helper: wipe the registry between test cases."""
        with self._lock:
            self._tools.clear()


_default_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Process-wide default registry. Tests that need isolation should
    construct their own ToolRegistry() instead of using this singleton."""
    return _default_registry
