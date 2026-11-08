import pytest

from mis.ids import new_id
from mis.project_service.impact import analyze, apply_impact
from mis.project_service.repository import ProjectService
from mis.schemas.artifacts import AgentArtifact
from mis.schemas.plan import BomEntry, ClaimRef, PlanConclusion
from mis.schemas.requirements import RequirementItem
from mis.schemas.tasks import AgentTaskBrief


@pytest.mark.parametrize("changed_key", ["R04", "R11"])
def test_exact_impact_and_preserved_versions(db_session, records, changed_key):
    service = ProjectService(db_session)
    project, old, base_brief, ev, base_art, base_plan = records[:6]
    budget = RequirementItem(
        key="R11",
        name="budget",
        metric="project.bom_total",
        comparator="max",
        upper=60000,
        unit="CNY",
        verification="sum",
    )
    old = old.model_copy(update={"items": (*old.items, budget)})
    for record in (project, old, ev):
        service.add(record)
    objects = []
    for key in ("R04", "R11"):
        brief = base_brief.model_copy(update={"id": new_id("brf"), "requirement_refs": (key,)})
        artifact = base_art.model_copy(
            update={"id": new_id("art"), "brief_id": brief.id, "requirement_refs": (key,)}
        )
        ref = ClaimRef(artifact_id=artifact.id, claim_id=artifact.claims[0].claim_id)
        plan = base_plan.model_copy(
            update={
                "id": new_id("pln"),
                "version": len(objects) + 1,
                "artifact_ids": (artifact.id,),
                "bom": (BomEntry(subject="LAS-A", claim_refs=(ref,)),),
                "rationale": (PlanConclusion(statement="test dependency", claim_refs=(ref,)),),
                "check_summary": {"R04": "pass", "R11": "pass"},
            }
        )
        for record in (brief, artifact, plan):
            service.add(record)
        objects.append((brief, artifact, plan))
    direct = service.add(
        base_art.model_copy(
            update={"id": new_id("art"), "brief_id": objects[1][0].id, "requirement_refs": ("R04",)}
        )
    )
    direct_ref = ClaimRef(artifact_id=direct.id, claim_id=direct.claims[0].claim_id)
    direct_plan = service.revise_plan(
        objects[0][2],
        artifact_ids=(direct.id,),
        bom=(BomEntry(subject="LAS-A", claim_refs=(direct_ref,)),),
        rationale=(PlanConclusion(statement="direct dependency", claim_refs=(direct_ref,)),),
    )
    items = tuple(
        item.model_copy(update={"lower": 300})
        if item.key == "R04" and changed_key == "R04"
        else item.model_copy(update={"upper": 50000})
        if item.key == "R11" and changed_key == "R11"
        else item
        for item in old.items
    )
    new = service.revise_baseline(project.id, items=items, change_note=f"change {changed_key}")
    report = analyze(service, project.id, 1, 2)
    impacted = objects[0 if changed_key == "R04" else 1]
    untouched = objects[1 if changed_key == "R04" else 0]
    assert report.changed_keys == (changed_key,)
    assert report.brief_ids == (impacted[0].id,)
    assert set(report.artifact_ids) == {impacted[1].id, direct.id}
    assert set(report.plan_ids) == {impacted[2].id, direct_plan.id}
    with pytest.raises(ValueError):
        apply_impact(service, report.model_copy(update={"brief_ids": ()}))
    assert service.get(AgentArtifact, impacted[1].id).status == "draft"
    apply_impact(service, report)
    apply_impact(service, report)  # replay does not duplicate status history
    for record in impacted:
        saved = service.get(type(record), record.id)
        assert saved.status == "stale"
        assert saved.status_history[-1].reason == f"需求 v1 → v2，{changed_key} 变更"
        assert saved.model_dump(exclude={"status", "status_history"}) == record.model_dump(
            exclude={"status", "status_history"}
        )
        assert len(saved.status_history) == 1
    for record in untouched:
        assert service.get(type(record), record.id) == record
    assert service.baseline(project.id, 1) == old
    assert service.baseline(project.id, 2) == new
    assert service.plan(project.id, impacted[2].version).id == impacted[2].id
    if changed_key == "R11":
        v3_items = tuple(
            i.model_copy(update={"lower": 300}) if i.key == "R04" else i for i in new.items
        )
        service.revise_baseline(
            project.id, items=v3_items, change_note="change retained dependency"
        )
        next_report = analyze(service, project.id, 2, 3)
        assert objects[0][0].id in next_report.brief_ids
        apply_impact(service, next_report)
        assert service.get(AgentTaskBrief, objects[0][0].id).status == "stale"
