"""add_tnc_fields

Revision ID: c8e054023c8b
Revises: add_sites_001
Create Date: 2026-06-10 12:44:10.646013

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'c8e054023c8b'
down_revision: Union[str, None] = 'add_sites_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('purchase_orders', sa.Column('penalty_clauses', sa.Text(), nullable=True))
    op.add_column('purchase_orders', sa.Column('delivery_terms', sa.Text(), nullable=True))
    op.add_column('purchase_orders', sa.Column('warranty_terms', sa.Text(), nullable=True))
    op.add_column('purchase_orders', sa.Column('special_conditions', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('purchase_orders', 'special_conditions')
    op.drop_column('purchase_orders', 'warranty_terms')
    op.drop_column('purchase_orders', 'delivery_terms')
    op.drop_column('purchase_orders', 'penalty_clauses')
