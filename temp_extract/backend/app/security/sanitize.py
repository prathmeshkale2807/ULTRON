"""
Sanitization helpers for fields written into the permanent audit trail.

`normalize_actor` is the single authoritative cleaner for every caller-
supplied identity field (actor, updated_by, reset_by, activated_by) that
ends up in a PermissionAuditEntry row. Its goals:

1. Prevent control characters (newlines, tabs, ANSI escapes, NUL) from
   embedding false line-breaks or escape sequences in structured log lines.
2. Collapse whitespace runs to a single space so that log-pattern matching
   stays predictable.
3. Cap the field at 64 characters -- generous enough for any real actor
   identity, conservative enough to prevent DB-column overflow.
4. Default to "unknown" when the result is empty, matching the existing
   pydantic default already used across the API models.

Notably, this function does NOT restrict to ASCII or an allowlist of
characters. Unicode actor names (e.g. for future non-English deployments)
are preserved as long as they contain no control characters. This is the
"lenient" policy choice from the plan review, favoring future
multi-locale compatibility over strict allowlist enforcement.
"""

from __future__ import annotations

import re

# Regex matching any C0/C1 control character and DEL.
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x1f\x7f\ufff0-\uffff]')

_MAX_ACTOR_LENGTH = 64
_DEFAULT_ACTOR = "unknown"


def normalize_actor(raw: str) -> str:
    """Return a safe, bounded actor-identity string suitable for storage
    in an audit log row.

    Steps:
    1. Strip leading/trailing whitespace.
    2. Replace any control characters (including CR, LF, TAB, NUL, ANSI
       escape sequences) with a single underscore.
    3. Collapse runs of multiple spaces to one space.
    4. Truncate to _MAX_ACTOR_LENGTH.
    5. Return _DEFAULT_ACTOR if the result is empty.
    """
    if not isinstance(raw, str):
        return _DEFAULT_ACTOR

    # Step 1: strip outer whitespace
    cleaned = raw.strip()

    # Step 2: replace control characters with underscore
    cleaned = _CONTROL_CHAR_RE.sub("_", cleaned)

    # Step 3: collapse multiple spaces to one
    cleaned = re.sub(r" {2,}", " ", cleaned)

    # Step 4: truncate
    cleaned = cleaned[:_MAX_ACTOR_LENGTH]

    # Step 5: default if empty
    return cleaned if cleaned else _DEFAULT_ACTOR
