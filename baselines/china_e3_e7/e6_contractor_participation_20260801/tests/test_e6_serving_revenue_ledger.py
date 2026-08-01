from __future__ import annotations

import csv
from collections import defaultdict
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
OUTPUT = HERE / "formal_e6_serving_revenue_ledger_20260801"
SOURCE = HERE / "formal_e6a_panel_20260801"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_formal_serving_revenue_ledger_closes_independently() -> None:
    with (OUTPUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with (OUTPUT / "ledger_checks.csv").open(encoding="utf-8", newline="") as handle:
        checks = list(csv.DictReader(handle))
    decision = json.loads((OUTPUT / "decision.json").read_text(encoding="utf-8"))

    grouped: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["instance_id"], int(row["seed"]))].append(row)

    assert len(rows) == 240
    assert len(grouped) == len(checks) == 60
    assert all(len(unit) == 4 for unit in grouped.values())
    assert all(
        len({row["contractor"] for row in unit}) == 4
        for unit in grouped.values()
    )

    for check in checks:
        key = (check["instance_id"], int(check["seed"]))
        unit = grouped[key]
        revenue = sum(float(row["actual_service_revenue_cny"]) for row in unit)
        cost = sum(float(row["actual_service_cost_cny"]) for row in unit)
        profit = sum(float(row["pre_settlement_profit_cny"]) for row in unit)
        assert abs(revenue - float(check["formal_game_revenue_cny"])) < 1.0e-6
        assert abs(cost - float(check["formal_grand_cost_cny"])) < 1.0e-6
        assert abs(profit - float(check["formal_grand_profit_cny"])) < 1.0e-6

    for (instance_id, seed), unit_rows in grouped.items():
        unit = SOURCE / "units" / instance_id / f"seed_{seed:02d}"
        manifest = json.loads((unit / "artifact_hashes.json").read_text(encoding="utf-8"))[
            "artifacts"
        ]
        settlement_path = unit / "settlement_results.json"
        assert sha256(settlement_path) == manifest["settlement_results.json"]
        settlement = json.loads(settlement_path.read_text(encoding="utf-8"))
        for row in unit_rows:
            expected = float(settlement["standalone_profit_cny"][row["contractor"]])
            assert abs(float(row["standalone_profit_cny"]) - expected) < 1.0e-9

    below = [row for row in rows if row["pre_settlement_below_standalone"] == "True"]
    affected = {(row["instance_id"], int(row["seed"])) for row in below}
    worst = min(rows, key=lambda row: float(row["pre_settlement_gain_over_standalone_cny"]))
    assert len(below) == decision["member_rows_below_standalone"]
    assert len(affected) == decision["units_with_member_below_standalone"]
    assert abs(
        float(worst["pre_settlement_gain_over_standalone_cny"])
        - decision["minimum_pre_settlement_gain_over_standalone_cny"]
    ) < 1.0e-9
