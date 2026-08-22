"""Safety Gate -- Phase 3.

Decides, for every tool call, whether it is allowed to proceed
automatically, must be denied outright, or must stop and get an explicit
human confirmation first. This is policy only -- it never touches a
device and never calls a tool handler. See app/executor/ for the
component that enforces the gate's decision.
"""

from app.safety.gate import SafetyGate
from app.safety.models import GateAction, GateDecision, SafetyMode

__all__ = ["SafetyGate", "GateAction", "GateDecision", "SafetyMode"]
