import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from sqlmodel import SQLModel

# Import all models so Alembic detects them for autogenerate
from app.models.models import (  # noqa: F401
    Department, Project, Vendor, User,
    ApprovalChain, PurchaseOrder, POLineItem,
    ApprovalStep, POAttachment, AuditLog
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Read sync URL directly from environment — no alembic.ini interpolation needed
db_url = os.environ.get("DATABASE_URL_SYNC")
if not db_url:
    raise RuntimeError("DATABASE_URL_SYNC is not set")

config.set_main_option("sqlalchemy.url", db_url)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Use plain SYNC engine — psycopg2, not asyncpg
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()