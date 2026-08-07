from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = (
    ROOT
    / "baselines/algorithm_prototypes/duty_hgs_20260807"
    / "run_cross_depot_profit_replay.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("cross_depot_profit_replay", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import profit replay runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selects_all_and_only_evaluated_raw_cost_decreases(tmp_path: Path) -> None:
    path = tmp_path / "candidate_rows.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("action_id", "evaluated", "cost_change_cny"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(
            (
                {"action_id": "negative", "evaluated": "True", "cost_change_cny": "-1.25"},
                {"action_id": "zero", "evaluated": "True", "cost_change_cny": "0"},
                {"action_id": "positive", "evaluated": "True", "cost_change_cny": "2"},
                {"action_id": "rejected", "evaluated": "False", "cost_change_cny": "-9"},
            )
        )

    runner = _load_runner()

    assert runner.select_raw_cost_decreasing_actions(path) == {"negative": -1.25}
