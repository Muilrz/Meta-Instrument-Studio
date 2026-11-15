"""Opt-in real PostgreSQL ledger acceptance; never creates tables or runs DDL.

Requires the separately approved, installed schema and a P2-target connection.
Test rows are deliberately retained as audit fixtures in the two new tables.
"""

import json
import os
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url

from mis.adapters.deerflow import RunBinding, RunResult, ThreadBinding
from mis.adapters.task_bridge import TaskRunLink
from mis.adapters.task_store import (
    CallBudget,
    CommandIntent,
    MappingConflict,
    PostgresTaskRunLinkStore,
    thread_bindings,
)
from mis.project_service.db import ROOT

pytestmark = pytest.mark.skipif(
    os.environ.get("MIS_INTEGRATION_TEST_APPROVED") != "1"
    or not os.environ.get("MIS_INTEGRATION_TEST_DATABASE_URL"),
    reason="approved P2 ledger schema/credential required; tests never install it",
)


def _reload_in_process(project_id, run_id):
    code = """
import json,os,sys
from sqlalchemy import create_engine
from mis.adapters.task_store import PostgresTaskRunLinkStore
try:
    engine=create_engine(os.environ['MIS_INTEGRATION_TEST_DATABASE_URL'],hide_parameters=True)
    with engine.begin() as conn:
        if os.environ.get('MIS_INTEGRATION_TEST_SET_ROLE') == 'mis_app':
            conn.exec_driver_sql('SET LOCAL ROLE mis_app')
        record=PostgresTaskRunLinkStore(conn).get_command(sys.argv[1],sys.argv[2])
        print(json.dumps({'state':record.state,'upstream_run_id':record.upstream_run_id,
                          'request_sha256':record.intent.request_sha256}))
    engine.dispose()
except Exception as exc:
    print(json.dumps({'error_type':type(exc).__name__}))
    raise SystemExit(1)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, project_id, run_id], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stdout
    return json.loads(completed.stdout)


def test_postgres_cross_process_crash_window_and_uniqueness():
    settings = dotenv_values(ROOT / ".env")
    url = make_url(os.environ["MIS_INTEGRATION_TEST_DATABASE_URL"])
    target = make_url(settings["DEER_FLOW_TEST_DATABASE_URL"])

    def endpoint(item):
        return ((item.host or "").replace("-pooler", ""), item.port or 5432, item.database)

    assert endpoint(url) == endpoint(target), "only the approved P2 endpoint is allowed"
    for key in ("MIS_DATABASE_URL", "MIS_TEST_DATABASE_URL"):
        assert endpoint(url) != endpoint(make_url(settings[key])), "business targets forbidden"
    engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 15})
    prefix = "p2-ledger-" + uuid4().hex
    thread = ThreadBinding(prefix, "task", "mt", prefix + "-dt")
    intent = CommandIntent(
        thread,
        "mr",
        prefix + "-key",
        "a" * 64,
        1,
        "lab",
        "b" * 64,
        "c" * 64,
        CallBudget(7, 98192, 1024, Decimal("0.08")),
    )

    def app_role(connection):
        if os.environ.get("MIS_INTEGRATION_TEST_SET_ROLE") == "mis_app":
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
        assert connection.exec_driver_sql("SELECT current_user").scalar_one() == "mis_app"

    try:
        with engine.begin() as connection:
            app_role(connection)
            receipt = PostgresTaskRunLinkStore(connection).begin_intent(intent)
            assert receipt.created
        # Simulates process loss after committed intent, before an HTTP ack is
        # bound. The new process reads committed PostgreSQL, not a Python cache.
        assert _reload_in_process(prefix, "mr")["state"] == "intent"
        with engine.begin() as connection:
            app_role(connection)
            store = PostgresTaskRunLinkStore(connection)
            assert not store.begin_intent(intent).created
            assert store.mark_uncertain(prefix, "mr").state == "uncertain"
            for changed in (
                replace(intent, request_sha256="d" * 64),
                replace(intent, run_id="another"),
                replace(intent, thread=replace(thread, task_id="another")),
            ):
                with pytest.raises(MappingConflict):
                    store.begin_intent(changed)
        assert _reload_in_process(prefix, "mr")["state"] == "uncertain"
        binding = RunBinding(thread, "mr", prefix + "-dr")
        result = RunResult(
            binding,
            "completed",
            {
                "thread_id": thread.deerflow_thread_id,
                "run_id": binding.deerflow_run_id,
                "status": "success",
                "metadata": {
                    "mis_project_id": prefix,
                    "mis_task_id": "task",
                    "mis_thread_id": "mt",
                    "mis_run_id": "mr",
                },
            },
        )
        with engine.begin() as connection:
            app_role(connection)
            store = PostgresTaskRunLinkStore(connection)
            assert store.reconcile(prefix, "mr", result).state == "completed"
            assert store.put(TaskRunLink(binding, "a" * 64, 1, "lab")) == store.get(prefix, "mr")
            other = replace(intent, thread=replace(thread, project_id=prefix + "-other"))
            with pytest.raises(MappingConflict):
                store.begin_intent(other)
            assert (
                connection.execute(
                    select(thread_bindings).where(thread_bindings.c.project_id == prefix + "-other")
                ).first()
                is None
            )
            second = replace(
                intent,
                run_id="second",
                idempotency_key=prefix + "-second",
                thread=replace(thread, thread_id="second", deerflow_thread_id=prefix + "-dt2"),
            )
            assert store.begin_intent(second).created
            collision = TaskRunLink(
                RunBinding(second.thread, second.run_id, binding.deerflow_run_id),
                "a" * 64,
                1,
                "lab",
            )
            with pytest.raises(MappingConflict):
                store.put(collision)
            assert store.get_command(prefix, "second").state == "intent"
        final = _reload_in_process(prefix, "mr")
        assert final == {
            "state": "completed",
            "upstream_run_id": binding.deerflow_run_id,
            "request_sha256": "c" * 64,
        }
    finally:
        engine.dispose()
