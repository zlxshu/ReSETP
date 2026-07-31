from __future__ import annotations

import importlib.util
import sys
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


def test_mapping_uses_node_order_and_reference_fleet() -> None:
    runner = load_runner()
    bundle, _, info = runner.prepare(
        "cn-prd-150c-01-V2-LOCATIONS", "Uniform_Balanced"
    )
    customers = sorted(bundle.customer_home_depot)
    depots = sorted(set(bundle.customer_home_depot.values()))
    labels = runner.sequences()[("Uniform_Balanced", "01")]
    assert bundle.customer_home_depot[customers[0]] == depots[labels[0]]
    assert sum(info["owner_counts"].values()) == 150
    assert bundle.instance.num_cv == 4 * 40
    assert bundle.instance.num_ev == 4 * 10
    assert all(
        dict(caps) == {"num_cv": 40, "num_ev": 10, "total_fleet_cap": 50}
        for caps in bundle.fleet_caps_by_depot.values()
    )


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
