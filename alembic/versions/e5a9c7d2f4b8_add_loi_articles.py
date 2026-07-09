"""add loi_articles (customized LOI clause set) to purchase_orders

Revision ID: e5a9c7d2f4b8
Revises: b3e8d2f1a9c5
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e5a9c7d2f4b8"
down_revision = "b3e8d2f1a9c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("loi_articles", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("purchase_orders", "loi_articles")
