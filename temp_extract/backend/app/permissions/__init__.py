"""Permission State -- Phase 3.

Tracks grant / revoke / check for permission categories, at two scopes:
  - session:    lives only as long as the current process/session; never
                touches the database.
  - persistent: survives restarts, backed by the `permission_records`
                table (see app/core/database.py).

A permission record is always just: category (+ optional tool/device
narrowing) + granted/denied. Never a secret, a token, or anything else
that would need protecting beyond normal DB access control.
"""

from app.permissions.models import PermissionScope, PermissionStatus
from app.permissions.store import PermissionStore

__all__ = ["PermissionScope", "PermissionStatus", "PermissionStore"]
