from __future__ import annotations

from enum import Enum


class PermissionScope(str, Enum):
    SESSION = "session"
    PERSISTENT = "persistent"


class PermissionStatus(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"
    UNSET = "unset"  # no explicit decision has ever been recorded
