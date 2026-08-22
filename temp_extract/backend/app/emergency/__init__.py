"""Emergency Stop Foundation -- Phase 3.

Backend/API surface only: activate / reset / status, DB-backed so an
engaged stop survives a backend restart. The global keyboard/voice kill
switch that calls `activate()` from outside the app is a later phase --
this module is the interface that switch will call into once it exists.

The one hard rule this phase enforces end-to-end: while engaged, the
Tool Executor refuses to start any new tool execution. See
app/executor/executor.py.
"""

from app.emergency.stop import EmergencyStop, EmergencyStopStatus

__all__ = ["EmergencyStop", "EmergencyStopStatus"]
