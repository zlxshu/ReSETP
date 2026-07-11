"""Verify the E2 unseen-seed recovery gate from saved artifacts, without rerunning search."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns.e2_loss_recovery_unseen_seed_gate import (
    CANDIDATE_ID,
    validation_pairs,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import instance_abs_dir
from setp_solver.search.metaheuristic_baselines import solution_from_dict


DEFAULT_OUTPUT = REPO_ROOT / "baselines/e2_alns/e2_loss_recovery_20260711/unseen_seed_4000_gate"
PROVENANCE_FILES = (
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "baselines/e2_alns/e2_loss_recovery_gate.py",
    "baselines/e2_alns/e2_loss_recovery_unseen_seed_gate.py",
    "baselines/e2_alns/e2_loss_recovery_unseen_seed_verify.py",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob(commit: str, relative_path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def expected_run_ids() -> set[str]:
    algorithms = ("staged", CANDIDATE_ID, "LNS")
    return {
        f"{instance}__seed{seed}__{algorithm}"
        for instance, seed in validation_pairs()
        for algorithm in algorithms
    }


def _verify_declared_hashes(output_dir: Path) -> list[str]:
    manifest_path = output_dir / "artifact_hashes.json"
    if not manifest_path.exists():
        return ["artifact_hashes.json:MISSING"]
    declared = _read_json(manifest_path)
    failures: list[str] = []
    for relative_path, expected_hash in declared.items():
        path = output_dir / relative_path
        if not path.exists():
            failures.append(f"{relative_path}:MISSING")
        elif _sha256(path.read_bytes()) != str(expected_hash):
            failures.append(f"{relative_path}:HASH_MISMATCH")
    return failures


def verify(output_dir: Path, execution_commit: str | None = None) -> dict[str, Any]:
    required = ("decision.json", "metadata.json", "raw_runs.csv", "paired_comparisons.csv", "per_scale_summary.csv")
    missing_required = [name for name in required if not (output_dir / name).exists()]
    if missing_required:
        raise RuntimeError(f"UNSEEN_SEED_GATE_NOT_FINISHED:{','.join(missing_required)}")

    decision = _read_json(output_dir / "decision.json")
    metadata = _read_json(output_dir / "metadata.json")
    commit = str(execution_commit or metadata.get("git_commit") or "")
    if not commit:
        raise RuntimeError("MISSING_EXECUTION_COMMIT")
    with (output_dir / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    expected_ids = expected_run_ids()
    actual_ids = [str(row.get("run_id", "")) for row in rows]
    actual_id_set = set(actual_ids)
    duplicate_run_ids = sorted({run_id for run_id in actual_ids if actual_ids.count(run_id) > 1})
    missing_run_ids = sorted(expected_ids - actual_id_set)
    unexpected_run_ids = sorted(actual_id_set - expected_ids)
    status_failures = [row["run_id"] for row in rows if row.get("status") != "OK"]
    budget_failures = [
        row["run_id"]
        for row in rows
        if int(row.get("eval_budget", 0)) != 4000 or int(row.get("actual_evals", 0)) != 4000
    ]
    recorded_violations = [row["run_id"] for row in rows if int(row.get("violations", -1)) != 0]

    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(metadata["battery_kwh"]))
    recompute_failures: list[dict[str, Any]] = []
    missing_solutions: list[str] = []
    missing_operator_counts: list[str] = []
    bundle_cache: dict[str, Any] = {}
    for row in rows:
        run_id = str(row["run_id"])
        solution_path = output_dir / "solutions" / f"{run_id}.json"
        operator_path = output_dir / "solutions" / f"{run_id}.operators.json"
        if not solution_path.exists():
            missing_solutions.append(run_id)
            continue
        if not operator_path.exists():
            missing_operator_counts.append(run_id)
        instance = str(row["instance"])
        if instance not in bundle_cache:
            bundle_cache[instance] = load_search_bundle(instance_abs_dir(REPO_ROOT, instance))
        bundle = bundle_cache[instance]
        solution = solution_from_dict(_read_json(solution_path))
        violations = check_solution(solution, bundle.instance, prices)
        recomputed_cost = model_cost(
            solution,
            EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices),
        )
        recorded_cost = float(row["cost"])
        if violations or abs(recomputed_cost - recorded_cost) > 1e-6:
            recompute_failures.append(
                {
                    "run_id": run_id,
                    "recorded_cost": recorded_cost,
                    "recomputed_cost": recomputed_cost,
                    "cost_delta": recomputed_cost - recorded_cost,
                    "violations": [str(violation) for violation in violations],
                }
            )

    provenance: dict[str, Any] = {}
    provenance_ok = True
    for relative_path in PROVENANCE_FILES:
        working = (REPO_ROOT / relative_path).read_bytes()
        committed = _git_blob(commit, relative_path)
        matches = working == committed
        provenance_ok = provenance_ok and matches
        provenance[relative_path] = {
            "working_sha256": _sha256(working),
            "committed_sha256": _sha256(committed),
            "matches_execution_commit": matches,
        }

    hash_failures = _verify_declared_hashes(output_dir)
    decision_verdict = str(decision.get("verdict", ""))
    decision_valid = decision_verdict in {
        "E2_UNSEEN_SEED_4000_PROMOTED",
        "E2_UNSEEN_SEED_4000_REJECTED",
    }
    passed = (
        len(rows) == 57
        and not duplicate_run_ids
        and not missing_run_ids
        and not unexpected_run_ids
        and not status_failures
        and not budget_failures
        and not recorded_violations
        and not missing_solutions
        and not missing_operator_counts
        and not recompute_failures
        and not hash_failures
        and provenance_ok
        and decision_valid
    )
    verification = {
        "verdict": "E2_UNSEEN_SEED_4000_VERIFIED" if passed else "HALT_E2_UNSEEN_SEED_4000_VERIFICATION",
        "decision_verdict": decision_verdict,
        "rows": len(rows),
        "expected_rows": 57,
        "duplicate_run_ids": duplicate_run_ids,
        "missing_run_ids": missing_run_ids,
        "unexpected_run_ids": unexpected_run_ids,
        "status_failures": status_failures,
        "budget_failures": budget_failures,
        "recorded_violations": recorded_violations,
        "missing_solutions": missing_solutions,
        "missing_operator_counts": missing_operator_counts,
        "recompute_failures": recompute_failures,
        "hash_failures": hash_failures,
        "execution_commit": commit,
        "provenance_files": provenance,
    }
    _write_json(output_dir / "verification.json", verification)
    metadata["execution_commit"] = commit
    metadata["verification_contract"] = "saved solutions fully recomputed; matrix, budget, violations, hashes, and source provenance checked"
    _write_json(output_dir / "metadata.json", metadata)
    hashes = {
        str(path.relative_to(output_dir)): _sha256(path.read_bytes())
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
        and path.name not in {"artifact_hashes.json", "formal_run.log"}
        and not path.name.startswith("._")
    }
    _write_json(output_dir / "artifact_hashes.json", hashes)
    if not passed:
        raise RuntimeError(json.dumps(verification, sort_keys=True))
    return verification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execution-commit")
    args = parser.parse_args()
    print(json.dumps(verify(args.output_dir.resolve(), args.execution_commit), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
