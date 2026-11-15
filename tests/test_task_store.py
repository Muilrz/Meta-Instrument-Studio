"""No database or DDL: scripted PostgreSQL driver and statement contracts.

Real PostgreSQL and cross-process acceptance are separate opt-in tests.
"""

import json
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict, replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from mis.adapters.deerflow import DeerFlowError, RunBinding, RunResult, ThreadBinding
from mis.adapters.task_bridge import TaskRunLink
from mis.adapters.task_store import (
    CallBudget,
    CommandIntent,
    MappingConflict,
    MappingPending,
    PostgresTaskRunLinkStore,
    _intent_values,
    _record,
    _thread_values,
    run_commands,
    thread_bindings,
)


@pytest.fixture
def intent():
    return CommandIntent(
        ThreadBinding("p", "task", "mt", "dt"),
        "mr",
        "cmd-1",
        "a" * 64,
        1,
        "lab",
        "b" * 64,
        "c" * 64,
        CallBudget(7, 98192, 1024, Decimal("0.08")),
    )


def row_for(intent, state="intent", upstream=None, status=None):
    return {
        **_intent_values(intent),
        "state": state,
        "upstream_run_id": upstream,
        "runtime_status": status,
    }


class ScriptedConnection:
    """Expected rows only, not a substitute relational database implementation."""

    dialect = postgresql.dialect()

    def __init__(self, *responses):
        self.responses = list(responses)
        self.statements = []
        self.savepoints = []

    def execute(self, statement):
        self.statements.append(statement)
        assert self.responses, "unexpected statement"
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(one_or_none=lambda: result),
            scalar_one_or_none=lambda: result,
        )

    @contextmanager
    def begin_nested(self):
        self.savepoints.append("begin")
        try:
            yield
        except Exception:
            self.savepoints.append("rollback")
            raise
        else:
            self.savepoints.append("release")


def test_begin_persists_snapshot_and_identical_replay_is_not_send_permission(intent):
    for inserted, created in [("mr", True), (None, False)]:
        connection = ScriptedConnection(
            None, _thread_values(intent.thread), inserted, row_for(intent)
        )
        receipt = PostgresTaskRunLinkStore(connection).begin_intent(intent)
        assert receipt.created is created
        assert receipt.command.intent == intent
        assert receipt.command.state == "intent"
        sql = [str(s.compile(dialect=connection.dialect)) for s in connection.statements]
        assert "ON CONFLICT DO NOTHING" in sql[0] and "ON CONFLICT DO NOTHING" in sql[2]
        assert "FOR UPDATE" in sql[1] and "FOR UPDATE" in sql[3]
        assert connection.savepoints == ["begin", "release"]
        assert not connection.responses


@pytest.mark.parametrize("changed", ["task", "upstream"])
def test_thread_conflict_rolls_back_partial_intent(intent, changed):
    existing = _thread_values(intent.thread)
    existing["task_id" if changed == "task" else "upstream_thread_id"] = "other"
    connection = ScriptedConnection(None, existing)
    with pytest.raises(MappingConflict, match="thread"):
        PostgresTaskRunLinkStore(connection).begin_intent(intent)
    assert connection.savepoints == ["begin", "rollback"]
    assert len(connection.statements) == 2


def test_reused_key_for_other_run_is_rejected(intent):
    connection = ScriptedConnection(None, _thread_values(intent.thread), None, None)
    with pytest.raises(MappingConflict, match="idempotency"):
        PostgresTaskRunLinkStore(connection).begin_intent(intent)
    assert connection.savepoints[-1] == "rollback"


def test_same_run_changed_intent_cannot_replace_hash_or_budget(intent):
    connection = ScriptedConnection(
        None,
        _thread_values(intent.thread),
        None,
        row_for(replace(intent, config_sha256="d" * 64)),
    )
    with pytest.raises(MappingConflict, match="intent conflict"):
        PostgresTaskRunLinkStore(connection).begin_intent(intent)
    assert connection.savepoints[-1] == "rollback"


def test_uncertain_is_persisted_without_resend_or_implicit_binding(intent):
    connection = ScriptedConnection(row_for(intent), None, row_for(intent, "uncertain"))
    record = PostgresTaskRunLinkStore(connection).mark_uncertain("p", "mr")
    assert record.state == "uncertain"
    with pytest.raises(MappingPending):
        _ = record.link
    statement = connection.statements[1].compile(dialect=connection.dialect)
    assert statement.params["state"] == "uncertain"
    assert all("INSERT" not in str(s) for s in connection.statements)


def test_late_timeout_does_not_regress_acknowledged_run(intent):
    connection = ScriptedConnection(
        row_for(intent, "completed", "dr", "success"),
        row_for(intent, "completed", "dr", "success"),
    )
    assert PostgresTaskRunLinkStore(connection).mark_uncertain("p", "mr").state == "completed"
    assert all(not s.is_update for s in connection.statements)


def test_bind_requires_existing_intent_and_preserves_mapping(intent):
    link = TaskRunLink(RunBinding(intent.thread, "mr", "dr"), "a" * 64, 1, "lab")
    connection = ScriptedConnection(None)
    with pytest.raises(KeyError):
        PostgresTaskRunLinkStore(connection).put(link)
    connection = ScriptedConnection(
        row_for(intent, "uncertain"), None, row_for(intent, "bound", "dr")
    )
    assert PostgresTaskRunLinkStore(connection).put(link) == link
    assert connection.savepoints == ["begin", "release"]


