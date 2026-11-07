from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import Field

from mis.rules.compare import CheckResult, RamanContext, Verdict, compare
from mis.schemas.base import Model
from mis.schemas.evidence import Evidence
from mis.schemas.requirements import RequirementBaseline
from mis.schemas.values import Known, Quantity, SpecValue, Unknown


def aggregate(verdicts: Sequence[Verdict]) -> Verdict:
    if "fail" in verdicts:
        return "fail"
    if not verdicts or "unknown" in verdicts:
        return "unknown"
    return "pass"


class Evaluation(Model):
    verdict: Verdict
    checks: tuple[CheckResult, ...]
    should_checks: tuple[CheckResult, ...] = ()
    rule_version: str = Field(default="1", pattern="^1$")


def evaluate(
    baseline: RequirementBaseline,
    values: Mapping[str, SpecValue | Sequence[SpecValue]],
    *,
    context: RamanContext | None = None,
) -> Evaluation:
    """Compare caller-supplied facts per requirement key; absent keys stay unknown.

    The caller supplies one value per applicable component (not only the preferred
    component). Multiple connector values must also agree. Subject selection and
    evidence-reference existence belong to Project Service, not the numeric engine.
    """
    extra = set(values) - {item.key for item in baseline.items}
    if extra:
        raise ValueError(f"unknown requirement keys: {sorted(extra)}")
    must, should = [], []
    for item in baseline.items:
        candidates = values.get(item.key, Unknown(reason="no reported value"))
        if isinstance(candidates, (Known, Unknown)):
            candidates = (candidates,)
        checks = [compare(item, value, context=context) for value in candidates]
        verdict = aggregate([check.verdict for check in checks])
        reason = "; ".join(check.reason for check in checks) or "no reported value"
        if item.metric == "optics.fiber_connector":
            connectors = {v.value for v in candidates if isinstance(v, Known)}
            if len(connectors) > 1:
                verdict, reason = "fail", "component fiber connectors do not match"
        check = CheckResult(
            requirement_key=item.key,
            verdict=verdict,
            reason=reason,
            evidence_ids=tuple(
                dict.fromkeys(eid for check in checks for eid in check.evidence_ids)
            ),
        )
        (must if item.priority == "must" else should).append(check)
    return Evaluation(
        verdict=aggregate([c.verdict for c in must]),
        checks=tuple(must),
        should_checks=tuple(should),
    )


def budget_total(prices: Sequence[SpecValue], fx_evidence: Evidence | None = None) -> SpecValue:
    """Sum explicit single-unit prices; USD requires a structured FX Evidence."""
    total = Decimal(0)
    evidence_ids = []
    if not prices:
        return Unknown(reason="no BOM prices")
    for price in prices:
        evidence_ids.extend(price.evidence_ids)
        if isinstance(price, Unknown):
            return Unknown(reason="BOM contains unknown price", evidence_ids=tuple(evidence_ids))
        if not isinstance(price.value, Quantity):
            raise ValueError("price requires a scalar money quantity")
        if price.value.value < 0:
            raise ValueError("price cannot be negative")
        try:
            amount = Decimal(str(price.value.to("CNY").value))
        except ValueError:
            usd = Decimal(str(price.value.to("USD").value))
            if fx_evidence is None:
                return Unknown(
                    reason="USD/CNY FX evidence required", evidence_ids=tuple(evidence_ids)
                )
            if fx_evidence.source_type != "fx_rate" or fx_evidence.fx_rate is None:
                raise ValueError("structured FX evidence required") from None
            amount = usd * Decimal(str(fx_evidence.fx_rate.rate))
            evidence_ids.append(fx_evidence.id)
        total += amount
    return Known(
        value=Quantity(value=float(total), unit="CNY"),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
    )
