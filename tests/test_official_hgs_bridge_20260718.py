from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "baselines/e2_alns/official_hgs_bridge_20260718.py"
SPEC = importlib.util.spec_from_file_location("official_hgs_bridge_tested", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
BRIDGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BRIDGE
SPEC.loader.exec_module(BRIDGE)


RAW = REPO / "baselines/e2_alns/official_hgs_b_gate_20260718/raw_sources/X-n110-k13.vrp"
SOLUTION = REPO / "baselines/e2_alns/official_hgs_b_gate_20260718/solutions/hgs__X-n110-k13__seed1.sol"


def test_parse_and_validate_sealed_development_result() -> None:
    problem = BRIDGE.parse_cvrplib(RAW)
    result = BRIDGE.parse_and_validate_solution(problem, SOLUTION)
    assert result["passed"]
    assert result["cost"] == 14971
    assert result["route_count"] == 13


def test_bridge_rejects_non_cvrp(tmp_path: Path) -> None:
    malformed = tmp_path / "not-cvrp.vrp"
    malformed.write_text(
        "\n".join(
            [
                "NAME : bad",
                "TYPE : VRPTW",
                "DIMENSION : 1",
                "EDGE_WEIGHT_TYPE : EUC_2D",
                "CAPACITY : 1",
                "NODE_COORD_SECTION",
                "1 0 0",
                "DEMAND_SECTION",
                "1 0",
                "DEPOT_SECTION",
                "1",
                "-1",
                "EOF",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="TYPE=CVRP only"):
        BRIDGE.parse_cvrplib(malformed)


def test_config_rejects_invalid_budget() -> None:
    with pytest.raises(ValueError, match="positive"):
        BRIDGE.HGSConfig(seed=1, time_limit_seconds=0)
