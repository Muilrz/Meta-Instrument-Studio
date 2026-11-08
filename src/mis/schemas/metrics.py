"""Known Raman metrics constrain dimensions without coupling to an agent runtime."""

from mis.units import convert

METRIC_UNITS = {
    "laser.center_wavelength": "nm",
    "laser.max_power": "mW",
    "laser.linewidth": "nm",
    "spectrometer.raman_shift_coverage": "cm^-1",
    "spectrometer.wavelength_coverage": "nm",
    "spectrometer.resolution": "cm^-1",
    "spectrometer.integration_time": "ms",
    "spectrometer.detector_temperature": "degC",
    "system.snr_cyclohexane_802": "ratio",
    "project.bom_total": "CNY",
    "procurement.unit_price": None,
}
ENUM_METRICS = {"optics.fiber_connector", "software.sdk"}


def check_dimension(metric: str, unit: str, *, domain_resolution: bool = False):
    expected = METRIC_UNITS.get(metric)
    if domain_resolution and metric == "spectrometer.resolution":
        try:
            convert(1, unit, "nm")
            return
        except ValueError:
            pass
    if expected:
        convert(1, unit, expected)
