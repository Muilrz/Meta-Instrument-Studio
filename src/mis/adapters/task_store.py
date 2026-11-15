"""MIS-owned PostgreSQL command ledger. No DDL, network calls, or auto retries.

Schema installation requires separate approval. The caller owns commit/rollback;
commit a newly prepared intent before sending any Gateway request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from mis.adapters.deerflow import DeerFlowClient, RunBinding, RunResult, ThreadBinding
from mis.adapters.task_bridge import TaskRunLink

metadata = MetaData(schema="mis_integration")
thread_bindings = Table(
    "thread_bindings",
    metadata,
    Column("project_id", String, primary_key=True),
    Column("task_id", String, nullable=False),
    Column("thread_id", String, primary_key=True),
    Column("upstream_thread_id", String, nullable=False, unique=True),
    UniqueConstraint("project_id", "task_id", "thread_id", "upstream_thread_id"),
)
run_commands = Table(
    "run_commands",
    metadata,
    Column("project_id", String, primary_key=True),
    Column("run_id", String, primary_key=True),
    Column("task_id", String, nullable=False),
    Column("thread_id", String, nullable=False),
    Column("upstream_thread_id", String, nullable=False),
    Column("idempotency_key", String, nullable=False),
    Column("brief_sha256", String, nullable=False),
    Column("baseline_version", Integer, nullable=False),
    Column("specialist", String, nullable=False),
    Column("config_sha256", String, nullable=False),
    Column("request_sha256", String, nullable=False),
    Column("budget", JSONB, nullable=False),
    Column("state", String, nullable=False),
    Column("upstream_run_id", String, unique=True),
    Column("runtime_status", String),
    UniqueConstraint("project_id", "idempotency_key"),
    ForeignKeyConstraint(
        ["project_id", "task_id", "thread_id", "upstream_thread_id"],
        [
            f"mis_integration.thread_bindings.{name}"
            for name in ("project_id", "task_id", "thread_id", "upstream_thread_id")
        ],
    ),
    CheckConstraint("brief_sha256 ~ '^[0-9a-f]{64}$'"),
    CheckConstraint("config_sha256 ~ '^[0-9a-f]{64}$'"),
    CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'"),
    CheckConstraint("baseline_version > 0"),
    CheckConstraint("specialist IN ('lab', 'research', 'procurement')"),
    CheckConstraint("jsonb_typeof(budget) = 'object'"),
    CheckConstraint("state IN ('intent','uncertain','bound','completed','failed','cancelled')"),
    CheckConstraint("state IN ('intent','uncertain') OR upstream_run_id IS NOT NULL"),
)


class MappingConflict(ValueError):
    """A stable identifier already owns a different command or scope."""


class MappingPending(LookupError):
    """No verified upstream Run has been bound yet; never resend implicitly."""


@dataclass(frozen=True)
class CallBudget:
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    reserved_usd: Decimal

    def __post_init__(self):
        for value in (self.max_calls, self.max_input_tokens, self.max_output_tokens):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("budget limits must be positive integers")
        if (
            not isinstance(self.reserved_usd, Decimal)
            or not self.reserved_usd.is_finite()
            or self.reserved_usd <= 0
        ):
            raise ValueError("budget requires a finite positive Decimal reservation")

    def as_json(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "reserved_usd": str(self.reserved_usd),
        }


@dataclass(frozen=True)
class CommandIntent:
    thread: ThreadBinding
    run_id: str
    idempotency_key: str
    brief_sha256: str
    baseline_version: int
    specialist: str
    config_sha256: str
    request_sha256: str
    budget: CallBudget

    def __post_init__(self):
        for value in (
            self.thread.project_id,
            self.thread.task_id,
            self.thread.thread_id,
            self.thread.deerflow_thread_id,
            self.run_id,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("mapping IDs must be nonempty strings")
        for value in (self.brief_sha256, self.config_sha256, self.request_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("intent hashes must be SHA-256 hex")
        if (
            not self.idempotency_key.strip()
            or len(self.idempotency_key) > 255
            or any(not 32 <= ord(c) <= 126 for c in self.idempotency_key)
        ):
            raise ValueError("intent key requires 1-255 printable ASCII characters")
        if (
            not isinstance(self.baseline_version, int)
            or isinstance(self.baseline_version, bool)
            or self.baseline_version < 1
            or self.specialist not in {"lab", "research", "procurement"}
            or not isinstance(self.budget, CallBudget)
        ):
            raise ValueError("invalid intent baseline, role, or budget")


@dataclass(frozen=True)
class CommandRecord:
    intent: CommandIntent
    state: str
    upstream_run_id: str | None = None
    runtime_status: str | None = None

    @property
    def link(self) -> TaskRunLink:
        if self.upstream_run_id is None:
            raise MappingPending("command needs authoritative upstream reconciliation")
        return TaskRunLink(
            RunBinding(self.intent.thread, self.intent.run_id, self.upstream_run_id),
            self.intent.brief_sha256,
            self.intent.baseline_version,
            self.intent.specialist,
        )


@dataclass(frozen=True)
class IntentReceipt:
    created: bool
    command: CommandRecord


def _thread_values(binding: ThreadBinding) -> dict[str, Any]:
    return {
        "project_id": binding.project_id,
        "task_id": binding.task_id,
        "thread_id": binding.thread_id,
        "upstream_thread_id": binding.deerflow_thread_id,
    }


def _intent_values(intent: CommandIntent) -> dict[str, Any]:
    return {
        **_thread_values(intent.thread),
        "run_id": intent.run_id,
        "idempotency_key": intent.idempotency_key,
        "brief_sha256": intent.brief_sha256,
        "baseline_version": intent.baseline_version,
        "specialist": intent.specialist,
        "config_sha256": intent.config_sha256,
        "request_sha256": intent.request_sha256,
        "budget": intent.budget.as_json(),
    }


def _record(row) -> CommandRecord:
    values = dict(row)
    thread = ThreadBinding(
        values["project_id"], values["task_id"], values["thread_id"], values["upstream_thread_id"]
    )
    budget = dict(values["budget"])
    budget["reserved_usd"] = Decimal(budget["reserved_usd"])
    intent = CommandIntent(
        thread,
        values["run_id"],
        values["idempotency_key"],
        values["brief_sha256"],
        values["baseline_version"],
        values["specialist"],
        values["config_sha256"],
        values["request_sha256"],
        CallBudget(**budget),
    )
    return CommandRecord(
        intent, values["state"], values["upstream_run_id"], values["runtime_status"]
    )


class PostgresTaskRunLinkStore:
    """All methods participate in the caller's transaction; none commit or run DDL."""

    def __init__(self, connection: Connection):
        if connection.dialect.name != "postgresql":
            raise ValueError("TaskRunLinkStore requires PostgreSQL")
        self.connection = connection

    @staticmethod
    def _key(project_id: str, run_id: str):
        return (run_commands.c.project_id == project_id) & (run_commands.c.run_id == run_id)

    def _read(self, project_id: str, run_id: str, *, lock: bool = False) -> CommandRecord:
        query = select(run_commands).where(self._key(project_id, run_id))
        if lock:
            query = query.with_for_update()
        row = self.connection.execute(query).mappings().one_or_none()
        if row is None:
            raise KeyError("command intent not found")
        return _record(row)

    def begin_intent(self, intent: CommandIntent) -> IntentReceipt:
        # An idempotency/thread conflict must not leave a partially inserted
        # thread if a caller catches the safe ValueError and commits its work.
        with self.connection.begin_nested():
            return self._begin_intent(intent)

    def _begin_intent(self, intent: CommandIntent) -> IntentReceipt:
        values = _thread_values(intent.thread)
        self.connection.execute(insert(thread_bindings).values(**values).on_conflict_do_nothing())
        row = (
            self.connection.execute(
                select(thread_bindings)
                .where(
                    (thread_bindings.c.project_id == intent.thread.project_id)
                    & (thread_bindings.c.thread_id == intent.thread.thread_id)
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None or dict(row) != values:
            raise MappingConflict("thread mapping conflict")
        inserted = self.connection.execute(
            insert(run_commands)
            .values(**_intent_values(intent), state="intent")
            .on_conflict_do_nothing()
            .returning(run_commands.c.run_id)
        ).scalar_one_or_none()
        try:
            record = self._read(intent.thread.project_id, intent.run_id, lock=True)
        except KeyError:
            raise MappingConflict("idempotency key belongs to another command") from None
        if record.intent != intent:
            raise MappingConflict("command intent conflict")
        return IntentReceipt(inserted is not None, record)

    def get_command(self, project_id: str, run_id: str) -> CommandRecord:
        return self._read(project_id, run_id)

    def get(self, project_id: str, run_id: str) -> TaskRunLink:
        return self.get_command(project_id, run_id).link

    def mark_uncertain(self, project_id: str, run_id: str) -> CommandRecord:
        record = self._read(project_id, run_id, lock=True)
        if record.state == "intent":
            self.connection.execute(
                update(run_commands).where(self._key(project_id, run_id)).values(state="uncertain")
            )
        return self._read(project_id, run_id)

    def put(self, link: TaskRunLink) -> TaskRunLink:
        project_id, run_id = link.binding.thread.project_id, link.binding.run_id
        record = self._read(project_id, run_id, lock=True)
        expected = TaskRunLink(
            link.binding,
            record.intent.brief_sha256,
            record.intent.baseline_version,
            record.intent.specialist,
        )
        if (
            record.intent.thread != link.binding.thread
            or expected != link
            or (
                record.upstream_run_id is not None
                and record.upstream_run_id != link.binding.deerflow_run_id
            )
            or not link.binding.deerflow_run_id.strip()
        ):
            raise MappingConflict("run binding conflict")
        if record.upstream_run_id is None:
            try:
                with self.connection.begin_nested():
                    self.connection.execute(
                        update(run_commands)
                        .where(self._key(project_id, run_id))
                        .values(state="bound", upstream_run_id=link.binding.deerflow_run_id)
                    )
            except IntegrityError:
                raise MappingConflict("upstream run already belongs to another command") from None
        return self._read(project_id, run_id).link

    def reconcile(self, project_id: str, run_id: str, result: RunResult) -> CommandRecord:
        record = self._read(project_id, run_id, lock=True)
        if result.binding.thread != record.intent.thread or result.binding.run_id != run_id:
            raise MappingConflict("reconciliation scope mismatch")
        checked = DeerFlowClient._result(result.binding, result.raw)
        if checked.status != result.status:
            raise MappingConflict("reconciliation status mismatch")
        link = TaskRunLink(
            result.binding,
            record.intent.brief_sha256,
            record.intent.baseline_version,
            record.intent.specialist,
        )
        self.put(link)
        state = result.status if result.status in {"completed", "failed", "cancelled"} else "bound"
        if record.state in {"completed", "failed", "cancelled"} and record.state != state:
            raise MappingConflict("terminal state cannot regress or change")
        self.connection.execute(
            update(run_commands)
            .where(self._key(project_id, run_id))
            .values(state=state, runtime_status=result.raw["status"])
        )
        return self._read(project_id, run_id)
