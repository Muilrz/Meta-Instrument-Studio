"""Logical backup/restore through Project Service. Does not read or write runtime."""

from mis.project_service.db import TABLES
from mis.project_service.repository import ProjectService
from mis.schemas.backup import ProjectBackup


def dump_data(service: ProjectService) -> ProjectBackup:
    # All service writers lock the project before mutation. Export holds this barrier
    # until the caller ends the transaction, then locks the business tables for a snapshot.
    service.session.connection().exec_driver_sql("LOCK TABLE mis.projects IN EXCLUSIVE MODE")
    tables = ", ".join(f"mis.{table.name}" for table in TABLES.values())
    service.session.connection().exec_driver_sql(f"LOCK TABLE {tables} IN SHARE MODE")
    return ProjectBackup(
        **{table.name: tuple(service.list(model)) for model, table in TABLES.items()}
    )


def restore_data(service: ProjectService, data: str | ProjectBackup) -> ProjectBackup:
    # Revalidate even model instances (model_copy does not itself validate updates).
    snapshot = ProjectBackup.model_validate_json(
        data if isinstance(data, str) else data.model_dump_json()
    )
    with service.session.begin_nested():
        # Serializes restores to an empty destination, including concurrent service writes.
        service.session.connection().exec_driver_sql("LOCK TABLE mis.projects IN EXCLUSIVE MODE")
        if any(service.list(model) for model in TABLES):
            raise ValueError("restore requires an empty business database")
        for project in snapshot.projects:
            service._restore_record(
                project.model_copy(
                    update={"current_baseline_version": None, "current_plan_version": None}
                )
            )
        order = (
            "baselines",
            "evidence",
            "briefs",
            "artifacts",
            "plans",
            "questions",
            "corrections",
            "test_results",
        )
        for name in order:
            records = getattr(snapshot, name)
            if name in ("baselines", "plans"):
                records = sorted(records, key=lambda r: (r.project_id, r.version))
            for record in records:
                service._restore_record(record)
        restored = dump_data(service)
        if restored != snapshot:
            raise ValueError("backup pointers, state history or records are inconsistent")
    return restored
