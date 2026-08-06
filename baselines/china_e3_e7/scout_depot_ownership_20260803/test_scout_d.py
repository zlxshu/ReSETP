from __future__ import annotations

from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (
    HERE,
    REPO,
    REPO / "solver/src",
    REPO / "models/src",
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720",
    REPO
    / "build/python_envs/pyvrp-hgs-0.12.2/lib/python3.13/site-packages",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_scout_d as scout


def test_nearest_mapping_is_direct_and_matches_instance_authority() -> None:
    with scout.model_config_scope(scout.MODEL_CONFIG):
        bundle = scout.load_bundle()
        mapping, detail = scout.build_nearest_mapping(bundle)
    assert mapping == dict(bundle.customer_home_depot)
    assert detail["capacity_rank_alignment_applied"] is False
    assert len(mapping) == 100


def test_frozen_random_rule_halts_on_four_labels_two_depots() -> None:
    with scout.model_config_scope(scout.MODEL_CONFIG):
        bundle = scout.load_bundle()
        with pytest.raises(ValueError):
            scout.build_random_mapping(bundle)
    labels = scout.source_sequences()[
        (scout.SOURCE_FAMILY, scout.source_replicate(scout.INSTANCE_ID))
    ][:100]
    assert set(labels) == {0, 1, 2, 3}
    assert len(bundle.fleet_caps_by_depot) == 2


def test_preflight_has_feasible_common_multitrip_initial() -> None:
    payload = scout.preflight()
    assert payload["random"]["status"].startswith("HALT_PRESEARCH")
    assert payload["nearest"]["status"] == "PASS_PREFLIGHT_READY_FOR_SEARCH"
    assert payload["nearest"]["initial_payload"]["multitrip_certificate"][
        "status"
    ] == "PASS"
    assert payload["nearest"]["initial_payload"]["objective_cny"] > 0


def test_iteration_contract_has_no_2000_or_150_early_stop() -> None:
    assert scout.ITERATIONS_PER_VIEW == 25_000
    assert scout.SEEDS == tuple(range(1, 11))
    source = Path(scout.__file__).read_text(encoding="utf-8")
    assert "max_no_improvement_iterations_per_view=None" in source