def test_upstream_unique_violation_is_safe_and_savepoint_is_rolled_back(intent):
    link = TaskRunLink(RunBinding(intent.thread, "mr", "dr"), "a" * 64, 1, "lab")
    connection = ScriptedConnection(
        row_for(intent), IntegrityError("private-sql", {}, Exception("private database detail"))
    )
    with pytest.raises(MappingConflict) as error:
        PostgresTaskRunLinkStore(connection).put(link)
    assert "private" not in str(error.value)
    assert connection.savepoints == ["begin", "rollback"]


@pytest.mark.parametrize("changed", ["thread", "hash", "upstream"])
def test_bind_conflicts_never_update_existing_record(intent, changed):
    binding = RunBinding(intent.thread, "mr", "dr")
    link = TaskRunLink(binding, "a" * 64, 1, "lab")
    existing = row_for(intent, "bound", "dr")
    if changed == "thread":
        link = replace(
            link, binding=replace(binding, thread=replace(intent.thread, project_id="q"))
        )
    elif changed == "hash":
        link = replace(link, brief_sha256="f" * 64)
    else:
        link = replace(link, binding=replace(binding, deerflow_run_id="another"))
    connection = ScriptedConnection(existing)
    with pytest.raises(MappingConflict):
        PostgresTaskRunLinkStore(connection).put(link)
    assert len(connection.statements) == 1


def result_for(intent, *, status="success"):
    binding = RunBinding(intent.thread, intent.run_id, "dr")
    return RunResult(
        binding,
        "completed" if status == "success" else "running",
        {
            "thread_id": "dt",
            "run_id": "dr",
            "status": status,
            "metadata": {
                "mis_project_id": "p",
                "mis_task_id": "task",
                "mis_thread_id": "mt",
                "mis_run_id": "mr",
            },
        },
    )


def test_reconcile_verifies_metadata_before_binding(intent):
    result = result_for(intent)
    result.raw["metadata"]["mis_project_id"] = "other"
    connection = ScriptedConnection(row_for(intent, "uncertain"))
    with pytest.raises(DeerFlowError, match="mapping"):
        PostgresTaskRunLinkStore(connection).reconcile("p", "mr", result)
    assert len(connection.statements) == 1


def test_successful_query_reconciles_uncertain_without_resending(intent):
    connection = ScriptedConnection(
        row_for(intent, "uncertain"),
        row_for(intent, "uncertain"),
        None,
        row_for(intent, "bound", "dr"),
        None,
        row_for(intent, "completed", "dr", "success"),
    )
    record = PostgresTaskRunLinkStore(connection).reconcile("p", "mr", result_for(intent))
    assert record.state == "completed"
    assert record.link.binding.deerflow_run_id == "dr"
    assert all("INSERT" not in str(s) for s in connection.statements)


def test_terminal_reconciliation_cannot_regress(intent):
    connection = ScriptedConnection(
        row_for(intent, "completed", "dr", "success"),
        row_for(intent, "completed", "dr", "success"),
        row_for(intent, "completed", "dr", "success"),
    )
    with pytest.raises(MappingConflict, match="terminal"):
        PostgresTaskRunLinkStore(connection).reconcile(
            "p", "mr", result_for(intent, status="running")
        )
    assert all(not s.is_update for s in connection.statements)


def test_postgresql_schema_has_required_uniqueness_and_scope_constraints():
    ddl = str(CreateTable(run_commands).compile(dialect=postgresql.dialect()))
    assert "PRIMARY KEY (project_id, run_id)" in ddl
    assert "UNIQUE (project_id, idempotency_key)" in ddl
    assert "UNIQUE (upstream_run_id)" in ddl
    assert "FOREIGN KEY(project_id, task_id, thread_id, upstream_thread_id)" in ddl
    thread_ddl = str(CreateTable(thread_bindings).compile(dialect=postgresql.dialect()))
    assert "UNIQUE (upstream_thread_id)" in thread_ddl


def test_row_reload_in_another_process_preserves_intent_and_link(intent):
    # JSON is a simulated DB row. This proves codec/process independence only,
    # not PostgreSQL persistence, transactions, or server uniqueness behavior.
    body = json.dumps(row_for(intent, "bound", "dr"))
    code = (
        "import json,sys; from dataclasses import asdict; "
        "from mis.adapters.task_store import _record; "
        "print(json.dumps(asdict(_record(json.load(sys.stdin)).link)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], input=body, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == asdict(_record(json.loads(body)).link)


@pytest.mark.parametrize(
    "change",
    [
        {"baseline_version": 0},
        {"brief_sha256": "invalid"},
        {"specialist": "other"},
        {"idempotency_key": " "},
        {"idempotency_key": "bad\nheader"},
    ],
)
def test_invalid_intent_rejected_before_database(intent, change):
    with pytest.raises(ValueError):
        replace(intent, **change)


@pytest.mark.parametrize("reservation", [Decimal("NaN"), Decimal("Infinity"), Decimal("0")])
def test_invalid_budget_rejected(reservation):
    with pytest.raises(ValueError):
        CallBudget(7, 1000, 1000, reservation)


def test_strictly_zero_budget_records_no_model_authorization():
    assert CallBudget(0, 0, 0, Decimal("0")).as_json() == {
        "max_calls": 0,
        "max_input_tokens": 0,
        "max_output_tokens": 0,
        "reserved_usd": "0",
    }
    with pytest.raises(ValueError):
        CallBudget(0, 1000, 1000, Decimal("0"))
