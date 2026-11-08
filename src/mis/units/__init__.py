"""MIS unit boundary. Currency conversion requires explicit FX evidence elsewhere."""

from math import isfinite

import pint

_registry = pint.UnitRegistry()
_registry.define("CNY = [currency_cny]")
_registry.define("USD = [currency_usd]")
_registry.define("ratio = dimensionless")
_ALIASES = {"cm⁻¹": "1 / cm", "cm^-1": "1 / cm", "°C": "degC"}


def unit_name(unit: str) -> str:
    return _ALIASES.get(unit, unit)


def convert(value: float, source: str, target: str) -> float:
    """Convert compatible units, including absolute offset temperatures."""
    if not isfinite(value):
        raise ValueError("quantity must be finite")
    try:
        result = float(_registry.Quantity(value, unit_name(source)).to(unit_name(target)).magnitude)
    except (pint.PintError, TypeError, ValueError) as exc:
        raise ValueError(f"incompatible or invalid units: {source} -> {target}") from exc
    if not isfinite(result):
        raise ValueError("conversion result must be finite")
    return result


def validate_unit(unit: str) -> str:
    convert(1, unit, unit)
    return unit
