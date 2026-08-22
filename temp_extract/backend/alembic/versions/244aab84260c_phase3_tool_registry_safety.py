"""phase 3: permission records, audit log, emergency stop state

Revision ID: 244aab84260c
Revises: def515f5d079
Create Date: 2026-08-21

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "244aab84260c"
down_revision: Union[str, None] = "def515f5d079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "permission_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("device", sa.String(length=32), nullable=True),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_permission_records_category", "permission_records", ["category"]
    )

    op.create_table(
        "audit_log_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("requested_action", sa.String(length=256), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("permission_result", sa.String(length=32), nullable=False),
        sa.Column("confirmation_result", sa.String(length=32), nullable=False),
        sa.Column("execution_result", sa.String(length=32), nullable=False),
        sa.Column("verification_result", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=1024), nullable=False, server_default=""),
    )
    op.create_index("ix_audit_log_entries_tool_name", "audit_log_entries", ["tool_name"])

    op.create_table(
        "emergency_stop_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("engaged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("activated_by", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("emergency_stop_state")
    op.drop_index("ix_audit_log_entries_tool_name", table_name="audit_log_entries")
    op.drop_table("audit_log_entries")
    op.drop_index("ix_permission_records_category", table_name="permission_records")
    op.drop_table("permission_records")
