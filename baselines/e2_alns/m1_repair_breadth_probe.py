"""Bounded probe: halve exact insertion breadth on the two costly hard-case paths."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns.m1_dominant_pair_autopsy import run_probe as run_autopsy
from baselines.e2_alns.m1_joint_repack_fleet_headroom import _sha256, _write_csv, evidence_files
from setp_solver.algorithms.resetp_alns.operators import feasible_repair


DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_repair_breadth_20260710")
REFERENCE_DIR = Path("baselines/e2_alns/m1_dominant_pair_autopsy_20260710")


def classify(rows: list[dict[str, object]]) -> str:
    if not rows or not all(bool(row["clean"]) for row in rows):
        return "REPAIR_BREADTH_2_NOT_SUPPORTED"
    if all(float(row["cost_delta"]) <= 1e-9 for row in rows) and sum(float(row["runtime_delta"]) for row in rows) < 0:
        return "REPAIR_BREADTH_2_SUPPORTED"
    return "REPAIR_BREADTH_2_NOT_SUPPORTED"


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    original = feasible_repair.enumerate_feasible_insertions

    def narrowed(*call_args: object, **call_kwargs: object):
        call_kwargs["max_route_candidates"] = 2
        return original(*call_args, **call_kwargs)

    nested = argparse.Namespace(**vars(args))
    nested.output_dir = args.output_dir / "candidate"
    with patch.object(feasible_repair, "enumerate_feasible_insertions", narrowed):
        run_autopsy(nested)

    def read_rows(path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    reference = {int(row["seed"]): row for row in read_rows(repo_root / args.reference_dir / "raw_runs.csv")}
    candidate = {int(row["seed"]): row for row in read_rows(output_dir / "candidate/raw_runs.csv")}
    rows: list[dict[str, object]] = []
    for seed in sorted(candidate):
        before = reference[seed]
        after = candidate[seed]
        rows.append(
            {
                "seed": seed,
                "reference_cost": float(before["best_cost"]),
                "candidate_cost": float(after["best_cost"]),
                "cost_delta": float(after["best_cost"]) - float(before["best_cost"]),
                "reference_seconds": float(before["elapsed_seconds"]),
                "candidate_seconds": float(after["elapsed_seconds"]),
                "runtime_delta": float(after["elapsed_seconds"]) - float(before["elapsed_seconds"]),
                "clean": int(after["actual_evaluations"]) == int(args.eval_budget) and int(after["violation_count"]) == 0,
            }
        )
    _write_csv(output_dir / "raw_runs.csv", rows)
    verdict = classify(rows)
    decision = {
        "schema_version": "setp-m1-repair-breadth.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "comparison_count": len(rows),
        "mean_cost_delta": sum(float(row["cost_delta"]) for row in rows) / len(rows),
        "mean_runtime_delta": sum(float(row["runtime_delta"]) for row in rows) / len(rows),
    }
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "metadata.json").write_text(
        json.dumps(
            {
                **decision,
                "reference_dir": str(args.reference_dir),
                "candidate_route_limit": 2,
                "eval_budget": int(args.eval_budget),
                "seeds": str(args.seeds),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        f"# M1 repair breadth probe\n\nVerdict: `{verdict}`. This is a two-seed hard-case speed/quality diagnostic, not a benchmark claim.\n",
        encoding="utf-8",
    )
    sources = [Path(__file__).resolve(), feasible_repair.__file__ and Path(feasible_repair.__file__).resolve()]
    paths = [path for path in sources if isinstance(path, Path)]
    hashes = {str(path.relative_to(repo_root)): _sha256(path) for path in [*evidence_files(output_dir), *paths] if path.is_file()}
    (output_dir / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reference-dir", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--seeds", default="1,2")
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--max-runtime-seconds", type=float, default=180.0)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    args = parser.parse_args()
    print(json.dumps(run_probe(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
