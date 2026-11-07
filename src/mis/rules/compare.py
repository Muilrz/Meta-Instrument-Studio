from typing import Literal

from pydantic import Field, model_validator

from mis.schemas.base import Model, Text
from mis.schemas.requirements import RequirementItem
from mis.schemas.values import Quantity, QuantityRange, SpecValue, Unknown
from mis.units.raman import resolution_nm_to_cm1, shift_cm1, wavelength_at_shift_nm

Verdict = Literal["pass", "fail", "unknown"]


class CheckResult(Model):
    requirement_key: Text
    verdict: Verdict
    reason: Text
    evidence_ids: tuple[Text, ...] = ()
    rule_version: Literal["1"] = "1"


class RamanContext(Model):
    excitation_nm: float = Field(gt=0)
    shift_range_cm1: tuple[float, float]
    evidence_ids: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def physical_domain(self):
        lo, hi = self.shift_range_cm1
        if lo > hi:
            raise ValueError("reversed Raman shift range")
        wavelength_at_shift_nm(self.excitation_nm, lo)
        wavelength_at_shift_nm(self.excitation_nm, hi)
        return self


def compare(
    requirement: RequirementItem, value: SpecValue, *, context: RamanContext | None = None
) -> CheckResult:
    """Inclusive limits. Missing information is unknown; invalid dimensions raise ValueError."""
    evidence_ids = value.evidence_ids

    def result(verdict: Verdict, reason: str):
        return CheckResult(
            requirement_key=requirement.key,
            verdict=verdict,
            reason=reason,
            evidence_ids=evidence_ids,
        )

    if isinstance(value, Unknown):
        return result("unknown", value.reason)
    actual = value.value
    if requirement.comparator == "enum":
        if not isinstance(actual, str):
            raise ValueError("enum requires a text value")
        return result("pass" if actual in requirement.allowed else "fail", "enum membership")
    if isinstance(actual, str):
        raise ValueError("numeric comparison requires quantity")
    try:
        actual = actual.to(requirement.unit)
    except ValueError:
        # Only these explicit domain conversions can bridge length and inverse length.
        if requirement.metric == "spectrometer.resolution" and isinstance(actual, Quantity):
            resolution_nm = actual.to("nm").value
            if context is None:
                return result("unknown", "Raman excitation and evaluation range required")
            actual = Quantity(
                value=max(
                    resolution_nm_to_cm1(
                        resolution_nm, wavelength_at_shift_nm(context.excitation_nm, shift)
                    )
                    for shift in context.shift_range_cm1
                ),
                unit="cm^-1",
            ).to(requirement.unit)
        elif requirement.metric == "spectrometer.raman_shift_coverage" and isinstance(
            actual, QuantityRange
        ):
            wavelengths = actual.to("nm")
            if context is None:
                return result("unknown", "Raman excitation required")
            actual = QuantityRange(
                lower=shift_cm1(context.excitation_nm, wavelengths.lower),
                upper=shift_cm1(context.excitation_nm, wavelengths.upper),
                unit="cm^-1",
            ).to(requirement.unit)
        else:
            raise
        evidence_ids = tuple(dict.fromkeys((*evidence_ids, *context.evidence_ids)))
    lo, hi = (
        (actual.lower, actual.upper)
        if isinstance(actual, QuantityRange)
        else (actual.value, actual.value)
    )
    match requirement.comparator:
        case "min":
            passed = lo >= requirement.lower
        case "max":
            passed = hi <= requirement.upper
        case "range":
            passed = lo >= requirement.lower and hi <= requirement.upper
        case "covers":
            if not isinstance(actual, QuantityRange):
                return result("unknown", "coverage requires a reported interval")
            passed = lo <= requirement.lower and hi >= requirement.upper
        case _:
            raise ValueError("unsupported comparator")
    return result("pass" if passed else "fail", f"{requirement.comparator}: inclusive bounds")
