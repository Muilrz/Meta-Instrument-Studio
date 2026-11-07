from datetime import date

import pytest

from mis.rules.compare import RamanContext, compare
from mis.rules.evaluate import budget_total, evaluate
from mis.schemas.evidence import Evidence, FxRate
from mis.schemas.provenance import RunRef
from mis.schemas.requirements import RequirementBaseline, RequirementItem
from mis.schemas.values import Known, Quantity, QuantityRange, Unknown


def known(value, unit=None):
    if unit:
        value = Quantity(value=value, unit=unit)
    return Known(value=value, evidence_ids=("evd_manual",))


def requirement(key, comparator, unit=None, lower=None, upper=None, allowed=(), priority="must"):
    return RequirementItem(
        key=key,
        name=key,
        metric="test.metric",
        comparator=comparator,
        unit=unit,
        lower=lower,
        upper=upper,
        allowed=allowed,
        priority=priority,
        verification="manual",
    )


@pytest.mark.parametrize(
    "req,value,verdict",
    [
        (requirement("power", "min", "mW", lower=450), known(0.35, "W"), "fail"),
        (requirement("power", "min", "mW", lower=450), known(450, "mW"), "pass"),
        (requirement("width", "max", "nm", upper=0.1), known(0.08, "nm"), "pass"),
        (requirement("width", "max", "nm", upper=0.1), known(2, "nm"), "fail"),
        (requirement("lambda", "range", "nm", lower=784.5, upper=785.5), known(785, "nm"), "pass"),
        (
            requirement("lambda", "range", "nm", lower=784.5, upper=785.5),
            known(QuantityRange(lower=782, upper=788, unit="nm")),
            "fail",
        ),
        (
            requirement("time", "covers", "ms", lower=10, upper=10000),
            known(QuantityRange(lower=0.001, upper=60, unit="s")),
            "pass",
        ),
        (requirement("connector", "enum", allowed=("SMA905", "FC/PC")), known("SMA905"), "pass"),
        (requirement("connector", "enum", allowed=("SMA905",)), known("FC/PC"), "fail"),
        (
            requirement("cooling", "max", "degC", upper=-10),
            Unknown(reason="not reported"),
            "unknown",
        ),
    ],
)
def test_five_comparators_and_unknown(req, value, verdict):
    assert compare(req, value).verdict == verdict


def test_raman_cp05_cp06_and_missing_context():
    context = RamanContext(excitation_nm=785, shift_range_cm1=(200, 2000))
    resolution = requirement("R03", "max", "cm^-1", upper=8).model_copy(
        update={"metric": "spectrometer.resolution"}
    )
    assert compare(resolution, known(0.6, "nm"), context=context).verdict == "fail"
    assert compare(resolution, known(0.6, "nm")).verdict == "unknown"
    coverage = requirement("R02", "covers", "cm^-1", lower=200, upper=2000).model_copy(
        update={"metric": "spectrometer.raman_shift_coverage"}
    )
    value = known(QuantityRange(lower=790, upper=1000, unit="nm"))
    assert compare(coverage, value, context=context).verdict == "pass"


def test_three_value_precedence_and_should(records):
    baseline = RequirementBaseline(
        project_id=records[0].id,
        version=1,
        change_note="initial",
        items=(
            requirement("must", "min", "mW", lower=450),
            requirement("should", "max", "degC", upper=-10, priority="should"),
        ),
    )
    assert evaluate(baseline, {"must": known(500, "mW")}).verdict == "pass"
    assert evaluate(baseline, {}).verdict == "unknown"
    assert evaluate(baseline, {"must": known(300, "mW")}).verdict == "fail"


def test_budget_cp10_cp11_and_evidence(records):
    fx = Evidence(
        project_id=records[0].id,
        source_type="fx_rate",
        locator="manifest.yaml",
        excerpt="USD_CNY: 7.10",
        page_or_anchor="fx",
        source_version="0.1.0",
        retrieved_by=RunRef(run_id="manual", actor="user"),
        fx_rate=FxRate(source_currency="USD", rate=7.1, as_of=date(2026, 11, 5)),
    )
    req = requirement("R11", "max", "CNY", upper=60000)
    over = budget_total((known(9800, "USD"),), fx)
    assert over.value.value == 69580
    assert compare(req, over).verdict == "fail"
    total = budget_total((known(18000, "CNY"), known(4200, "USD"), known(7500, "CNY")), fx)
    assert total.value.value == 55320
    assert fx.id in total.evidence_ids
    assert compare(req, total).verdict == "pass"
    assert isinstance(budget_total((known(4200, "USD"),)), Unknown)
    assert isinstance(budget_total((Unknown(reason="no quote"),)), Unknown)


def test_invalid_shape_or_dimension_never_passes():
    assert (
        compare(
            requirement("time", "covers", "ms", lower=10, upper=10000), known(1000, "ms")
        ).verdict
        == "unknown"
    )
    with pytest.raises(ValueError):
        compare(requirement("power", "min", "mW", lower=450), known(1, "nm"))


def test_raman_combination_all_requirements_and_spec_c_unknown(records):
    from mis.fixtures import load_requirements

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
        for row in load_requirements()
    )
    baseline = RequirementBaseline(
        project_id=records[0].id, version=1, items=items, change_note="rule test from baseline CSV"
    )
    facts = {
        "R01": known(QuantityRange(lower=784.7, upper=785.3, unit="nm")),
        "R02": known(QuantityRange(lower=790, upper=1000, unit="nm")),
        "R03": known(6, "cm^-1"),
        "R04": known(500, "mW"),
        "R05": known(800, "ratio"),
        "R06": known(QuantityRange(lower=1, upper=60000, unit="ms")),
        "R07": known(-15, "degC"),
        "R08": known(0.08, "nm"),
        "R09": (known("SMA905"), known("SMA905"), known("SMA905")),
        "R10": (known("Windows+Python"), known("Windows+C")),
        "R11": known(55320, "CNY"),
    }
    context = RamanContext(excitation_nm=785, shift_range_cm1=(200, 2000))
    assert evaluate(baseline, facts, context=context).verdict == "pass"
    spec_c = {
        **facts,
        "R02": known(QuantityRange(lower=792, upper=950, unit="nm")),
        "R03": known(7, "cm^-1"),
        "R05": Unknown(reason="no comparable SNR"),
        "R06": known(QuantityRange(lower=10, upper=10000, unit="ms")),
        "R07": Unknown(reason="cooling temperature absent"),
        "R11": known(51500, "CNY"),
    }
    result = evaluate(baseline, spec_c, context=context)
    assert result.verdict == "unknown"
    assert result.should_checks[0].verdict == "unknown"
    assert next(c for c in result.checks if c.requirement_key == "R05").verdict == "unknown"
    # A hard failure dominates both an unknown must item and an unknown should item.
    assert (
        evaluate(baseline, {**spec_c, "R04": known(0.35, "W")}, context=context).verdict == "fail"
    )
    mixed = {**facts, "R09": (known("SMA905"), known("FC/PC"))}
    assert evaluate(baseline, mixed, context=context).verdict == "fail"
