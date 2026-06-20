"""add po_type to purchase_orders

Revision ID: a7f3c9e1b2d4
Revises: c01ccc667203
Create Date: 2026-06-20

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7f3c9e1b2d4"
down_revision = "c01ccc667203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("po_type", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("purchase_orders", "po_type")
