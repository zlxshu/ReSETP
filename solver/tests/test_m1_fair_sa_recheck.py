from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "baselines/e2_alns/m1_fair_sa_recheck.py"


def _load_probe():
    assert PROBE_PATH.is_file(), "M1 fair SA recheck is missing"
    spec = importlib.util.spec_from_file_location("m1_fair_sa_recheck_for_test", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sa_verdict_needs_majority_paired_wins_and_lower_mean() -> None:
    probe = _load_probe()
    supported = [
        {"profile": "DEFAULT_ALPHA_UCB", "sa_best_cost": 90.0, "alns_best_cost": 100.0, "clean": True},
        {"profile": "DEFAULT_ALPHA_UCB", "sa_best_cost": 95.0, "alns_best_cost": 100.0, "clean": True},
    ]
    unsupported = [
        {"profile": "DEFAULT_ALPHA_UCB", "sa_best_cost": 110.0, "alns_best_cost": 100.0, "clean": True},
        {"profile": "DEFAULT_ALPHA_UCB", "sa_best_cost": 95.0, "alns_best_cost": 100.0, "clean": True},
    ]

    assert probe.classify_sa(supported) == "SA_SHORT_ADVANTAGE_REPRODUCED"
    assert probe.classify_sa(unsupported) == "SA_SHORT_ADVANTAGE_NOT_REPRODUCED"
