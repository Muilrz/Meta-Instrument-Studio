from alembic import context
from sqlalchemy import text

from mis.project_service.db import engine_for, metadata


def run(connection):
    connection.execute(text("SET ROLE mis_admin"))
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table_schema="mis",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    run(provided)
else:
    engine = engine_for(test=context.get_x_argument(as_dictionary=True).get("test") == "true")
    with engine.begin() as connection:
        run(connection)
    engine.dispose()
