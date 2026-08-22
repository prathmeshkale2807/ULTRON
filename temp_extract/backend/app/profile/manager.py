"""
Persistent active profile (Safe/Balanced/Trusted/Custom).

A singleton row (id=1) is the source of truth, same pattern as
EmergencyStopRecord -- every process sharing the database agrees on the
active profile, including after a restart, and Balanced is the default
only until someone explicitly chooses otherwise.

This module only owns *persistence and shape*. It never loosens what a
mode is allowed to do -- that enforcement lives entirely in
app/safety/gate.py's SafetyGate, which this module hands back a
correctly-configured instance of via `to_gate()`. Custom Mode's
per-category overrides are validated against the same enums the gate
already understands; SafetyGate's own non-overridable floors
(ALWAYS_ASK / CRITICAL) apply regardless of what's stored here, so a
Custom override can never actually bypass them even if misconfigured.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import ActiveProfileRecord
from app.core.logging_config import get_logger
from app.safety.gate import SafetyGate
from app.safety.models import SafetyMode
from app.tools.models import ConfirmationTier, PermissionCategory

logger = get_logger("profile.manager")

_SINGLETON_ID = 1
_DEFAULT_MODE = SafetyMode.BALANCED


class ProfileState(BaseModel):
    mode: SafetyMode
    custom_overrides: dict[PermissionCategory, ConfirmationTier]
    updated_at: datetime | None
    updated_by: str


class ProfileManager:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_or_create_row(self) -> ActiveProfileRecord:
        row = self.db.get(ActiveProfileRecord, _SINGLETON_ID)
        if row is None:
            row = ActiveProfileRecord(
                id=_SINGLETON_ID,
                mode=_DEFAULT_MODE.value,
                custom_overrides="{}",
                updated_at=datetime.now(timezone.utc),
                updated_by="",
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    def get(self) -> ProfileState:
        row = self._get_or_create_row()
        return self._to_state(row)

    def set(
        self,
        mode: SafetyMode,
        *,
        custom_overrides: dict[PermissionCategory, ConfirmationTier] | None = None,
        updated_by: str = "unknown",
    ) -> ProfileState:
        row = self._get_or_create_row()
        row.mode = mode.value
        if custom_overrides is not None:
            row.custom_overrides = json.dumps(
                {k.value: v.value for k, v in custom_overrides.items()}
            )
        elif mode != SafetyMode.CUSTOM:
            # Leaving a stale override map around is harmless (the gate
            # ignores it outside Custom Mode) but confusing to inspect,
            # so clear it whenever we leave Custom Mode without a new map.
            row.custom_overrides = "{}"
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = updated_by[:128]
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        logger.info("Active profile set to %s by=%s", mode.value, updated_by)
        return self._to_state(row)

    def to_gate(self) -> tuple[SafetyGate, SafetyMode]:
        """Convenience for callers (e.g. a future execute endpoint) that
        need a ready-to-use SafetyGate matching the persisted profile."""
        state = self.get()
        return SafetyGate(custom_overrides=state.custom_overrides), state.mode

    @staticmethod
    def _to_state(row: ActiveProfileRecord) -> ProfileState:
        try:
            raw_overrides: dict[str, str] = json.loads(row.custom_overrides or "{}")
        except (json.JSONDecodeError, TypeError):
            raw_overrides = {}
        overrides: dict[PermissionCategory, ConfirmationTier] = {}
        for cat, tier in raw_overrides.items():
            try:
                overrides[PermissionCategory(cat)] = ConfirmationTier(tier)
            except ValueError:
                continue  # ignore unrecognized/corrupt entries defensively
        return ProfileState(
            mode=SafetyMode(row.mode),
            custom_overrides=overrides,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        )
