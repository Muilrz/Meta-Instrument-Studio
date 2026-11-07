"""Raman conversions; nm resolution uses the baseline's differential FWHM formula."""

from math import isfinite


def _positive(value: float) -> float:
    if not isfinite(value) or value <= 0:
        raise ValueError("wavelength and resolution must be positive and finite")
    return value


def shift_cm1(excitation_nm: float, wavelength_nm: float) -> float:
    return 1e7 / _positive(excitation_nm) - 1e7 / _positive(wavelength_nm)


def wavelength_at_shift_nm(excitation_nm: float, shift_cm1: float) -> float:
    if not isfinite(shift_cm1):
        raise ValueError("shift must be finite")
    return 1e7 / _positive(1e7 / _positive(excitation_nm) - shift_cm1)


def resolution_nm_to_cm1(resolution_nm: float, at_wavelength_nm: float) -> float:
    return _positive(resolution_nm) / _positive(at_wavelength_nm) ** 2 * 1e7
