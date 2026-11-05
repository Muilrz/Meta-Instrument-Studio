"""Integrity checks for the Raman baseline task package (fixtures/raman_baseline).

These tests guard the answer key itself: every checkpoint must point at evidence that
really exists, and every numeric verdict must be reproducible from the stated inputs.
"""

from __future__ import annotations

import json

import pytest

from mis.fixtures import baseline_dir, load_checkpoints, load_manifest, load_requirements

PKG = baseline_dir("raman_baseline")
MANIFEST = load_manifest()
CHECKPOINTS = load_checkpoints()
REQUIREMENTS = load_requirements()

REQUIREMENT_IDS = {r["id"] for r in REQUIREMENTS}
PART_IDS = {p.stem for p in (PKG / "component_pages").glob("*.md")}
LISTED_FILES = {f for group in MANIFEST["files"].values() for f in group}

# Multiplier to convert each unit into its group's base unit.
UNIT_SCALE = {"mW": 1.0, "W": 1000.0, "nm": 1.0, "µm": 1000.0, "ms": 1.0, "s": 1000.0}

# P0 acceptance: the package must exercise each of these traps at least once.
REQUIRED_CHECKPOINT_TYPES = {"must_unknown", "unit_trap", "budget", "must_exclude"}


def raman_shift_cm1(excitation_nm: float, wavelength_nm: float) -> float:
    return 1e7 / excitation_nm - 1e7 / wavelength_nm


def wavelength_at_shift_nm(excitation_nm: float, shift_cm1: float) -> float:
    return 1e7 / (1e7 / excitation_nm - shift_cm1)


# --- manifest ---------------------------------------------------------------


def test_manifest_lists_every_file_and_all_exist():
    on_disk = {
        p.relative_to(PKG).as_posix()
        for p in PKG.rglob("*")
        if p.is_file() and p.name != "manifest.yaml"
    }
    assert on_disk == LISTED_FILES


def test_manifest_has_version_and_fx():
    assert MANIFEST["version"]
    assert MANIFEST["fx"]["USD_CNY"] > 0


# --- requirements -----------------------------------------------------------


def test_requirement_ids_unique():
    ids = [r["id"] for r in REQUIREMENTS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("req", REQUIREMENTS, ids=lambda r: r["id"])
def test_requirement_row_well_formed(req):
    assert req["优先级"] in {"must", "should"}
    assert req["比较方式"] in {"min", "max", "range", "covers", "enum"}
    assert req["验收方法"].strip()
    if req["比较方式"] != "enum":
        assert req["单位"].strip()


# --- synthetic labelling ----------------------------------------------------


@pytest.mark.parametrize(
    "path", sorted(f for f in LISTED_FILES if f.endswith(".md") and "/" in f), ids=str
)
def test_material_is_labelled_synthetic(path):
    assert "合成资料" in (PKG / path).read_text(encoding="utf-8")


# --- vendor responses -------------------------------------------------------

QUOTE_KEYS = {
    "part_id",
    "vendor",
    "currency",
    "price_tiers",
    "stock",
    "lead_time_days",
    "quote_valid_until",
    "region",
    "retrieved_at",
}


@pytest.mark.parametrize("part", sorted(PART_IDS))
def test_vendor_response_shape(part):
    quote = json.loads((PKG / "vendor_responses" / f"{part}.json").read_text(encoding="utf-8"))
    assert QUOTE_KEYS <= quote.keys()
    assert quote["part_id"] == part
    assert quote["currency"] in {"CNY"} | {k.split("_")[0] for k in MANIFEST["fx"] if "_" in k}
    assert quote["price_tiers"] and quote["price_tiers"][0]["min_qty"] == 1


# --- checkpoints ------------------------------------------------------------


def test_checkpoint_ids_unique_and_ordered():
    ids = [cp["id"] for cp in CHECKPOINTS]
    assert ids == [f"CP{i:02d}" for i in range(1, len(ids) + 1)]


def test_checkpoints_cover_required_trap_types():
    assert REQUIRED_CHECKPOINT_TYPES <= {cp["type"] for cp in CHECKPOINTS}
    assert any(cp["expected"] == "unknown" for cp in CHECKPOINTS)
    assert any(cp["expected"] == "exclude" for cp in CHECKPOINTS)


@pytest.mark.parametrize("cp", CHECKPOINTS, ids=lambda cp: cp["id"])
def test_checkpoint_references_resolve(cp):
    assert cp["expected"] in {"include", "exclude", "unknown", "mention"}
    if "requirement" in cp:
        assert cp["requirement"] in REQUIREMENT_IDS
    if "part" in cp:
        assert cp["part"] in PART_IDS
    assert cp["evidence"], "every checkpoint needs evidence"
    for ev in cp["evidence"]:
        assert ev["file"] in LISTED_FILES
        text = (PKG / ev["file"]).read_text(encoding="utf-8")
        assert ev["quote"] in text, f"{ev['quote']!r} not found in {ev['file']}"


def _passes(check: dict) -> bool:
    kind = check["kind"]
    if kind == "unit_compare":
        value = check["value"] * UNIT_SCALE[check["unit"]]
        threshold = check["threshold"] * UNIT_SCALE[check["threshold_unit"]]
        return value >= threshold if check["op"] == "ge" else value <= threshold
    if kind == "raman_resolution":
        lo, hi = check["shift_range_cm1"]
        worst = max(
            check["resolution_nm"] / wavelength_at_shift_nm(check["excitation_nm"], s) ** 2 * 1e7
            for s in (lo, hi)
        )
        assert worst == pytest.approx(check["worst_cm1_approx"], abs=0.01)
        return worst <= check["threshold_cm1"]
    if kind == "raman_coverage":
        w_lo, w_hi = check["wavelength_range_nm"]
        need_lo, need_hi = check["required_shift_cm1"]
        exc = check["excitation_nm"]
        return raman_shift_cm1(exc, w_lo) <= need_lo and raman_shift_cm1(exc, w_hi) >= need_hi
    if kind == "budget":
        fx = MANIFEST["fx"]
        total = sum(
            item["price"] * (1 if item["currency"] == "CNY" else fx[f"{item['currency']}_CNY"])
            for item in check["items"]
        )
        assert total == pytest.approx(check["total_cny"])
        return total <= check["limit_cny"]
    raise AssertionError(f"unknown check kind: {kind}")


@pytest.mark.parametrize("cp", [cp for cp in CHECKPOINTS if "check" in cp], ids=lambda cp: cp["id"])
def test_checkpoint_numeric_verdict_reproducible(cp):
    expected_pass = {"include": True, "exclude": False}[cp["expected"]]
    assert _passes(cp["check"]) is expected_pass
