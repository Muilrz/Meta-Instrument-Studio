"""Transactional service API. Caller owns commit/rollback; methods never commit."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from mis.ids import new_id
from mis.project_service.db import TABLES
from mis.schemas.artifacts import AgentArtifact
from mis.schemas.base import Model, now
from mis.schemas.evidence import Evidence
from mis.schemas.plan import InstrumentPlan
from mis.schemas.project import InstrumentProject
from mis.schemas.questions import UserCorrection, UserQuestion
from mis.schemas.requirements import RequirementBaseline, RequirementItem
from mis.schemas.status import Status, StatusChange
from mis.schemas.tasks import AgentTaskBrief
from mis.schemas.testing import TestResult

Record = TypeVar("Record", bound=Model)


class ProjectService:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def table(model):
        return TABLES[model]

    def get(self, model: type[Record], identifier: str) -> Record:
        table = self.table(model)
        body = self.session.scalar(select(table.c.body).where(table.c.id == identifier))
        if body is None:
            raise KeyError(f"{model.__name__} not found: {identifier}")
        return model.model_validate(body)

    def list(self, model: type[Record], project_id: str | None = None) -> list[Record]:
        table = self.table(model)
        query = select(table.c.body).order_by(table.c.id)
        if project_id is not None:
            column = table.c.id if model is InstrumentProject else table.c.project_id
            query = query.where(column == project_id)
        return [model.model_validate(body) for body in self.session.scalars(query)]

    def _project_lock(self, project_id):
        table = self.table(InstrumentProject)
        body = self.session.scalar(
            select(table.c.body).where(table.c.id == project_id).with_for_update()
        )
        if body is None:
            raise KeyError("project not found")
        return InstrumentProject.model_validate(body)

    def _scoped(self, model, identifier, project_id):
        record = self.get(model, identifier)
        if record.project_id != project_id:
            raise ValueError("cross-project reference rejected")
        return record

    def baseline(self, project_id: str, version: int) -> RequirementBaseline:
        table = self.table(RequirementBaseline)
        body = self.session.scalar(
            select(table.c.body).where(table.c.project_id == project_id, table.c.version == version)
        )
        if body is None:
            raise KeyError("baseline version not found")
        return RequirementBaseline.model_validate(body)

    def plan(self, project_id: str, version: int) -> InstrumentPlan:
        table = self.table(InstrumentPlan)
        body = self.session.scalar(
            select(table.c.body).where(table.c.project_id == project_id, table.c.version == version)
        )
        if body is None:
            raise KeyError("plan version not found")
        return InstrumentPlan.model_validate(body)

    def _evidence(self, value, project_id):
        for eid in value.evidence_ids:
            self._scoped(Evidence, eid, project_id)

    def _validate_references(self, record):
        project_id = record.project_id
        if isinstance(record, AgentTaskBrief):
            baseline = self.baseline(project_id, record.baseline_version)
            items = {item.key: item for item in baseline.items}
            if not set(record.requirement_refs) <= items.keys():
                raise ValueError("brief requirement does not exist in its baseline")
            for param in record.specified_params:
                if items.get(param.requirement_key) != param.target:
                    raise ValueError("specified parameter differs from baseline requirement")
        elif isinstance(record, AgentArtifact):
            brief = self._scoped(AgentTaskBrief, record.brief_id, project_id)
            baseline = self.baseline(project_id, brief.baseline_version)
            if not set(record.requirement_refs) <= {item.key for item in baseline.items}:
                raise ValueError("artifact requirement does not exist")
            for claim in record.claims:
                self._evidence(claim.value, project_id)
            for candidate in record.candidates:
                metrics = {
                    c.metric
                    for c in record.claims
                    if c.subject == candidate.subject and c.claim_id in candidate.claim_ids
                }
                if any(p.target.metric not in metrics for p in brief.specified_params):
                    raise ValueError("candidate must report every specified parameter or Unknown")
        elif isinstance(record, InstrumentPlan):
            baseline = self.baseline(project_id, record.baseline_version)
            if set(record.check_summary) != {item.key for item in baseline.items}:
                raise ValueError("plan check_summary must cover every requirement")
            artifacts = {
                aid: self._scoped(AgentArtifact, aid, project_id) for aid in record.artifact_ids
            }
            for entry in (*record.bom, *record.modules, *record.rationale):
                for ref in entry.claim_refs:
                    if ref.artifact_id not in artifacts:
                        raise ValueError("plan claim must belong to a listed artifact")
                    claim = next(
                        (
                            c
                            for c in artifacts[ref.artifact_id].claims
                            if c.claim_id == ref.claim_id
                        ),
                        None,
                    )
                    if claim is None or (
                        hasattr(entry, "subject") and claim.subject != entry.subject
                    ):
                        raise ValueError("plan claim or BOM subject mismatch")
        elif isinstance(record, UserQuestion):
            if record.brief_id:
                self._scoped(AgentTaskBrief, record.brief_id, project_id)
            if record.answer_evidence_id:
                ev = self._scoped(Evidence, record.answer_evidence_id, project_id)
                if ev.source_type != "user_decision":
                    raise ValueError("answer requires user_decision Evidence")
        elif isinstance(record, UserCorrection):
            artifact = self._scoped(AgentArtifact, record.artifact_id, project_id)
            claim = next((c for c in artifact.claims if c.claim_id == record.claim_id), None)
            if claim is None or claim.value != record.original_value:
                raise ValueError("correction must identify the original claim value")
            ev = self._scoped(Evidence, record.evidence_id, project_id)
            if ev.source_type != "user_decision":
                raise ValueError("correction requires user_decision Evidence")
            self._evidence(record.corrected_value, project_id)
        elif isinstance(record, TestResult):
            plan = self.plan(project_id, record.plan_version)
            baseline = self.baseline(project_id, plan.baseline_version)
            if record.requirement_key not in {i.key for i in baseline.items}:
                raise ValueError("test result requirement not in plan baseline")
            self._evidence(record, project_id)
            self._evidence(record.measured, project_id)

    @staticmethod
    def _row(record):
        provenance = getattr(record, "produced_by", None) or getattr(record, "retrieved_by", None)
        row = dict(
            id=record.id,
            version=getattr(record, "version", None),
            status=getattr(record, "status", None),
            run_id=provenance.run_id if provenance else getattr(record, "run_id", None),
            created_at=getattr(record, "created_at", None)
            or getattr(record, "retrieved_at", None)
            or now(),
            body=record.model_dump(mode="json"),
        )
        if not isinstance(record, InstrumentProject):
            row["project_id"] = record.project_id
        return row

    def add(self, record: Record) -> Record:
        record = type(record).model_validate_json(record.model_dump_json())
        table = self.table(type(record))
        existing = self.session.scalar(select(table.c.body).where(table.c.id == record.id))
        if existing is not None:
            if existing != record.model_dump(mode="json"):
                raise ValueError("record ID exists with different content")
            return type(record).model_validate(existing)
        project = None
        if not isinstance(record, InstrumentProject):
            project = self._project_lock(record.project_id)
            self._validate_references(record)
        pointer = None
        if isinstance(record, RequirementBaseline):
            pointer = "current_baseline_version"
        elif isinstance(record, InstrumentPlan):
            pointer = "current_plan_version"
        if pointer and record.version != (getattr(project, pointer) or 0) + 1:
            raise ValueError("versions must be appended consecutively")
        self.session.execute(table.insert().values(**self._row(record)))
        if pointer:
            updated = project.model_copy(update={pointer: record.version})
            self._replace_mutable(updated)
        return record

    def _replace_mutable(self, record):
        table = self.table(type(record))
        # Preserve indexed timestamps; only a controlled body/status change is allowed.
        self.session.execute(
            table.update()
            .where(table.c.id == record.id)
            .values(body=record.model_dump(mode="json"), status=getattr(record, "status", None))
        )
        return record

    def revise_baseline(
        self, project_id: str, *, items: Sequence[RequirementItem], change_note: str
    ) -> RequirementBaseline:
        project = self._project_lock(project_id)
        version = (project.current_baseline_version or 0) + 1
        budget_item = next((i for i in items if i.metric == "project.bom_total"), None)
        from mis.schemas.values import Quantity

        budget = Quantity(value=budget_item.upper, unit=budget_item.unit) if budget_item else None
        return self.add(
            RequirementBaseline(
                project_id=project_id,
                version=version,
                items=tuple(items),
                budget=budget,
                change_note=change_note,
            )
        )

    def revise_plan(self, plan: InstrumentPlan, **changes) -> InstrumentPlan:
        project = self._project_lock(plan.project_id)
        if {"id", "version", "project_id"} & changes.keys():
            raise ValueError("plan identity is service-managed")
        data = {
            **plan.model_dump(),
            **changes,
            "id": new_id("pln"),
            "version": (project.current_plan_version or 0) + 1,
            "status": "draft",
            "status_history": (),
        }
        return self.add(InstrumentPlan.model_validate(data))

    def set_status(self, model, identifier: str, status: Status, *, reason: str, trigger_id: str):
        if model not in (AgentTaskBrief, AgentArtifact, InstrumentPlan):
            raise ValueError("record does not support status changes")
        table = self.table(model)
        self.session.execute(select(table.c.id).where(table.c.id == identifier).with_for_update())
        record = self.get(model, identifier)
        if record.status == status:
            return record
        if record.status == "stale":
            raise ValueError("stale record requires a replacement, not reactivation")
        history = (
            *record.status_history,
            StatusChange(status=status, reason=reason, trigger_id=trigger_id),
        )
        return self._replace_mutable(
            record.model_copy(update={"status": status, "status_history": history})
        )

    def delete_project(self, project_id: str):
        self._project_lock(project_id)
        if any(self.list(model, project_id) for model in TABLES if model is not InstrumentProject):
            raise ValueError("only an empty project can be deleted")
        table = self.table(InstrumentProject)
        self.session.execute(table.delete().where(table.c.id == project_id))

    def by_run(self, run_id: str) -> list[Model]:
        records = []
        for model, table in TABLES.items():
            records.extend(
                model.model_validate(body)
                for body in self.session.scalars(
                    select(table.c.body).where(table.c.run_id == run_id).order_by(table.c.id)
                )
            )
        return records
