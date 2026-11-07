import pytest

from mis.units import convert
from mis.units.raman import resolution_nm_to_cm1, shift_cm1, wavelength_at_shift_nm


@pytest.mark.parametrize(
    "value,source,target,expected",
    [
        (0.35, "W", "mW", 350),
        (1, "µm", "nm", 1000),
        (1, "s", "ms", 1000),
        (8, "cm⁻¹", "cm^-1", 8),
        (-10, "°C", "K", 263.15),
        (60000, "CNY", "CNY", 60000),
        (500, "ratio", "dimensionless", 500),
    ],
)
def test_convert(value, source, target, expected):
    assert convert(value, source, target) == pytest.approx(expected)


def test_invalid_conversion():
    with pytest.raises(ValueError):
        convert(1, "nm", "mW")
    with pytest.raises(ValueError):
        convert(1, "USD", "CNY")


def test_raman_reference_and_roundtrip():
    wavelength = wavelength_at_shift_nm(785, 200)
    assert shift_cm1(785, wavelength) == pytest.approx(200)
    assert resolution_nm_to_cm1(0.6, wavelength) == pytest.approx(9.43, abs=0.01)
    assert shift_cm1(785, 790) < 200
    assert shift_cm1(785, 1000) > 2000


@pytest.mark.parametrize("excitation,shift", [(0, 200), (785, 20000), (float("nan"), 1)])
def test_invalid_raman_domain(excitation, shift):
    with pytest.raises(ValueError):
        wavelength_at_shift_nm(excitation, shift)
