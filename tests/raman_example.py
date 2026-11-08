"""Hand-authored ideal specialist output. Never reads checkpoints to generate answers."""

import json
from pathlib import Path

from mis.fixtures import baseline_dir
from mis.importers.raman_baseline import import_raman_baseline
from mis.project_service.repository import ProjectService
from mis.rules.compare import RamanContext
from mis.rules.evaluate import budget_total, evaluate
from mis.schemas.artifacts import AgentArtifact, Candidate, Claim
from mis.schemas.base import Model
from mis.schemas.evidence import Evidence, Quote
from mis.schemas.plan import BomEntry, ClaimRef, InstrumentPlan, PlanConclusion
from mis.schemas.provenance import RunRef
from mis.schemas.requirements import RequirementBaseline
from mis.schemas.tasks import AgentTaskBrief, SpecifiedParam
from mis.schemas.values import Known, Quantity, QuantityRange, Unknown
from mis.units.raman import shift_cm1


class Example(Model):
    project_id: str
    baseline: RequirementBaseline
    fx: Evidence
    run: RunRef
    artifacts: dict[str, AgentArtifact]
    notes: AgentArtifact

    def value(self, subject, metric):
        return next(c.value for c in self.artifacts[subject].claims if c.metric == metric)


def build_example(service: ProjectService) -> Example:
    run = RunRef(run_id="raman-manual-p1", actor="user", skill_versions={"raman_fixture": "1"})
    imported = import_raman_baseline(service, run=run)
    project_id = imported.project.id
    items = {item.key: item for item in imported.baseline.items}
    parts = json.loads(
        (Path(__file__).parent / "data/raman_components.json").read_text(encoding="utf-8")
    )
    artifacts = {}
    for part, data in parts.items():
        brief = service.add(
            AgentTaskBrief(
                project_id=project_id,
                baseline_version=1,
                requirement_refs=tuple(data["requirements"]),
                specialist="procurement",
                goal=f"Characterize {part}",
                specified_params=tuple(
                    SpecifiedParam(name=items[k].metric, requirement_key=k, target=items[k])
                    for k in data["requirements"]
                ),
            )
        )
        claims = []
        for fact in data["facts"]:
            evidence = service.add(
                Evidence(
                    project_id=project_id,
                    source_type="document",
                    locator=f"component_pages/{part}.md",
                    excerpt=fact["excerpt"],
                    page_or_anchor=fact["metric"],
                    source_version="0.1.0",
                    retrieved_by=run,
                )
            )
            if "unknown" in fact:
                value = Unknown(reason=fact["unknown"], evidence_ids=(evidence.id,))
            else:
                raw = fact["value"]
                actual = (
                    (QuantityRange(**raw) if "lower" in raw else Quantity(**raw))
                    if isinstance(raw, dict)
                    else raw
                )
                value = Known(value=actual, evidence_ids=(evidence.id,))
            claims.append(
                Claim(
                    statement=f"{part}: {fact['metric']}",
                    subject=part,
                    metric=fact["metric"],
                    value=value,
                )
            )
            if fact["metric"] == "spectrometer.wavelength_coverage":
                raw = value.value.to("nm")
                coverage = QuantityRange(
                    lower=shift_cm1(785, raw.lower), upper=shift_cm1(785, raw.upper), unit="cm^-1"
                )
                claims.append(
                    Claim(
                        statement="Wavelength coverage converted at 785 nm",
                        subject=part,
                        metric="spectrometer.raman_shift_coverage",
                        value=Known(value=coverage, evidence_ids=(evidence.id,)),
                    )
                )
        quote_text = (baseline_dir() / "vendor_responses" / f"{part}.json").read_text(
            encoding="utf-8"
        )
        raw = json.loads(quote_text)
        quote = service.add(
            Evidence(
                project_id=project_id,
                source_type="vendor_api",
                locator=f"vendor_responses/{part}.json",
                excerpt=quote_text,
                page_or_anchor="quote",
                source_version="0.1.0",
                retrieved_at=raw["retrieved_at"],
                retrieved_by=run,
                quote=Quote(
                    currency=raw["currency"],
                    price_tiers=raw["price_tiers"],
                    region=raw["region"],
                    valid_until=raw["quote_valid_until"],
                    tax_included=raw["tax_included"],
                ),
            )
        )
        for metric, amount, unit in (
            ("procurement.unit_price", raw["price_tiers"][0]["unit_price"], raw["currency"]),
            ("procurement.stock", raw["stock"], "ratio"),
            ("procurement.lead_time", raw["lead_time_days"], "day"),
        ):
            value = (
                Unknown(reason="vendor did not report this field", evidence_ids=(quote.id,))
                if (amount is None)
                else Known(value=Quantity(value=amount, unit=unit), evidence_ids=(quote.id,))
            )
            claims.append(
                Claim(statement=f"{part}: {metric}", subject=part, metric=metric, value=value)
            )
        artifact = service.add(
            AgentArtifact(
                project_id=project_id,
                brief_id=brief.id,
                artifact_type="procurement",
                requirement_refs=brief.requirement_refs,
                claims=tuple(claims),
                candidates=(Candidate(subject=part, claim_ids=tuple(c.claim_id for c in claims)),),
                produced_by=run,
            )
        )
        artifacts[part] = artifact
    note_claims = []
    notes = json.loads(
        (Path(__file__).parent / "data/raman_notes.json").read_text(encoding="utf-8")
    )
    for note in notes:
        evidence_ids = []
        for source in note["evidence"]:
            ev = service.add(
                Evidence(
                    project_id=project_id,
                    source_type="document",
                    locator=source["file"],
                    excerpt=source["excerpt"],
                    page_or_anchor=note["metric"],
                    source_version="0.1.0",
                    retrieved_by=run,
                )
            )
            evidence_ids.append(ev.id)
        note_claims.append(
            Claim(
                statement=note["statement"],
                subject="system",
                metric=note["metric"],
                value=Known(value=note["value"], evidence_ids=tuple(evidence_ids)),
            )
        )
    note_brief = service.add(
        AgentTaskBrief(
            project_id=project_id,
            baseline_version=1,
            requirement_refs=("R01", "R05", "R11"),
            specialist="lab",
            goal="Record lab constraints",
        )
    )
    note_artifact = service.add(
        AgentArtifact(
            project_id=project_id,
            brief_id=note_brief.id,
            artifact_type="lab",
            requirement_refs=note_brief.requirement_refs,
            claims=tuple(note_claims),
            produced_by=run,
        )
    )
    return Example(
        project_id=project_id,
        baseline=imported.baseline,
        fx=imported.fx_evidence,
        run=run,
        artifacts=artifacts,
        notes=note_artifact,
    )


