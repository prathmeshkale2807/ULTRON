from fastapi import APIRouter

from app.api import confirmations, emergency, health, permissions, profile, sessions, tasks, tools, conversations, devices

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(tools.router, tags=["tools"])
api_router.include_router(permissions.router, tags=["permissions"])
api_router.include_router(confirmations.router, tags=["confirmations"])
api_router.include_router(emergency.router, tags=["emergency"])
api_router.include_router(profile.router, tags=["profile"])
api_router.include_router(sessions.router, tags=["sessions"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(conversations.router, tags=["conversations"])
api_router.include_router(devices.router, tags=["devices"])
from app.api import memory
api_router.include_router(memory.router, tags=["memory"])
