"""phase 5: task manager — task_records and task_audit_entries

Revision ID: a3f8c2e9d041
Revises: 6a1d7d4906b2
Create Date: 2026-08-21

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f8c2e9d041"
down_revision: Union[str, None] = "6a1d7d4906b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_records",
        sa.Column("task_id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("error_summary", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(), nullable=True),
        sa.Column("tools_requested", sa.String(length=1024), nullable=False, server_default="[]"),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column("progress_metadata", sa.String(length=2048), nullable=True),
    )
    op.create_index("ix_task_records_session_id", "task_records", ["session_id"])
    op.create_index("ix_task_records_state", "task_records", ["state"])

    op.create_table(
        "task_audit_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("actor", sa.String(length=128), nullable=False, server_default="system"),
    )
    op.create_index("ix_task_audit_entries_task_id", "task_audit_entries", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_audit_entries_task_id", table_name="task_audit_entries")
    op.drop_table("task_audit_entries")
    op.drop_index("ix_task_records_state", table_name="task_records")
    op.drop_index("ix_task_records_session_id", table_name="task_records")
    op.drop_table("task_records")
