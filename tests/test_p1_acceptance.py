from mis.fixtures import baseline_dir, load_checkpoints
from mis.ids import new_id
from mis.project_service.impact import analyze, apply_impact
from mis.project_service.repository import ProjectService
from mis.rules.compare import RamanContext, compare
from mis.rules.evaluate import budget_total
from mis.schemas.artifacts import AgentArtifact, Claim
from mis.schemas.evidence import Evidence
from mis.schemas.plan import InstrumentPlan
from mis.schemas.questions import UserQuestion
from mis.schemas.values import Known, Unknown
from tests.raman_example import build_example, make_plan


def test_manual_raman_answers_traceability_and_user_decisions(db_session):
    service = ProjectService(db_session)
    example = build_example(service)
    items = {item.key: item for item in example.baseline.items}
    checkpoints = {cp["id"]: cp for cp in load_checkpoints()}
    context = RamanContext(excitation_nm=785, shift_range_cm1=(200, 2000))
    metric_checks = {
        "CP02": ("LAS-A", "R08"),
        "CP03": ("LAS-B", "R04"),
        "CP04": ("LAS-C", "R08"),
        "CP05": ("SPEC-B", "R03"),
        "CP06": ("SPEC-A", "R02"),
        "CP07": ("SPEC-C", "R07"),
        "CP08": ("SPEC-C", "R05"),
    }
    verdicts = {"include": "pass", "exclude": "fail", "unknown": "unknown"}
    for cp, (part, key) in metric_checks.items():
        value = example.value(part, items[key].metric)
        assert (
            compare(items[key], value, context=context).verdict
            == verdicts[checkpoints[cp]["expected"]]
        )
    price = example.value("SPEC-D", "procurement.unit_price")
    assert compare(items["R11"], budget_total((price,), example.fx)).verdict == "fail"
    assert isinstance(example.value("SPEC-C", "procurement.lead_time"), Unknown)  # CP09
    plan, evaluation = make_plan(service, example, ("LAS-A", "SPEC-A", "PRB-A"))
    assert evaluation.verdict == "pass"
    assert plan.check_summary["R11"] == "pass"  # CP11
    trace = service.trace_plan(plan.id)
    assert trace
    for link in trace:
        assert link.evidence
        for evidence in link.evidence:
            assert evidence.excerpt in (baseline_dir() / evidence.locator).read_text(
                encoding="utf-8"
            )
    assert example.fx.id in {e.id for link in trace for e in link.evidence}
    for cid in ("CP01", "CP12", "CP13"):
        for expected in checkpoints[cid]["evidence"]:
            assert any(
                e.locator == expected["file"] and expected["quote"] in e.excerpt
                for link in trace
                for e in link.evidence
            )
    assert {(ref.artifact_id, ref.claim_id) for entry in plan.bom for ref in entry.claim_refs} <= {
        (link.artifact_id, link.claim.claim_id) for link in trace
    }
    # Every hand-authored claim, including rejected candidates, points at a real source excerpt.
    evidence_by_id = {e.id: e for e in service.list(Evidence, example.project_id)}
    for artifact in example.artifacts.values():
        for claim in artifact.claims:
            for eid in claim.evidence_ids:
                evidence = evidence_by_id[eid]
                assert evidence.excerpt in (baseline_dir() / evidence.locator).read_text(
                    encoding="utf-8"
                )
    alternate, evaluation = make_plan(service, example, ("LAS-A", "SPEC-C", "PRB-A"))
    assert evaluation.verdict == "unknown"
    question = service.add(
        UserQuestion(
            project_id=example.project_id,
            run_id=example.run.run_id,
            question="Which SDK?",
            context="user preference",
        )
    )
    answer = service.answer_question(question.id, answer="Prefer Python", run=example.run)
    assert service.answer_question(question.id, answer="Prefer Python", run=example.run) == answer
    answer_ev = service.get(Evidence, answer.answer_evidence_id)
    assert answer_ev.source_type == "user_decision"
    claim = Claim(
        statement="user preference",
        subject="user",
        metric="preference.sdk",
        value=Known(value="Python", evidence_ids=(answer_ev.id,)),
    )
    preference = example.artifacts["SPEC-A"].model_copy(
        update={"id": new_id("art"), "candidates": (), "claims": (claim,)}
    )
    service.add(preference)
    original = example.artifacts["SPEC-C"]
    target = next(c for c in original.claims if c.metric == "spectrometer.detector_temperature")
    correction = service.correct_claim(
        original.id,
        target.claim_id,
        corrected_value=Unknown(reason="user confirms no cooling temperature specification"),
        reason="manual correction",
        corrected_by="owner",
        run=example.run,
    )
    assert correction.original_value == target.value
    assert isinstance(correction.corrected_value, Unknown)
    assert service.get(Evidence, correction.evidence_id).source_type == "user_decision"
    assert service.get(AgentArtifact, original.id).claims == original.claims
    assert service.get(AgentArtifact, original.id).status == "stale"
    assert service.get(InstrumentPlan, alternate.id).status == "stale"
    assert service.get(InstrumentPlan, plan.id).status == "draft"
    by_run = service.by_run(example.run.run_id)
    assert {plan.id, alternate.id, answer_ev.id, correction.evidence_id} <= {r.id for r in by_run}
    # Acceptance 3 uses the imported eleven-item Raman baseline, not only a small rule fixture.
    v2_items = tuple(
        item.model_copy(update={"lower": 300}) if item.key == "R04" else item
        for item in example.baseline.items
    )
    v2 = service.revise_baseline(
        example.project_id, items=v2_items, change_note="R04: 450 mW to 300 mW"
    )
    impact = analyze(service, example.project_id, 1, 2)
    lasers = tuple(example.artifacts[p] for p in ("LAS-A", "LAS-B", "LAS-C"))
    assert set(impact.artifact_ids) == {a.id for a in lasers}
    assert set(impact.brief_ids) == {a.brief_id for a in lasers}
    assert set(impact.plan_ids) == {plan.id, alternate.id}
    apply_impact(service, impact)
    assert service.baseline(example.project_id, 1) == example.baseline
    assert service.baseline(example.project_id, 2) == v2
    retained = service.plan(example.project_id, 1)
    assert retained.status == "stale"
    assert retained.model_dump(exclude={"status", "status_history"}) == plan.model_dump(
        exclude={"status", "status_history"}
    )
    assert compare(items["R04"], example.value("LAS-B", "laser.max_power")).verdict == "fail"
    changed = next(item for item in v2.items if item.key == "R04")
    assert compare(changed, example.value("LAS-B", "laser.max_power")).verdict == "pass"
