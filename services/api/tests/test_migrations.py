"""Migrations apply and roll back cleanly on an empty database, and match the ORM model."""

from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, make_url

from recallspring_api.models import Base

from .conftest import alembic_config, recreate_database


def test_upgrade_downgrade_roundtrip_and_no_model_drift(migrated_database: str) -> None:
    url = make_url(migrated_database).set(database="recallspring_migration_test").render_as_string(hide_password=False)
    recreate_database(url)
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine.dispose()
