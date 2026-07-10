from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "baselines/e2_alns/m1_fleet_opportunity_map.py"


def _load_probe():
    assert PROBE_PATH.is_file(), "M1 fleet opportunity map is missing"
    spec = importlib.util.spec_from_file_location("m1_fleet_opportunity_map_for_test", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_composition_verdict_distinguishes_physics_from_routing_dependence() -> None:
    probe = _load_probe()

    assert probe.classify_composition([{"route_count": 8, "best_ev_routes": 8}]) == "FIXED_ROUTES_ALL_EV"
    assert probe.classify_composition([{"route_count": 8, "best_ev_routes": 0}]) == "FIXED_ROUTES_ALL_CV"
    assert probe.classify_composition([{"route_count": 8, "best_ev_routes": 3}]) == "FIXED_ROUTES_MIXED"
    assert probe.classify_composition(
        [{"route_count": 8, "best_ev_routes": 8}, {"route_count": 8, "best_ev_routes": 3}]
    ) == "FIXED_ROUTES_ROUTING_DEPENDENT"
