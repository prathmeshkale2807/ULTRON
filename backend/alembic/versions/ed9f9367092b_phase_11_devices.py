"""Phase 11 devices

Revision ID: ed9f9367092b
Revises: a3f8c2e9d041
Create Date: 2026-08-22 17:57:18.596010

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ed9f9367092b'
down_revision: Union[str, None] = 'a3f8c2e9d041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('device_pairing_codes',
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('principal_id', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('device_name_hint', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('code')
    )
    op.create_index(op.f('ix_device_pairing_codes_principal_id'), 'device_pairing_codes', ['principal_id'], unique=False)
    
    op.create_table('device_records',
        sa.Column('device_id', sa.String(length=64), nullable=False),
        sa.Column('principal_id', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('device_type', sa.String(length=32), nullable=False),
        sa.Column('credential_hash', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('device_id')
    )
    op.create_index(op.f('ix_device_records_principal_id'), 'device_records', ['principal_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_device_records_principal_id'), table_name='device_records')
    op.drop_table('device_records')
    op.drop_index(op.f('ix_device_pairing_codes_principal_id'), table_name='device_pairing_codes')
    op.drop_table('device_pairing_codes')
