#!/usr/bin/env python3
"""Run functional and cheapest three-arm development gates."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[3]
SOLVER_SRC = REPO / "solver/src"
HERE = Path(__file__).resolve().parent
for path in (SOLVER_SRC, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prototype import independent_cost, run_combined, run_outer_search, run_pure_alns  # noqa: E402


DEFAULT_BUNDLES = (
    REPO / "baselines/e2_alns/homberger_200_development_bundles_20260717/C1_2_1",
    REPO / "baselines/e2_alns/homberger_200_development_bundles_20260717/R1_2_8",
    REPO / "baselines/e2_alns/homberger_200_development_bundles_20260717/RC2_2_8",
)
FUNCTIONAL_BUNDLE = (
    REPO
    / "models/data_bundle/generated_instances/L-main_mixed23_archive_20260709"
    / "L-main-multidepot-10c-01"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def row_for(
    bundle: Path,
    seed: int,
    budget: int,
    algorithm: str,
    *,
    outer_share: float = 0.25,
    inner_basins: int = 1,
) -> dict[str, Any]:
    if algorithm == "pure_alns":
        result = run_pure_alns(bundle, seed=seed, eval_budget=budget)
    elif algorithm == "pure_hgs_style_outer":
        result = run_outer_search(bundle, seed=seed, eval_budget=budget)
    elif algorithm == "mechanism_hgs_alns_skeleton":
        result = run_combined(
            bundle,
            seed=seed,
            eval_budget=budget,
            outer_share=outer_share,
            inner_basins=inner_basins,
        )
    else:
        raise ValueError(algorithm)
    recomputed = independent_cost(bundle, result.best_solution)
    return {
        "instance": bundle.name,
        "seed": seed,
        "budget": budget,
        "algorithm": result.algorithm,
        "cost": result.best_cost,
        "recomputed_cost": recomputed,
        "cost_match": abs(result.best_cost - recomputed) <= 1e-7,
        "evaluations": result.evaluations,
        "budget_exact": result.evaluations == budget,
        "elapsed_seconds": result.elapsed_seconds,
        "route_count": result.route_count,
        "feasible": result.feasible,
        "mechanism_activity": json.dumps(result.mechanism_activity, sort_keys=True),
    }


def decide(rows: list[dict[str, Any]], *, performance_mode: bool) -> dict[str, Any]:
    accounting_pass = all(
        row["budget_exact"] and row["cost_match"] and row["feasible"]
        for row in rows
    )
    if not performance_mode:
        return {
            "decision": "PASS_SKELETON_FUNCTION_AND_ACCOUNTING_ONLY" if accounting_pass else "HALT_SKELETON_ACCOUNTING",
            "accounting_passed": accounting_pass,
            "strong_effect": False,
            "formal_search_allowed": False,
        }
    paired = []
    for instance in sorted({str(row["instance"]) for row in rows}):
        for seed in sorted({int(row["seed"]) for row in rows if row["instance"] == instance}):
            group = {
                str(row["algorithm"]): float(row["recomputed_cost"])
                for row in rows
                if row["instance"] == instance and int(row["seed"]) == seed
            }
            if len(group) != 3:
                continue
            combo = group["mechanism_hgs_alns_skeleton"]
            paired.append(
                {
                    "instance": instance,
                    "seed": seed,
                    "beats_alns": combo < group["pure_alns"] - 1e-9,
                    "beats_hgs": combo < group["pure_hgs_style_outer"] - 1e-9,
                    "combo_cost": combo,
                    "alns_cost": group["pure_alns"],
                    "hgs_cost": group["pure_hgs_style_outer"],
                }
            )
    double_wins = sum(row["beats_alns"] and row["beats_hgs"] for row in paired)
    strong = accounting_pass and bool(paired) and double_wins == len(paired)
    return {
        "decision": "STRONG_POSITIVE_REQUEST_FORMAL_APPROVAL" if strong else "HOLD_REDESIGN_NOT_DOUBLE_WIN",
        "accounting_passed": accounting_pass,
        "strong_effect": strong,
        "formal_search_allowed": False,
        "double_wins": double_wins,
        "paired_tasks": len(paired),
        "paired_details": paired,
        "rule": "Every paired task must beat both pure arms; ties do not pass.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--functional", action="store_true")
    parser.add_argument("--budget", type=int, default=120)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--bundles", nargs="*", type=Path)
    parser.add_argument("--outer-share", type=float, default=0.25)
    parser.add_argument("--inner-basins", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, default=HERE)
    args = parser.parse_args()
    bundles = tuple(path.resolve() for path in (args.bundles or DEFAULT_BUNDLES))
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if args.functional:
        for budget in (0, 1, 2, 5):
            for algorithm in ("pure_hgs_style_outer", "mechanism_hgs_alns_skeleton"):
                rows.append(
                    row_for(
                        FUNCTIONAL_BUNDLE,
                        1,
                        budget,
                        algorithm,
                        outer_share=args.outer_share,
                        inner_basins=args.inner_basins,
                    )
                )
    else:
        seeds = tuple(int(item) for item in args.seeds.split(",") if item.strip())
        for bundle in bundles:
            for seed in seeds:
                for algorithm in ("pure_alns", "pure_hgs_style_outer", "mechanism_hgs_alns_skeleton"):
                    rows.append(
                        row_for(
                            bundle,
                            seed,
                            args.budget,
                            algorithm,
                            outer_share=args.outer_share,
                            inner_basins=args.inner_basins,
                        )
                    )

    fieldnames = [
        "instance", "seed", "budget", "algorithm", "cost", "recomputed_cost",
        "cost_match", "evaluations", "budget_exact", "elapsed_seconds",
        "route_count", "feasible", "mechanism_activity",
    ]
    with (out / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    decision = decide(rows, performance_mode=not args.functional)
    write_json(out / "decision.json", decision)
    write_json(
        out / "metadata.json",
        {
            "development_only": True,
            "formal_search_allowed": False,
            "mode": "functional" if args.functional else "three_arm_performance",
            "bundles": (
                [str(FUNCTIONAL_BUNDLE.relative_to(REPO))]
                if args.functional
                else [str(path.relative_to(REPO)) for path in bundles]
            ),
            "budget": None if args.functional else args.budget,
            "outer_share": args.outer_share,
            "inner_basins": args.inner_basins,
            "seeds": [1] if args.functional else [int(item) for item in args.seeds.split(",") if item.strip()],
            "protected_files_modified": False,
        },
    )
    report = [
        "# Mechanism HGS--ALNS isolated gate",
        "",
        f"- Decision: `{decision['decision']}`",
        "- Scope: development only; formal search remains forbidden.",
        "- Comparison rule: same bundle, paired seed, exact complete-evaluation budget, independent final recomputation.",
        "",
        "The current implementation tests only the outer-population plus ALNS-education skeleton. "
        "The four mechanism-specific prototypes remain isolated until this skeleton passes the double-win gate.",
    ]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    hashes = {
        path.name: sha256(path)
        for path in sorted(out.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    write_json(out / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["accounting_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
