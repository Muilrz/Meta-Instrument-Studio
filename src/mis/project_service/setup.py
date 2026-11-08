"""Initialize roles/schemas and migrate the selected database, without logging credentials."""

import argparse

from alembic import command
from alembic.config import Config

from mis.project_service.db import ROOT, engine_for


def initialize(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql((ROOT / "db/init.sql").read_text(encoding="utf-8"))
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="Use independent test database")
    args = parser.parse_args()
    try:
        engine = engine_for(test=args.test)
        initialize(engine)
        engine.dispose()
    except Exception as exc:
        print(f"Database initialization failed ({type(exc).__name__}); details suppressed.")
        raise SystemExit(1) from None
    print("Database initialized and migrated to head.")
