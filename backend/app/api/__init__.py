from fastapi import APIRouter

from app.api import confirmations, emergency, health, permissions, tools

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(tools.router, tags=["tools"])
api_router.include_router(permissions.router, tags=["permissions"])
api_router.include_router(confirmations.router, tags=["confirmations"])
api_router.include_router(emergency.router, tags=["emergency"])
