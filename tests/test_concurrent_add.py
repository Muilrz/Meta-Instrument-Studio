from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from mis.ids import new_id
from mis.project_service.db import metadata
from mis.project_service.repository import ProjectService


@pytest.fixture(scope="module")
def concurrent_engine(db_engine):
    # True commits are needed across connections. Isolate them from all business data.
    schema = f"p1_race_{new_id('tmp').split('_')[1].lower()}"
    with db_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        translated = connection.execution_options(schema_translate_map={"mis": schema})
        metadata.create_all(translated, checkfirst=False)
    try:
        yield db_engine.execution_options(schema_translate_map={"mis": schema})
    finally:
        with db_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


@pytest.mark.parametrize("record_index", [0, 3], ids=["project", "evidence"])
@pytest.mark.parametrize("same_content", [True, False], ids=["identical", "conflicting"])
def test_concurrent_add_is_idempotent_or_reports_content_conflict(
    concurrent_engine, records, record_index, same_content
):
    record = records[record_index]
    if record_index:
        with Session(concurrent_engine) as session, session.begin():
            ProjectService(session).add(records[0])
    field = "name" if record_index == 0 else "excerpt"
    second = record if same_content else record.model_copy(update={field: "different content"})
    barrier = Barrier(2)
    seen = local()

    def after_read(connection, cursor, statement, parameters, context, executemany):
        if (
            not getattr(seen, "done", False)
            and statement.lstrip().startswith("SELECT")
            and "body" in statement
            and record.id in parameters.values()
        ):
            seen.done = True
            barrier.wait(timeout=30)

    def write(value):
        with Session(concurrent_engine) as session, session.begin():
            try:
                return "ok", ProjectService(session).add(value)
            except ValueError:
                assert session.scalar(select(1)) == 1  # collision must not poison the transaction
                return "conflict", None

    event.listen(concurrent_engine, "after_cursor_execute", after_read)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, value) for value in (record, second)]
            results = [future.result(timeout=60) for future in futures]
    finally:
        event.remove(concurrent_engine, "after_cursor_execute", after_read)
    if same_content:
        assert results == [("ok", record), ("ok", record)]
    else:
        assert sorted(status for status, _ in results) == ["conflict", "ok"]
    with Session(concurrent_engine) as session:
        saved = ProjectService(session).get(type(record), record.id)
        assert saved in (record, second)
