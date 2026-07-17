from __future__ import annotations

import csv
import importlib.util
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "baselines/e4_e5/china_tvci_source_gate_20260717_v2/tvci_2025_48slot_wide.csv"
OUTPUT = ROOT / (
    "baselines/e4_e5/china_tvci_representative_days_jjj_prd_cy_20260718/"
    "selected_days_china_2025.csv"
)
SCRIPT = ROOT / (
    "baselines/e4_e5/china_tvci_representative_days_jjj_prd_cy_20260718/"
    "select_china_tvci_representative_days_jjj_prd_cy_20260718.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("china_tvci_selection", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load selection script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_conservation_and_replayed_selection():
    module = _module()
    metrics = module.load_daily_metrics(SOURCE)
    assert set(metrics) == {"Beijing", "Guangdong", "Chongqing"}
    assert all(len(days) == 365 for days in metrics.values())
    assert all(
        [metric.day_index for metric in days] == list(range(1, 366))
        for days in metrics.values()
    )

    expected = module.select_representative_days(metrics)
    with OUTPUT.open(newline="", encoding="utf-8") as handle:
        observed = list(csv.DictReader(handle))
    assert observed == [{key: str(value) for key, value in row.items()} for row in expected]

    counts = Counter(
        (row["region"], int(row["quarter"]), row["selection_rule"])
        for row in observed
    )
    assert len(observed) == 36
    assert len(counts) == 36
    assert set(counts.values()) == {1}
    assert {row["result_blind_selection"] for row in observed} == {"1"}


def test_selection_contract_is_curve_only():
    module = _module()
    metrics = module.load_daily_metrics(SOURCE)
    rows = module.select_representative_days(metrics)
    assert {row["region"] for row in rows} == set(module.REGIONS)
    assert {row["selection_rule"] for row in rows} == set(module.SELECTION_RULES)
    assert {int(row["quarter"]) for row in rows} == {1, 2, 3, 4}
    assert all("solver" not in str(row).lower() for row in rows)
