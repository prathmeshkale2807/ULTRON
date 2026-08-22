"""
Secret storage abstraction for the ULTRON local auth token.

Two backends:

  KeyringStore (PRODUCTION)
    Uses the `keyring` library, which on Windows delegates to Windows
    Credential Manager. Credentials are encrypted at rest with DPAPI,
    tied to the Windows user account. The token is NEVER written to the
    filesystem in plaintext. keyring is imported lazily inside
    KeyringStore.__init__ so the module is importable in environments
    where keyring is not installed (e.g. CI) -- the error surfaces only
    when production storage is actually attempted.

  FileStore (TEST / DEVELOPMENT ONLY)
    Plaintext file in the app data directory. Used when
    settings.environment is "test" or "development". NEVER instantiated
    when environment == "production". Preserves the test-isolation
    contract: each test fixture sets its own LOG_DIR / data_dir via
    monkeypatch, so every test gets its own isolated token file.

Public surface
--------------
  get_store() -> SecretStore
      Factory: returns the right backend for the current environment.
      Called on every auth operation so that test monkeypatching of
      ENVIRONMENT / LOG_DIR is always respected.

  SecretStore.get()    -> str | None   -- retrieve token or None
  SecretStore.set(tok) -> None         -- store / overwrite token
  SecretStore.delete() -> None         -- revoke / delete token

  SecretStore is an ABC -- callers program to the interface, not the
  backend.
"""

from __future__ import annotations

import stat
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.logging_config import get_logger

logger = get_logger("security.secret_store")

_SERVICE_NAME = "ULTRON-LocalAuth"
_CREDENTIAL_NAME = "local_auth_token"
_TOKEN_FILENAME = "local_auth.token"


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class SecretStore(ABC):
    """Minimal interface for token persistence."""

    @abstractmethod
    def get(self) -> str | None:
        """Return the stored token, or None if no token exists."""

    @abstractmethod
    def set(self, token: str) -> None:
        """Persist *token*. Never log the token value."""

    @abstractmethod
    def delete(self) -> None:
        """Delete the stored token. No-op if it does not exist."""


# ---------------------------------------------------------------------------
# Production backend: Windows Credential Manager via keyring
# ---------------------------------------------------------------------------


class KeyringStore(SecretStore):
    """Stores the auth token in Windows Credential Manager.

    keyring.get/set/delete_password map to the WinVault backend on
    Windows, which uses DPAPI for at-rest encryption. The credential is
    tied to the logged-in Windows user and is NOT accessible to other
    Windows user accounts on the same machine.

    ONLY instantiated when settings.environment == "production".
    """

    def __init__(self) -> None:
        try:
            import keyring as _kr  # lazy import -- not required at module level

            self._kr = _kr
        except ImportError as exc:
            raise RuntimeError(
                "The 'keyring' library is required for production secret "
                "storage. Run: pip install keyring"
            ) from exc

    def get(self) -> str | None:
        value = self._kr.get_password(_SERVICE_NAME, _CREDENTIAL_NAME)
        return value if value else None  # normalize empty string to None

    def set(self, token: str) -> None:
        # Never log the token value -- only the operation name.
        self._kr.set_password(_SERVICE_NAME, _CREDENTIAL_NAME, token)
        logger.info("Token stored in Windows Credential Manager (%s / %s)", _SERVICE_NAME, _CREDENTIAL_NAME)

    def delete(self) -> None:
        try:
            self._kr.delete_password(_SERVICE_NAME, _CREDENTIAL_NAME)
            logger.info("Token deleted from Windows Credential Manager")
        except Exception:  # noqa: BLE001
            pass  # already deleted or never existed -- both are fine


# ---------------------------------------------------------------------------
# Test/development backend: plaintext file
# ---------------------------------------------------------------------------


class FileStore(SecretStore):
    """Plaintext file in the app data directory.

    !! TEST AND DEVELOPMENT USE ONLY !!

    Never instantiated when settings.environment == "production".
    File is created with owner-read/write-only permissions (best-effort
    on Windows where POSIX mode bits are unsupported).
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / _TOKEN_FILENAME
        data_dir.mkdir(parents=True, exist_ok=True)

    def get(self) -> str | None:
        if not self._path.exists():
            return None
        text = self._path.read_text(encoding="utf-8").strip()
        return text if text else None

    def set(self, token: str) -> None:
        self._path.write_text(token, encoding="utf-8")
        try:
            self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            logger.warning(
                "Could not restrict permissions on %s -- token file may be "
                "readable by other local users (non-POSIX filesystem).",
                self._path,
            )

    def delete(self) -> None:
        if self._path.exists():
            self._path.unlink()
            logger.info("Token file deleted: %s", self._path)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_store() -> SecretStore:
    """Return the secret store appropriate for the current environment.

    Called on every auth operation (not cached) so that test fixtures
    that monkeypatch ENVIRONMENT / LOG_DIR are always respected.
    """
    from app.core.config import get_settings

    settings = get_settings()
    settings.ensure_data_dirs()

    if settings.environment == "production":
        return KeyringStore()

    # "development" and "test" both use the file backend.
    return FileStore(settings.data_dir)
