"""phase 4: active profile state, sessions, permission audit entries

Revision ID: 6a1d7d4906b2
Revises: 244aab84260c
Create Date: 2026-08-21

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6a1d7d4906b2"
down_revision: Union[str, None] = "244aab84260c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "active_profile_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="balanced"),
        sa.Column(
            "custom_overrides", sa.String(length=2048), nullable=False, server_default="{}"
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False, server_default=""),
    )

    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "permission_audit_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False, server_default="unknown"),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("device", sa.String(length=32), nullable=True),
        sa.Column("old_state", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("new_state", sa.String(length=64), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_permission_audit_entries_action", "permission_audit_entries", ["action"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_permission_audit_entries_action", table_name="permission_audit_entries"
    )
    op.drop_table("permission_audit_entries")
    op.drop_table("sessions")
    op.drop_table("active_profile_state")
