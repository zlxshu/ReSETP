from __future__ import annotations

import importlib.util
import sys
import csv
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
RUNNER = (
    REPO
    / "baselines/china_e3_e7/e3_scattered_ownership_20260801/"
    "run_e3_scattered_ownership.py"
)


def load_runner():
    spec = importlib.util.spec_from_file_location("e3_scattered_tested", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_sequences_are_complete_and_deterministic() -> None:
    runner = load_runner()
    sequences = runner.sequences()
    assert len(sequences) == 6
    assert all(len(sequence) == 200 for sequence in sequences.values())
    assert all(set(sequence) == {0, 1, 2, 3} for sequence in sequences.values())


def test_mapping_uses_node_order_and_existing_fleet() -> None:
    runner = load_runner()
    original = runner.load_bundle("cn-prd-150c-01-V2-LOCATIONS")
    bundle, initial, info = runner.prepare(
        "cn-prd-150c-01-V2-LOCATIONS", "Uniform_Balanced"
    )
    customers = sorted(bundle.customer_home_depot)
    depots = sorted(set(bundle.customer_home_depot.values()))
    labels = runner.sequences()[("Uniform_Balanced", "01")]
    assert bundle.customer_home_depot[customers[0]] == depots[labels[0]]
    assert sum(info["owner_counts"].values()) == 150
    assert bundle.instance.num_cv == original.instance.num_cv
    assert bundle.instance.num_ev == original.instance.num_ev
    assert {
        depot: dict(caps) for depot, caps in bundle.fleet_caps_by_depot.items()
    } == {
        depot: dict(caps) for depot, caps in original.fleet_caps_by_depot.items()
    }
    assert initial is None
    assert info["capacity_audit"]["D_dongguan"]["capacity_shortfall_kg"] == 524
    assert info["capacity_audit"]["D_foshan"]["capacity_shortfall_kg"] == 806


def test_balanced_and_unbalanced_are_both_retained() -> None:
    runner = load_runner()
    balanced, _, _ = runner.prepare(
        "cn-prd-200c-01-V2-LOCATIONS", "Uniform_Balanced"
    )
    unbalanced, _, _ = runner.prepare(
        "cn-prd-200c-01-V2-LOCATIONS", "Uniform_Unbalanced"
    )
    assert dict(balanced.customer_home_depot) != dict(
        unbalanced.customer_home_depot
    )


def test_existing_fleet_pilot_halts_and_keeps_all_seed1_rows(tmp_path: Path) -> None:
    runner = load_runner()
    decision = runner.run_pilot(tmp_path)
    assert decision["status"] == "HALT_ORIGINAL_FLEET_STANDALONE_CAPACITY_INFEASIBLE"
    assert decision["attempted_seeds_by_family"] == {
        family: [1] for family in runner.FAMILIES
    }
    assert decision["not_started_seeds_by_family"] == {
        family: [2, 3] for family in runner.FAMILIES
    }
    assert {path.name for path in tmp_path.iterdir()} == {
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    }
    rows = list(csv.DictReader((tmp_path / "raw_runs.csv").open(encoding="utf-8")))
    assert len(rows) == 4
    assert {row["source_family"] for row in rows} == set(runner.FAMILIES)
    assert {row["arm"] for row in rows} == set(runner.ARMS)
    assert {row["seed"] for row in rows} == {"1"}
    assert sum(row["status"] == "PROVEN_INFEASIBLE_CAPACITY_LOWER_BOUND" for row in rows) == 2
    assert sum(row["status"] == "NOT_RUN_STOP_RULE" for row in rows) == 2
    manifest = json.loads((tmp_path / "artifact_hashes.json").read_text())
    assert set(manifest["artifacts"]) == {
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "report.md",
    }
