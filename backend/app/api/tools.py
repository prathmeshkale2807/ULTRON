"""
Tool Registry API surface.

Read-only listing of registered tools plus enable/disable, so a future
desktop UI can show "what can ULTRON do and what's switched on" without
the UI ever needing a handle to a tool's handler -- this endpoint only
ever serializes ToolDefinition.public_metadata(), which excludes
`handler`/`verifier` by construction (see app/tools/models.py).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.tools.registry import ToolNotFoundError, get_registry
from app.security.local_auth import Principal, require_local_auth

router = APIRouter(prefix="/tools")


class SetEnabledRequest(BaseModel):
    enabled: bool


@router.get("")
def list_tools(
    enabled_only: bool = False,
    principal: Principal = Depends(require_local_auth)
) -> list[dict]:
    registry = get_registry()
    return [t.public_metadata() for t in registry.list_tools(enabled_only=enabled_only)]


@router.get("/{name}")
def get_tool(name: str, principal: Principal = Depends(require_local_auth)) -> dict:
    registry = get_registry()
    try:
        return registry.get(name).public_metadata()
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{name}/enabled")
def set_tool_enabled(
    name: str, 
    body: SetEnabledRequest,
    principal: Principal = Depends(require_local_auth)
) -> dict:
    registry = get_registry()
    try:
        tool = registry.set_enabled(name, body.enabled)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return tool.public_metadata()
