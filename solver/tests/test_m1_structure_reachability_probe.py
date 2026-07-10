from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "baselines/e2_alns/m1_structure_reachability_probe.py"


def _load_probe():
    assert PROBE_PATH.is_file(), "M1 structure reachability probe is missing"
    spec = importlib.util.spec_from_file_location("m1_structure_reachability_probe_for_test", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reachability_verdict_distinguishes_operator_acceptance_and_scheduler_barriers() -> None:
    probe = _load_probe()

    blocked = probe.classify_reachability(
        [{"engine": "ALNS", "changed": True, "feasible": True, "route_delta": 0, "ev_route_delta": 0, "cost_delta": -1.0}]
    )
    acceptance = probe.classify_reachability(
        [{"engine": "ALNS", "changed": True, "feasible": True, "route_delta": -1, "ev_route_delta": 0, "cost_delta": 5.0}]
    )
    scheduler = probe.classify_reachability(
        [{"engine": "ALNS", "changed": True, "feasible": True, "route_delta": 0, "ev_route_delta": 1, "cost_delta": -5.0}]
    )

    assert blocked == "ALNS_OPERATOR_REACHABILITY_BLOCKED"
    assert acceptance == "ALNS_ACCEPTANCE_BARRIER"
    assert scheduler == "ALNS_SCHEDULER_OR_MULTI_STEP_BARRIER"
