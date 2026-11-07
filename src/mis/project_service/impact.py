from mis.project_service.repository import ProjectService
from mis.schemas.artifacts import AgentArtifact
from mis.schemas.impact import ImpactReport
from mis.schemas.plan import InstrumentPlan
from mis.schemas.tasks import AgentTaskBrief


def analyze(
    service: ProjectService, project_id: str, from_version: int, to_version: int
) -> ImpactReport:
    if to_version <= from_version:
        raise ValueError("impact must compare a newer baseline")
    old = service.baseline(project_id, from_version)
    new = service.baseline(project_id, to_version)
    before, after = ({item.key: item for item in baseline.items} for baseline in (old, new))
    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    briefs = {
        b.id
        for b in service.list(AgentTaskBrief, project_id)
        if b.baseline_version <= from_version and changed.intersection(b.requirement_refs)
    }
    brief_versions = {b.id: b.baseline_version for b in service.list(AgentTaskBrief, project_id)}
    artifacts = {
        a.id
        for a in service.list(AgentArtifact, project_id)
        if a.brief_id in briefs
        or (brief_versions[a.brief_id] <= from_version and changed.intersection(a.requirement_refs))
    }
    plans = {
        p.id
        for p in service.list(InstrumentPlan, project_id)
        if artifacts.intersection(p.artifact_ids)
    }
    return ImpactReport(
        project_id=project_id,
        from_version=from_version,
        to_version=to_version,
        changed_keys=tuple(sorted(changed)),
        brief_ids=tuple(sorted(briefs)),
        artifact_ids=tuple(sorted(artifacts)),
        plan_ids=tuple(sorted(plans)),
    )


def apply_impact(service: ProjectService, report: ImpactReport):
    project = service._project_lock(report.project_id)
    if (
        project.current_baseline_version != report.to_version
        or analyze(service, report.project_id, report.from_version, report.to_version) != report
    ):
        raise ValueError("impact report is outdated or changed; analyze again")
    trigger_id = service.baseline(report.project_id, report.to_version).id
    for model, identifiers in (
        (AgentTaskBrief, report.brief_ids),
        (AgentArtifact, report.artifact_ids),
        (InstrumentPlan, report.plan_ids),
    ):
        for identifier in identifiers:
            service.set_status(
                model, identifier, "stale", reason=report.reason, trigger_id=trigger_id
            )


def invalidate_artifact(service: ProjectService, artifact_id: str, *, reason: str, trigger_id: str):
    artifact = service.get(AgentArtifact, artifact_id)
    service._project_lock(artifact.project_id)
    service.set_status(AgentArtifact, artifact_id, "stale", reason=reason, trigger_id=trigger_id)
    for plan in service.list(InstrumentPlan, artifact.project_id):
        if artifact_id in plan.artifact_ids:
            service.set_status(
                InstrumentPlan, plan.id, "stale", reason=reason, trigger_id=trigger_id
            )
