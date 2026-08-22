"""
Local authorization boundary.

Phase 4 explicitly forbids assuming "the caller is on localhost" is
sufficient authorization -- any local process (or a malicious page
running in a browser tab, via CSRF-style requests to 127.0.0.1) can
reach a service bound to localhost. Sensitive local management
operations therefore require a bearer-style local token in addition to
being reachable at all.

Secret storage
--------------
The token is stored in Windows Credential Manager (DPAPI-encrypted,
tied to the Windows user account) in production, and in a plaintext
file for test/development. See app/security/secret_store.py for the
backend selection logic.

Principal derivation (Phase 4 single-user model)
-------------------------------------------------
A valid token proves "the caller has read access to the ULTRON
credential on this machine". There is exactly one credential (one
shared secret), so every successfully authenticated caller is the same
principal: "local". The Principal object is returned by
require_local_auth() and MUST be used as the authoritative audit
identity -- callers must never use request-body fields (actor,
updated_by, reset_by, etc.) for this purpose, as those are
client-controlled and cannot be trusted as identity claims.

Rotation / revocation
---------------------
  rotate_local_token()  -- generate a new token; old token is invalid
  revoke_local_token()  -- delete the credential; all auth fails until
                           the next get_or_create_local_token() call

This module intentionally does NOT implement remote/network
authentication (OAuth, JWT-over-the-internet, etc.) -- that is
explicitly out of scope until Remote Mode gets its own security
review.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.core.logging_config import get_logger
from app.security.secret_store import get_store

logger = get_logger("security.local_auth")

_MIN_TOKEN_LENGTH = 32
_VALID_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
)

# The single principal identity for the Phase 4 local single-user model.
# In a future multi-user phase this would carry a real user identifier.
_LOCAL_PRINCIPAL_IDENTITY = "local"


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity, derived server-side from a valid
    local auth token. NEVER sourced from any request body field.

    In Phase 4 (single local user), identity is always the string
    "local". Future phases with per-user tokens would populate a
    richer identifier here.
    """

    identity: str


def _token_is_valid(token: str) -> bool:
    """Return True only if *token* looks like a real urlsafe token:
    non-empty, at least _MIN_TOKEN_LENGTH chars, all characters from
    the urlsafe-base64 alphabet. A corrupt or accidentally-truncated
    stored token fails this check and triggers regeneration instead of
    a permanent management-API lockout."""
    return (
        bool(token)
        and len(token) >= _MIN_TOKEN_LENGTH
        and all(c in _VALID_TOKEN_CHARS for c in token)
    )


def get_or_create_local_token() -> str:
    """Return the persisted local auth token, generating one on first
    use. Idempotent across restarts -- the Tauri UI copy stays valid
    until the credential is deleted, rotated, or found corrupt.

    Never logs the token value."""
    store = get_store()
    candidate = store.get()

    if candidate is not None:
        if _token_is_valid(candidate):
            return candidate
        # Corrupt credential -- log at ERROR (never the value), regenerate.
        logger.error(
            "Stored local auth token is malformed (length=%d); regenerating. "
            "The desktop UI will need its copy refreshed.",
            len(candidate),
        )

    # Generate and persist a new token.  Never log the token value.
    token = secrets.token_urlsafe(32)
    store.set(token)
    logger.info("Generated and stored new local auth token")
    return token


def rotate_local_token() -> str:
    """Invalidate the current token and issue a new one.

    The new token is returned so the caller (e.g. the Tauri UI setup
    flow) can distribute it. Never logs the token value."""
    store = get_store()
    store.delete()
    token = secrets.token_urlsafe(32)
    store.set(token)
    logger.info("Local auth token rotated; previous token is invalid")
    return token


def revoke_local_token() -> None:
    """Delete the auth token from the credential store.

    After revocation every management API call returns 401 until
    get_or_create_local_token() is called (which regenerates)."""
    get_store().delete()
    logger.info("Local auth token revoked")


def require_local_auth(
    x_ultron_auth: str | None = Header(default=None),
) -> Principal:
    """FastAPI dependency: authenticate the caller and return a Principal.

    Raises HTTP 401 if the header is missing or does not match the
    stored token.

    The returned Principal.identity is ALWAYS derived from a valid token
    -- it is NEVER sourced from any request body field. Every route that
    Depends() on this must use principal.identity for audit records, NOT
    any actor/updated_by/reset_by value supplied by the caller.

    Use on every sensitive local management endpoint (permission
    grant/revoke, profile changes, emergency-stop reset). Never on
    read-only status endpoints, and never as a substitute for the
    ALWAYS_ASK/CRITICAL safety floors, which this has no bearing on.
    """
    expected = get_or_create_local_token()
    if not x_ultron_auth or not secrets.compare_digest(x_ultron_auth, expected):
        raise HTTPException(status_code=401, detail="missing or invalid local auth token")
    return Principal(identity=_LOCAL_PRINCIPAL_IDENTITY)
