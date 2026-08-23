"""Add principal_id to sessions and permissions

Revision ID: 57e210ab9293
Revises: 503cc6a317d8
Create Date: 2026-08-23 14:40:17.799687

"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '57e210ab9293'
down_revision: Union[str, None] = '503cc6a317d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('permission_records', sa.Column('principal_id', sa.String(length=128), server_default='local_user', nullable=False))
    op.create_index(op.f('ix_permission_records_principal_id'), 'permission_records', ['principal_id'], unique=False)
    op.add_column('sessions', sa.Column('principal_id', sa.String(length=128), server_default='local_user', nullable=False))
    op.create_index(op.f('ix_sessions_principal_id'), 'sessions', ['principal_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_sessions_principal_id'), table_name='sessions')
    op.drop_column('sessions', 'principal_id')
    op.drop_index(op.f('ix_permission_records_principal_id'), table_name='permission_records')
    op.drop_column('permission_records', 'principal_id')
