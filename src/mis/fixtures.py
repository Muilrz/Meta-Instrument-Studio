"""Locate and load the versioned baseline task packages under ``fixtures/``."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures"


def baseline_dir(name: str = "raman_baseline") -> Path:
    path = FIXTURES_DIR / name
    if not path.is_dir():
        raise FileNotFoundError(f"baseline package not found: {path}")
    return path


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_manifest(name: str = "raman_baseline") -> dict[str, Any]:
    return load_yaml(baseline_dir(name) / "manifest.yaml")


def load_checkpoints(name: str = "raman_baseline") -> list[dict[str, Any]]:
    return load_yaml(baseline_dir(name) / "checkpoints.yaml")


def load_requirements(name: str = "raman_baseline") -> list[dict[str, str]]:
    with (baseline_dir(name) / "requirements.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
