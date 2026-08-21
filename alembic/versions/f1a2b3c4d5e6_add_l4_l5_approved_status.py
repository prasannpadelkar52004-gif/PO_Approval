"""add L4_APPROVED and L5_APPROVED to postatus enum

Revision ID: f1a2b3c4d5e6
Revises: e5a9c7d2f4b8
Create Date: 2026-08-21

"""
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e5a9c7d2f4b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE postatus ADD VALUE IF NOT EXISTS 'L4_APPROVED' AFTER 'L3_APPROVED'")
    op.execute("ALTER TYPE postatus ADD VALUE IF NOT EXISTS 'L5_APPROVED' AFTER 'L4_APPROVED'")


def downgrade() -> None:
    # Postgres does not support removing enum values; downgrade is a no-op
    pass
