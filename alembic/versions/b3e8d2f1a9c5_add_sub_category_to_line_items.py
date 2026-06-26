"""add sub_category to po_line_items

Revision ID: b3e8d2f1a9c5
Revises: a7f3c9e1b2d4
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa

revision = "b3e8d2f1a9c5"
down_revision = "a7f3c9e1b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "po_line_items",
        sa.Column("sub_category", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("po_line_items", "sub_category")
