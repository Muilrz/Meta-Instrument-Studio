import csv
from pathlib import Path
from typing import Literal

import yaml

from mis.fixtures import baseline_dir
from mis.project_service.repository import ProjectService
from mis.schemas.base import Model
from mis.schemas.evidence import Evidence, FxRate
from mis.schemas.project import InstrumentProject
from mis.schemas.provenance import RunRef
from mis.schemas.requirements import RequirementBaseline, RequirementItem
from mis.schemas.values import Quantity


class BaselineImport(Model):
    project: InstrumentProject
    baseline: RequirementBaseline
    fx_evidence: Evidence


def import_raman_baseline(
    service: ProjectService,
    path: Path | None = None,
    *,
    kind: Literal["normal", "benchmark"] = "benchmark",
    run: RunRef | None = None,
) -> BaselineImport:
    path = path or baseline_dir()
    manifest_text = (path / "manifest.yaml").read_text(encoding="utf-8")
    manifest = yaml.safe_load(manifest_text)
    with (path / "requirements.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    items = tuple(
        RequirementItem(
            key=row["id"],
            name=row["名称"],
            metric=row["指标键"],
            comparator=row["比较方式"],
            lower=float(row["下限"]) if row["下限"] and row["比较方式"] != "enum" else None,
            upper=float(row["上限"]) if row["上限"] else None,
            allowed=tuple(row["下限"].split("|")) if row["比较方式"] == "enum" else (),
            unit=row["单位"] or None,
            priority=row["优先级"],
            verification=row["验收方法"],
        )
        for row in rows
    )
    budget_item = next(item for item in items if item.metric == "project.bom_total")
    run = run or RunRef(run_id=f"import-{manifest['name']}-{manifest['version']}", actor="user")
    with service.session.begin_nested():
        project = service.add(InstrumentProject(name=manifest["name"], kind=kind))
        baseline = service.add(
            RequirementBaseline(
                project_id=project.id,
                version=1,
                items=items,
                budget=Quantity(value=budget_item.upper, unit=budget_item.unit),
                change_note=f"Imported Raman package {manifest['version']}",
            )
        )
        fx = service.add(
            Evidence(
                project_id=project.id,
                source_type="fx_rate",
                locator="manifest.yaml",
                excerpt=manifest_text,
                page_or_anchor="fx",
                source_version=manifest["version"],
                retrieved_by=run,
                fx_rate=FxRate(
                    source_currency="USD",
                    rate=manifest["fx"]["USD_CNY"],
                    as_of=manifest["fx"]["as_of"],
                ),
            )
        )
        return BaselineImport(
            project=service.get(InstrumentProject, project.id), baseline=baseline, fx_evidence=fx
        )
