from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "solver/scripts/run_public_v2_28_clean_ruler.py"
SPEC = importlib.util.spec_from_file_location("public_clean_ruler", RUNNER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _environment(arm: str) -> dict[str, str]:
    _, environment = MODULE._worker_command(
        output_dir=REPO / "unused",
        instance="PR11A",
        arm=arm,
        seed=11,
        max_runtime_seconds=120.0,
        no_improvement=5_000,
        run_kind="probe",
    )
    return environment


def test_independent_worker_uses_only_current_solver_and_kernel_sources() -> None:
    paths = _environment("independent")["PYTHONPATH"].split(os.pathsep)
    assert paths == [
        str(REPO / "third_party/setp_hgs_kernel"),
        str(REPO / "solver/src"),
    ]


def test_frozen_worker_remains_isolated_from_repo_pythonpath() -> None:
    environment = _environment("frozen_pyvrp")
    assert "PYTHONPATH" not in environment
    assert environment["PYTHONNOUSERSITE"] == "1"


@pytest.mark.parametrize(
    ("run_kind", "success_verdict", "failure_verdict"),
    (
        ("probe", "PROBE_RUN_COMPLETE", "PROBE_RUN_FAILED_AUDIT"),
        ("formal", "FORMAL_RUN_COMPLETE", "FORMAL_RUN_FAILED_AUDIT"),
    ),
)
def test_run_kind_selects_distinct_acceptance_verdicts(
    run_kind: str,
    success_verdict: str,
    failure_verdict: str,
) -> None:
    assert MODULE._run_verdicts(run_kind) == (
        success_verdict,
        failure_verdict,
    )


@pytest.mark.parametrize("run_kind", ("probe", "formal"))
def test_validator_rejects_audit_failure_even_when_cost_exists(
    tmp_path: Path,
    run_kind: str,
) -> None:
    output = tmp_path / "public-audit-failure"
    output.mkdir()
    MODULE._atomic_text(
        output / "raw_runs.csv",
        "iteration,elapsed_seconds,best_cost\n1,0.1,123\n",
    )
    MODULE._json(output / "best_solution.json", {"routes": [[1, 2]]})
    MODULE._json(
        output / "audit.json",
        {
            "status": "COMPLETE",
            "summary": {
                "all_routes_raw_precision_feasible": False,
                "service_complete": True,
            },
        },
    )
    success_verdict, failure_verdict = MODULE._run_verdicts(run_kind)
    rejected = MODULE.assess_run(
        termination_ok=True,
        feasible_ok=False,
        customers_complete=True,
        demand_complete=True,
        audit_ok=False,
        success_verdict=success_verdict,
        failure_verdict=failure_verdict,
    )
    MODULE.finalize_five_file_package(
        output,
        acceptance=rejected,
        metadata={"finished_at": "test", "run_kind": run_kind},
        decision={"cost_scaled": 123},
        report_text="# rejected\n",
    )

    with pytest.raises(RuntimeError, match="not accepted"):
        MODULE._validate_run_package(output)
