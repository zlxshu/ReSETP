"""Probe whether UCB reward-scale mismatch causes the hard-case lock-in."""

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
import setp_solver.algorithms.resetp_alns.kernel.winner as winner
from setp_solver.algorithms.resetp_alns.runtime.select import AlphaUCB


DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_normalized_ucb_20260710")
REFERENCE_DIR = Path("baselines/e2_alns/m1_dominant_pair_autopsy_20260710")


def _normalized_selector(num_destroy: int, num_repair: int, **kwargs: object) -> AlphaUCB:
    return AlphaUCB(
        [1.0, 0.4, 0.1, 0.0025],
        alpha=0.08,
        num_destroy=num_destroy,
        num_repair=num_repair,
        op_coupling=kwargs.get("op_coupling"),
    )


def classify(rows: list[dict[str, object]]) -> str:
    if not rows or not all(bool(row["clean"]) for row in rows):
        return "NORMALIZED_UCB_NOT_SUPPORTED"
    wins = sum(float(row["cost_delta"]) < -1e-9 for row in rows)
    mean_cost = sum(float(row["cost_delta"]) for row in rows) / len(rows)
    mean_time = sum(float(row["runtime_delta"]) for row in rows) / len(rows)
    if wins >= 2 and mean_cost < -1e-9 and mean_time < -1e-9:
        return "NORMALIZED_UCB_SUPPORTED"
    return "NORMALIZED_UCB_NOT_SUPPORTED"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    nested = argparse.Namespace(**vars(args))
    nested.output_dir = args.output_dir / "candidate"
    with patch.object(winner, "_make_operator_selector", _normalized_selector):
        run_autopsy(nested)

    reference = {int(row["seed"]): row for row in _read(repo_root / args.reference_dir / "raw_runs.csv")}
    candidate = {int(row["seed"]): row for row in _read(output_dir / "candidate/raw_runs.csv")}
    rows: list[dict[str, object]] = []
    for seed in sorted(candidate):
        before, after = reference[seed], candidate[seed]
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
        "schema_version": "setp-m1-normalized-ucb.v1",
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
        json.dumps({**decision, "reference_dir": str(args.reference_dir), "scores": [1.0, 0.4, 0.1, 0.0025]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        f"# M1 normalized UCB probe\n\nVerdict: `{verdict}`. Hard-instance diagnostic only; no benchmark claim.\n",
        encoding="utf-8",
    )
    sources = [Path(__file__).resolve(), Path(winner.__file__).resolve()]
    hashes = {str(path.relative_to(repo_root)): _sha256(path) for path in [*evidence_files(output_dir), *sources] if path.is_file()}
    (output_dir / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reference-dir", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--max-runtime-seconds", type=float, default=180.0)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    args = parser.parse_args()
    print(json.dumps(run_probe(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
