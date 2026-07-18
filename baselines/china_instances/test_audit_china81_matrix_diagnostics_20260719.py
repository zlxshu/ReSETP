from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name(
    "audit_china81_matrix_diagnostics_20260718.py"
)
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("matrix_diagnostics", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_static_fixture(root: Path, instances: int = 81) -> None:
    catalog = []
    for index in range(instances):
        region = ("jjj", "prd", "cy")[index % 3]
        instance_id = f"i{index:02d}"
        catalog.append({"instance_id": instance_id, "region": region})
        write_csv(
            root / "instances" / instance_id / "nodes.csv",
            [
                {
                    "node_id": f"D{index}",
                    "node_type": "depot",
                    "latitude": f"{30 + index / 1000:.7f}",
                    "longitude": f"{110 + index / 1000:.7f}",
                },
                {
                    "node_id": f"C{index}",
                    "node_type": "customer",
                    "latitude": f"{30 + index / 1000 + 0.0001:.7f}",
                    "longitude": f"{110 + index / 1000 + 0.0001:.7f}",
                },
            ],
        )
    write_csv(root / "instance_catalog.csv", catalog)


def test_expected_counts_are_derived_from_static_inputs(tmp_path: Path) -> None:
    build_static_fixture(tmp_path)
    unique, materialized = MODULE.derive_expected_counts(tmp_path)
    assert unique == {"jjj": 54, "prd": 54, "cy": 54}
    assert materialized == {"jjj": 54, "prd": 54, "cy": 54}


def test_missing_instance_cannot_be_a_valid_china81_catalog(tmp_path: Path) -> None:
    build_static_fixture(tmp_path, instances=80)
    with pytest.raises(RuntimeError, match="81 unique"):
        MODULE.derive_expected_counts(tmp_path)