def make_plan(service: ProjectService, example: Example, subjects: tuple[str, ...]):
    selected = [example.artifacts[part] for part in subjects]
    total = budget_total(
        tuple(example.value(s, "procurement.unit_price") for s in subjects), example.fx
    )
    budget_brief = service.add(
        AgentTaskBrief(
            project_id=example.project_id,
            baseline_version=1,
            requirement_refs=("R11",),
            specialist="procurement",
            goal="Sum selected single-unit BOM",
        )
    )
    budget_claim = Claim(
        statement="BOM total with fixed FX", subject="BOM", metric="project.bom_total", value=total
    )
    budget_artifact = service.add(
        AgentArtifact(
            project_id=example.project_id,
            brief_id=budget_brief.id,
            requirement_refs=("R11",),
            artifact_type="budget",
            claims=(budget_claim,),
            produced_by=example.run.model_copy(update={"actor": "rule_engine"}),
        )
    )
    facts = {
        item.key: tuple(
            c.value
            for a in (*selected, budget_artifact)
            for c in a.claims
            if c.metric == item.metric
        )
        for item in example.baseline.items
    }
    evaluation = evaluate(
        example.baseline,
        facts,
        context=RamanContext(excitation_nm=785, shift_range_cm1=(200, 2000)),
    )
    bom = tuple(
        BomEntry(
            subject=subject,
            claim_refs=tuple(
                ClaimRef(artifact_id=artifact.id, claim_id=claim.claim_id)
                for claim in artifact.claims
            ),
        )
        for subject, artifact in zip(subjects, selected, strict=True)
    )
    conclusions = tuple(
        PlanConclusion(statement=f"Use {entry.subject}", claim_refs=entry.claim_refs)
        for entry in bom
    )
    budget_ref = ClaimRef(artifact_id=budget_artifact.id, claim_id=budget_claim.claim_id)
    project = service._project_lock(example.project_id)
    plan = service.add(
        InstrumentPlan(
            project_id=example.project_id,
            version=(project.current_plan_version or 0) + 1,
            baseline_version=1,
            artifact_ids=tuple(a.id for a in (*selected, budget_artifact, example.notes)),
            bom=bom,
            modules=conclusions,
            rationale=(
                *conclusions,
                *(
                    PlanConclusion(
                        statement=c.statement,
                        claim_refs=(ClaimRef(artifact_id=example.notes.id, claim_id=c.claim_id),),
                    )
                    for c in example.notes.claims
                ),
                PlanConclusion(statement="BOM budget", claim_refs=(budget_ref,)),
            ),
            risks=("Unknown requirements require verification",)
            if evaluation.verdict == "unknown"
            else (),
            stage2_tasks=("Verify the optical assembly against the baseline",),
            check_summary={
                c.requirement_key: c.verdict
                for c in (*evaluation.checks, *evaluation.should_checks)
            },
            produced_by=example.run,
        )
    )
    return plan, evaluation
