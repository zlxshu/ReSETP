from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "baselines/algorithm_prototypes/duty_hgs_20260807/"
    "run_cross_depot_focus_probe.py"
)
SPEC = importlib.util.spec_from_file_location("cross_depot_focus_probe", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_focus_customers_supports_route_marginal_screen(tmp_path: Path) -> None:
    source = tmp_path / "marginals.csv"
    rows = [
        {
            "instance_id": "case-a",
            "customer_id": "C1",
            "best_capacity_relocate_net_delta_km": "-2.5",
        },
        {
            "instance_id": "case-a",
            "customer_id": "C2",
            "best_capacity_relocate_net_delta_km": "0.0",
        },
        {
            "instance_id": "case-b",
            "customer_id": "C3",
            "best_capacity_relocate_net_delta_km": "-9.0",
        },
    ]
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    assert MODULE._focus_customers(
        source,
        "case-a",
        "route_marginal_capacity",
    ) == {"C1": -2.5}
