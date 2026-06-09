"""add sites budget categories

Revision ID: add_sites_001
Revises: 50d0e2ba9ffd
Create Date: 2026-06-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'add_sites_001'
down_revision: Union[str, None] = '50d0e2ba9ffd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Sites table ───────────────────────────────────────────────────────────
    op.create_table('sites',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column('location', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('ix_sites_name', 'sites', ['name'])

    # ── Budget Categories table ───────────────────────────────────────────────
    op.create_table('budget_categories',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('site_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('category', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('sub_category', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column('budget_amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('spent_amount', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Add site_id to users ──────────────────────────────────────────────────
    op.add_column('users', sa.Column('site_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_users_site_id', 'users', 'sites', ['site_id'], ['id'])

    # ── Add site_id and budget fields to purchase_orders ─────────────────────
    op.add_column('purchase_orders', sa.Column('site_id', sa.Uuid(), nullable=True))
    op.add_column('purchase_orders', sa.Column('sub_category', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True))
    op.add_column('purchase_orders', sa.Column('exceeds_budget', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('purchase_orders', sa.Column('budget_category_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_po_site_id', 'purchase_orders', 'sites', ['site_id'], ['id'])
    op.create_foreign_key('fk_po_budget_category_id', 'purchase_orders', 'budget_categories', ['budget_category_id'], ['id'])

    # ── Add md_owner role to userrole enum ────────────────────────────────────
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'md_owner'")


def downgrade() -> None:
    op.drop_constraint('fk_po_budget_category_id', 'purchase_orders', type_='foreignkey')
    op.drop_constraint('fk_po_site_id', 'purchase_orders', type_='foreignkey')
    op.drop_column('purchase_orders', 'budget_category_id')
    op.drop_column('purchase_orders', 'exceeds_budget')
    op.drop_column('purchase_orders', 'sub_category')
    op.drop_column('purchase_orders', 'site_id')
    op.drop_constraint('fk_users_site_id', 'users', type_='foreignkey')
    op.drop_column('users', 'site_id')
    op.drop_table('budget_categories')
    op.drop_table('sites')
