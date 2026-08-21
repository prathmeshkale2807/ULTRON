"""
Audit logger + redaction.

`redact_detail` is deliberately conservative: it treats any key whose
name *contains* one of the secret-ish substrings below as sensitive,
not just an exact match, so "api_key", "apiKey", "auth_token",
"user_password" etc. are all caught. When in doubt, redact -- an
over-redacted audit log is annoying; a leaked credential in a log file
is a real incident.
"""

from __future__ import annotations

from typing import Any
import re

from app.core.database import AuditLogEntry
from app.core.logging_config import get_logger
from sqlalchemy.orm import Session

logger = get_logger("audit")

_SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
    "authorization",
    "auth_header",
    "session_cookie",
    "ssn",
    "card_number",
)

_MAX_DETAIL_LENGTH = 1024

# Defense-in-depth patterns for common bearer/API-key-like values that may
# arrive inside free-form strings (e.g. exception messages). This is not a
# claim of perfect secret detection; callers should still avoid logging raw
# payloads.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(token\s*[:=]\s*)[^\s,;]+"),
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def redact_detail(data: Any) -> str:
    """Turn arbitrary tool-call detail (args, results, error text) into a
    safe, bounded string for the audit log and application logs. Secret-
    looking keys are replaced with a fixed marker; the value itself is
    never inspected or partially shown, since a truncated secret is
    still a secret."""
    redacted = _redact_value(data)
    text = str(redacted)
    if len(text) > _MAX_DETAIL_LENGTH:
        text = text[: _MAX_DETAIL_LENGTH - 3] + "..."
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if _is_secret_key(str(k)) else _redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(v) for v in value]
    if isinstance(value, str):
        text = value
        for pattern in _SECRET_VALUE_PATTERNS:
            text = pattern.sub(lambda m: f"{m.group(1)}[REDACTED]", text)
        return text
    return value


class AuditLogger:
    """Writes one row per tool-decision. Every field is a short status
    string or identifier -- never a raw payload -- so this class can't
    accidentally become a secrets sink even if a caller passes
    unredacted data as `detail` (it's redacted here too, defensively)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        requested_action: str,
        tool_name: str,
        risk_level: str,
        permission_result: str,
        confirmation_result: str,
        execution_result: str,
        verification_result: str,
        detail: Any = "",
    ) -> AuditLogEntry:
        entry = AuditLogEntry(
            requested_action=requested_action[:256],
            tool_name=tool_name[:128],
            risk_level=risk_level,
            permission_result=permission_result,
            confirmation_result=confirmation_result,
            execution_result=execution_result,
            verification_result=verification_result,
            detail=redact_detail(detail),
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        logger.info(
            "AUDIT tool=%s risk=%s permission=%s confirmation=%s execution=%s verification=%s",
            tool_name,
            risk_level,
            permission_result,
            confirmation_result,
            execution_result,
            verification_result,
        )
        return entry
