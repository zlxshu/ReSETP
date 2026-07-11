"""Unseen-seed 4000-evaluation gate for the bounded E2 loss-recovery candidate."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
from typing import Any


from baselines.e2_alns.e2_loss_recovery_gate import (
    REPO_ROOT,
    _atomic_csv,
    _atomic_json,
    _read_csv,
    _run_task,
)
from setp_solver.search.instance_registry import assert_formal_benchmark_ready


LOSS_PRONE_SCALES = (15, 20, 50, 75, 100, 150)
UNSEEN_SEEDS = (6, 7, 8)
GUARD_PAIRS = (("L-main-threeshift-200c-01", 6),)
CANDIDATE_ID = "proportional_true_lns_middle"


def _instance(scale: int) -> str:
    return f"L-main-threeshift-{scale}c-01"


def validation_pairs() -> tuple[tuple[str, int], ...]:
    return tuple(
        [(_instance(scale), seed) for scale in LOSS_PRONE_SCALES for seed in UNSEEN_SEEDS]
        + list(GUARD_PAIRS)
    )


def _scale(instance: str) -> int:
    return int(instance.split("-")[-2].removesuffix("c"))


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _finalize(output_dir: Path, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    expected = int(metadata["expected_runs"])
    contract_ok = (
        len(rows) == expected
        and all(str(row["status"]) == "OK" for row in rows)
        and all(int(row["actual_evals"]) == int(metadata["eval_budget"]) for row in rows)
        and all(int(row["violations"]) == 0 for row in rows)
    )
    if not contract_ok:
        decision = {
            "verdict": "HALT_INCOMPLETE_OR_CONTRACT_FAILURE",
            "completed_runs": len(rows),
            "expected_runs": expected,
            "contract_ok": False,
        }
        _atomic_json(output_dir / "decision.json", decision)
        return decision

    lookup = {(str(row["instance"]), int(row["seed"]), str(row["algorithm"])): row for row in rows}
    paired: list[dict[str, Any]] = []
    for instance, seed in validation_pairs():
        staged = lookup[(instance, seed, "staged")]
        candidate = lookup[(instance, seed, CANDIDATE_ID)]
        lns = lookup[(instance, seed, "LNS")]
        staged_cost = float(staged["cost"])
        candidate_cost = float(candidate["cost"])
        lns_cost = float(lns["cost"])
        paired.append(
            {
                "instance": instance,
                "scale": _scale(instance),
                "seed": seed,
                "staged_cost": staged_cost,
                "candidate_cost": candidate_cost,
                "lns_cost": lns_cost,
                "candidate_gain_vs_staged_pct": (staged_cost - candidate_cost) / staged_cost * 100.0,
                "staged_gain_vs_lns_pct": (lns_cost - staged_cost) / lns_cost * 100.0,
                "candidate_gain_vs_lns_pct": (lns_cost - candidate_cost) / lns_cost * 100.0,
                "staged_loses_to_lns": staged_cost > lns_cost + 1e-9,
                "candidate_loses_to_lns": candidate_cost > lns_cost + 1e-9,
            }
        )
    _atomic_csv(output_dir / "paired_comparisons.csv", paired)

    scale_rows: list[dict[str, Any]] = []
    for scale in (*LOSS_PRONE_SCALES, 200):
        subset = [row for row in paired if int(row["scale"]) == scale]
        gains = [float(row["candidate_gain_vs_staged_pct"]) for row in subset]
        scale_rows.append(
            {
                "scale": scale,
                "pairs": len(subset),
                "mean_candidate_gain_vs_staged_pct": statistics.mean(gains),
                "median_candidate_gain_vs_staged_pct": _median(gains),
                "candidate_losses_to_lns": sum(bool(row["candidate_loses_to_lns"]) for row in subset),
                "staged_losses_to_lns": sum(bool(row["staged_loses_to_lns"]) for row in subset),
            }
        )
    _atomic_csv(output_dir / "per_scale_summary.csv", scale_rows)

    overall_gain = statistics.mean(float(row["candidate_gain_vs_staged_pct"]) for row in paired)
    staged_losses = sum(bool(row["staged_loses_to_lns"]) for row in paired)
    candidate_losses = sum(bool(row["candidate_loses_to_lns"]) for row in paired)
    loss_reduction = staged_losses - candidate_losses
    nonworse_loss_prone_scales = sum(
        float(row["mean_candidate_gain_vs_staged_pct"]) >= -1e-9
        for row in scale_rows
        if int(row["scale"]) in LOSS_PRONE_SCALES
    )
    worst_scale_gain = min(float(row["mean_candidate_gain_vs_staged_pct"]) for row in scale_rows)
    guard_gain = next(
        float(row["candidate_gain_vs_staged_pct"])
        for row in paired
        if int(row["scale"]) == 200 and int(row["seed"]) == 6
    )
    staged_median_vs_lns = _median([float(row["staged_gain_vs_lns_pct"]) for row in paired])
    candidate_median_vs_lns = _median([float(row["candidate_gain_vs_lns_pct"]) for row in paired])

    promoted = (
        overall_gain > 0.0
        and loss_reduction >= 2
        and nonworse_loss_prone_scales >= 4
        and worst_scale_gain >= -2.0
        and guard_gain >= -2.0
        and candidate_median_vs_lns >= staged_median_vs_lns - 1e-9
    )
    decision = {
        "verdict": "E2_UNSEEN_SEED_4000_PROMOTED" if promoted else "E2_UNSEEN_SEED_4000_REJECTED",
        "candidate_id": CANDIDATE_ID,
        "completed_runs": len(rows),
        "expected_runs": expected,
        "eval_budget": int(metadata["eval_budget"]),
        "contract_ok": True,
        "mean_candidate_gain_vs_staged_pct": overall_gain,
        "staged_losses_to_lns": staged_losses,
        "candidate_losses_to_lns": candidate_losses,
        "loss_reduction_vs_staged": loss_reduction,
        "nonworse_loss_prone_scales": nonworse_loss_prone_scales,
        "required_nonworse_loss_prone_scales": 4,
        "worst_scale_mean_gain_vs_staged_pct": worst_scale_gain,
        "guard_200c_seed6_gain_vs_staged_pct": guard_gain,
        "staged_median_gain_vs_lns_pct": staged_median_vs_lns,
        "candidate_median_gain_vs_lns_pct": candidate_median_vs_lns,
        "next_action": (
            "run the preregistered nine-scale seeds1-5 final-candidate matrix"
            if promoted
            else "reject proportional true-LNS-middle and stop formal recovery reruns"
        ),
    }
    _atomic_json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(
        "# E2 unseen-seed 4000-evaluation validation\n\n"
        f"Completed {len(rows)}/{expected} runs. Verdict: `{decision['verdict']}`.\n\n"
        f"Mean candidate gain over staged: {overall_gain:.3f}%. "
        f"Losses versus LNS changed from {staged_losses} to {candidate_losses}. "
        f"Non-worse loss-prone scales: {nonworse_loss_prone_scales}/6. "
        f"Worst scale mean change: {worst_scale_gain:.3f}%.\n",
        encoding="utf-8",
    )
    hashes = {
        str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
        and path.name not in {"artifact_hashes.json", "formal_run.log"}
        and not path.name.startswith("._")
    }
    _atomic_json(output_dir / "artifact_hashes.json", hashes)
    return decision


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    if int(args.eval_budget) != 4000:
        raise ValueError("The preregistered unseen-seed gate requires exactly 4000 evaluations")
    if int(args.workers) > 3:
        raise ValueError("The preregistered unseen-seed gate allows at most 3 workers")

    output_dir = repo_root / args.output_dir
    solution_dir = output_dir / "solutions"
    output_dir.mkdir(parents=True, exist_ok=True)
    solution_dir.mkdir(parents=True, exist_ok=True)
    algorithms = ("staged", CANDIDATE_ID, "LNS")
    tasks = [
        (
            str(repo_root),
            instance,
            seed,
            int(args.eval_budget),
            float(args.max_runtime_seconds),
            float(args.battery_kwh),
            algorithm,
        )
        for instance, seed in validation_pairs()
        for algorithm in algorithms
    ]
    metadata = {
        "schema_version": "setp-e2-loss-recovery-unseen-seed-gate.v1",
        "candidate_id": CANDIDATE_ID,
        "incumbent": "staged ALNS-LNS hybrid",
        "baseline": "LNS",
        "loss_prone_scales": list(LOSS_PRONE_SCALES),
        "unseen_seeds": list(UNSEEN_SEEDS),
        "guard_pairs": [list(pair) for pair in GUARD_PAIRS],
        "pairs": [list(pair) for pair in validation_pairs()],
        "eval_budget": int(args.eval_budget),
        "battery_kwh": float(args.battery_kwh),
        "start_contract": "formal make_shared_initial_solution with EV introduction and inferred fleet limits",
        "lns_common_flip_preprocess": True,
        "expected_runs": len(tasks),
        "workers": int(args.workers),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True
        ).stdout.strip(),
    }
    _atomic_json(output_dir / "metadata.json", metadata)
    raw_path = output_dir / "raw_runs.csv"
    rows: list[dict[str, Any]] = [dict(row) for row in _read_csv(raw_path) if row.get("status") == "OK"]
    completed = {str(row["run_id"]) for row in rows}
    pending = [task for task in tasks if f"{task[1]}__seed{task[2]}__{task[6]}" not in completed]
    with ProcessPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        futures = {executor.submit(_run_task, task): task for task in pending}
        for future in as_completed(futures):
            result = future.result()
            solution = result.pop("solution")
            operator_counts = result.pop("operator_counts")
            _atomic_json(solution_dir / f"{result['run_id']}.json", solution)
            _atomic_json(solution_dir / f"{result['run_id']}.operators.json", operator_counts)
            rows = [row for row in rows if row["run_id"] != result["run_id"]]
            rows.append(result)
            rows.sort(key=lambda row: (str(row["instance"]), int(row["seed"]), str(row["algorithm"])))
            _atomic_csv(raw_path, rows)
    return _finalize(output_dir, rows, metadata)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--output-dir",
        default="baselines/e2_alns/e2_loss_recovery_20260711/unseen_seed_4000_gate",
    )
    parser.add_argument("--eval-budget", type=int, default=4000)
    parser.add_argument("--max-runtime-seconds", type=float, default=1800.0)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
