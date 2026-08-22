"""Audit Logging -- Phase 3.

Every safety-relevant decision the Executor makes gets one row here:
what was requested, which tool, its risk level, the permission result,
the confirmation result, the execution result, and the verification
result. This is the ONLY code path permitted to write to
`audit_log_entries`, and it redacts anything that looks like a secret
before it ever reaches the database or a log line.
"""

from app.audit.log import AuditLogger, redact_detail

__all__ = ["AuditLogger", "redact_detail"]
