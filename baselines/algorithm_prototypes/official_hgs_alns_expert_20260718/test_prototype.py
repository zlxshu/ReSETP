from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys


REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUNNER_PATH = HERE / "run_gate.py"
SPEC = importlib.util.spec_from_file_location("me_hgs_gate_test_module", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)

INSTANCE = (
    REPO
    / "baselines/e2_alns/official_hgs_b_gate_20260718/raw_sources"
    / "X-n110-k13.vrp"
)
OFFICIAL = (
    REPO
    / "build/official-hgs-cvrp-1a927955cd28/source/build-resetp/hgs"
)
CANDIDATE = (
    REPO
    / "build/official-hgs-alns-expert-20260718/source/build-resetp/hgs"
)


def test_expert_disabled_matches_official_fixed_iteration(tmp_path: Path) -> None:
    official_solution = tmp_path / "official.sol"
    candidate_solution = tmp_path / "candidate.sol"
    common = ["-it", "50", "-seed", "7", "-round", "1", "-log", "0"]
    subprocess.run(
        [str(OFFICIAL), str(INSTANCE), str(official_solution), *common],
        check=True,
        capture_output=True,
        text=True,
    )
    environment = os.environ.copy()
    environment["RESET_ME_EXPERT_ENABLED"] = "0"
    subprocess.run(
        [str(CANDIDATE), str(INSTANCE), str(candidate_solution), *common],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert candidate_solution.read_text(encoding="utf-8") == official_solution.read_text(
        encoding="utf-8"
    )


def test_candidate_short_run_is_independently_valid(tmp_path: Path) -> None:
    row = RUNNER.run_hgs(
        algorithm="mechanism_expert_hgs_alns",
        binary=CANDIDATE,
        instance_path=INSTANCE,
        seed=1,
        seconds=0.05,
        solution_path=tmp_path / "candidate.sol",
        candidate=True,
    )
    assert row["feasible"]
    assert row["route_count"] > 0
    assert row["diagnostics"]["attempts"] >= row["diagnostics"]["accepted"]
    assert 0.0 <= row["diagnostics"]["expert_cpu_share"] <= 0.50


def test_original_alns_official_example_is_independently_valid() -> None:
    row = RUNNER.run_original_alns(
        instance_path=INSTANCE,
        seed=1,
        seconds=0.01,
    )
    assert row["feasible"]
    assert row["route_count"] > 0
    assert row["cost"] > 0
