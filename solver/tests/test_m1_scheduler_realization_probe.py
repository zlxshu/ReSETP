from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "baselines/e2_alns/m1_scheduler_realization_probe.py"


def _load_probe():
    assert PROBE_PATH.is_file(), "M1 scheduler realization probe is missing"
    spec = importlib.util.spec_from_file_location("m1_scheduler_realization_probe_for_test", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduler_verdict_requires_both_starvation_and_a_better_coverage_run() -> None:
    probe = _load_probe()
    confirmed = [
        {"profile": "DEFAULT_ALPHA_UCB", "start": "SHARED_ONE_EV", "seed": 1, "dominant_pair_share": 1.0, "selected_pair_count": 1, "best_cost": 100.0},
        {"profile": "BALANCED_COVERAGE", "start": "SHARED_ONE_EV", "seed": 1, "dominant_pair_share": 0.3, "selected_pair_count": 18, "best_cost": 90.0},
    ]
    noncausal = [
        {"profile": "DEFAULT_ALPHA_UCB", "start": "SHARED_ONE_EV", "seed": 1, "dominant_pair_share": 1.0, "selected_pair_count": 1, "best_cost": 90.0},
        {"profile": "BALANCED_COVERAGE", "start": "SHARED_ONE_EV", "seed": 1, "dominant_pair_share": 0.3, "selected_pair_count": 18, "best_cost": 100.0},
    ]
    healthy = [
        {"profile": "DEFAULT_ALPHA_UCB", "start": "SHARED_ONE_EV", "seed": 1, "dominant_pair_share": 0.4, "selected_pair_count": 12, "best_cost": 100.0},
        {"profile": "BALANCED_COVERAGE", "start": "SHARED_ONE_EV", "seed": 1, "dominant_pair_share": 0.3, "selected_pair_count": 18, "best_cost": 90.0},
    ]

    assert probe.classify_scheduler(confirmed) == "DEFAULT_SELECTOR_STARVATION_CONFIRMED"
    assert probe.classify_scheduler(noncausal) == "SELECTOR_STARVATION_PRESENT_NOT_CAUSAL"
    assert probe.classify_scheduler(healthy) == "SELECTOR_NOT_PRIMARY_BARRIER"


def test_minimum_coverage_gate_requires_clean_coverage_majority_wins_and_lower_mean() -> None:
    probe = _load_probe()
    supported = [
        {"profile": "DEFAULT_ALPHA_UCB", "start": "CV_ONLY", "seed": 1, "best_cost": 100.0},
        {"profile": "MINIMUM_COVERAGE", "start": "CV_ONLY", "seed": 1, "best_cost": 90.0, "vehicle_type_swap_attempts": 2, "feasible": True, "actual_evaluations": 400, "eval_budget": 400},
        {"profile": "DEFAULT_ALPHA_UCB", "start": "SHARED_ONE_EV", "seed": 1, "best_cost": 100.0},
        {"profile": "MINIMUM_COVERAGE", "start": "SHARED_ONE_EV", "seed": 1, "best_cost": 95.0, "vehicle_type_swap_attempts": 2, "feasible": True, "actual_evaluations": 400, "eval_budget": 400},
    ]
    failed = [*supported]
    failed[3] = {**failed[3], "vehicle_type_swap_attempts": 0}

    assert probe.classify_minimum_coverage(supported) == "MINIMUM_COVERAGE_400_SUPPORTED"
    assert probe.classify_minimum_coverage(failed) == "MINIMUM_COVERAGE_400_NOT_SUPPORTED"
