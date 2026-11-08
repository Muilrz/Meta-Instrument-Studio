import pytest
from pydantic import TypeAdapter, ValidationError

from mis.schemas.values import Known, Quantity, QuantityRange, SpecValue, Unknown


def test_value_contract_roundtrip_and_schema():
    adapter = TypeAdapter(SpecValue)
    values = [
        Known(value=Quantity(value=0.35, unit="W"), evidence_ids=("evd_source",)),
        Unknown(reason="not reported"),
    ]
    for value in values:
        assert adapter.validate_json(adapter.dump_json(value)) == value
    assert adapter.json_schema()["discriminator"]["propertyName"] == "kind"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Known(value="SMA905", evidence_ids=()),
        lambda: Unknown(reason=" "),
        lambda: Quantity(value=float("nan"), unit="nm"),
        lambda: Quantity(value=1, unit="not_a_unit"),
        lambda: QuantityRange(lower=2, upper=1, unit="nm"),
        lambda: Quantity(value=1, unit="nm").to("mW"),
    ],
)
def test_invalid_values_rejected(factory):
    with pytest.raises((ValueError, ValidationError)):
        factory()
