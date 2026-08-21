"""
Local authorization boundary.

Phase 4 explicitly forbids assuming "the caller is on localhost" is
sufficient authorization -- any local process (or a malicious page
running in a browser tab, via CSRF-style requests to 127.0.0.1) can
reach a service bound to localhost. Sensitive local management
operations therefore require a bearer-style local token in addition to
being reachable at all.

Mechanism: a random token is generated once and persisted to a file
under the app's local data directory (`data/local_auth.token`), with
owner-only permissions where the OS supports it (POSIX; best-effort,
non-fatal on Windows). This is the same shape Jupyter uses for its own
localhost-only auth. The future Tauri desktop UI reads this file
directly off disk (it runs as the same local user) and sends its
contents back as the `X-Ultron-Auth` header -- no network exposure, no
remote Internet access, nothing beyond "can this caller read a file
that only the local user account can read".

This module intentionally does NOT implement remote/network
authentication (OAuth, JWT-over-the-internet, etc.) -- that is
explicitly out of scope until Remote Mode gets its own security
review.
"""

from __future__ import annotations

import secrets
import stat

from fastapi import Header, HTTPException

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger("security.local_auth")

_TOKEN_FILENAME = "local_auth.token"


def _token_path():
    settings = get_settings()
    settings.ensure_data_dirs()
    return settings.data_dir / _TOKEN_FILENAME


def get_or_create_local_token() -> str:
    """Return the persisted local auth token, generating one on first
    use. Idempotent across restarts -- the Tauri UI's copy of the token
    stays valid until the token file is deleted."""
    path = _token_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    try:
        # Owner read/write only. Best-effort: Windows filesystems that
        # don't support POSIX mode bits simply ignore this, which is
        # fine -- the token file living under the user's own local data
        # directory is still the primary boundary there.
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        logger.debug("Could not restrict permissions on %s (non-POSIX filesystem?)", path)
    logger.info("Generated new local auth token at %s", path)
    return token


def require_local_auth(x_ultron_auth: str | None = Header(default=None)) -> str:
    """FastAPI dependency: raises 401 unless the caller presents the
    current local auth token via the `X-Ultron-Auth` header. Use on
    every sensitive local management endpoint (permission grant/revoke,
    profile changes, emergency-stop reset) -- never on read-only status
    endpoints, and never as a substitute for the ALWAYS_ASK/CRITICAL
    safety floors, which this has no bearing on."""
    expected = get_or_create_local_token()
    if not x_ultron_auth or not secrets.compare_digest(x_ultron_auth, expected):
        raise HTTPException(status_code=401, detail="missing or invalid local auth token")
    return x_ultron_auth
