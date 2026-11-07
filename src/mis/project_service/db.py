import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url

from mis.schemas.export import RECORD_MODELS

ROOT = Path(__file__).resolve().parents[3]
NAMES = (
    "projects",
    "baselines",
    "briefs",
    "evidence",
    "artifacts",
    "plans",
    "questions",
    "corrections",
    "test_results",
)
metadata = MetaData(schema="mis")
TABLES = {}
for model, name in zip(RECORD_MODELS, NAMES, strict=True):
    columns = [Column("id", String, primary_key=True)]
    if name != "projects":
        columns.append(
            Column("project_id", String, ForeignKey("mis.projects.id"), nullable=False, index=True)
        )
    columns.extend(
        [
            Column("version", Integer),
            Column("status", String),
            Column("run_id", String, index=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("body", JSONB, nullable=False),
            CheckConstraint("body->>'id' = id", name=f"{name}_body_id"),
        ]
    )
    if name != "projects":
        columns.append(
            CheckConstraint("body->>'project_id' = project_id", name=f"{name}_body_project")
        )
    if name in ("baselines", "plans"):
        columns.extend(
            [
                UniqueConstraint("project_id", "version", name=f"{name}_version"),
                CheckConstraint(
                    "version > 0 AND (body->>'version')::int = version", name=f"{name}_body_version"
                ),
            ]
        )
    TABLES[model] = Table(name, metadata, *columns)


def database_url(*, test: bool = False) -> str:
    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    key = "MIS_TEST_DATABASE_URL" if test else "MIS_DATABASE_URL"
    value = config.get(key)
    if not value:
        raise RuntimeError(
            f"Configure {key} in .env; use an independent Neon test branch or Docker"
        )
    url = make_url(value)
    if url.drivername not in ("postgresql", "postgresql+psycopg"):
        raise ValueError("PostgreSQL with psycopg is required")
    if test and config.get("MIS_DATABASE_URL"):
        dev = make_url(config["MIS_DATABASE_URL"])

        def endpoint(item):
            return ((item.host or "").replace("-pooler", ""), item.port or 5432, item.database)

        if endpoint(url) == endpoint(dev):
            raise ValueError("test database must be independent of the development database")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def engine_for(*, test: bool = False):
    return create_engine(
        database_url(test=test),
        hide_parameters=True,
        connect_args={"connect_timeout": 15},
        pool_pre_ping=True,
    )
