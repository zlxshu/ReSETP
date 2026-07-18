#!/usr/bin/env python3
"""Cheap component ablation for the mechanism HGS-ALNS v2 candidate.

This development-only gate asks two narrow questions under one exact
complete-evaluation budget:

1. Does the complete candidate beat the same candidate with official HGS
   removed and its budget returned to ALNS?
2. Does it beat the same candidate with the mechanism experts removed and
   their budget returned to ALNS?

It does not authorize E2, China81, or any formal experiment.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable


REPO = Path(__file__).resolve().parents[3]
SOLVER_SRC = REPO / "solver/src"
HERE = Path(__file__).resolve().parent
REFERENCE_ALNS = REPO / "Reference Algorithm" / "ALNS-7.0.0@N-Wouda"
for path in (SOLVER_SRC, HERE, REFERENCE_ALNS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from official_hgs_resetp_adapter import (  # noqa: E402
    OFFICIAL_COMMIT,
    OFFICIAL_LIBRARY,
    OFFICIAL_LIBRARY_SHA256,
)
from prototype import independent_cost  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from v2_solver import (  # noqa: E402
    run_mechanism_hgs_alns_v2,
    run_mechanism_hgs_alns_v2_without_experts,
    run_mechanism_hgs_alns_v2_without_hgs,
)


DEFAULT_BUNDLES = (
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-25c-01",
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-50c-01",
)
FULL = "mechanism_hgs_alns_v2"
WITHOUT_HGS = "mechanism_hgs_alns_v2_without_hgs_ablation"
WITHOUT_EXPERTS = "mechanism_hgs_alns_v2_without_experts_ablation"
ALGORITHMS = (FULL, WITHOUT_HGS, WITHOUT_EXPERTS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def run_arm(
    *,
    algorithm: str,
    bundle: Path,
    seed: int,
    budget: int,
    prices: Any,
    hgs_share: float,
    mechanism_share: float,
) -> dict[str, Any]:
    runners: dict[str, Callable[..., Any]] = {
        FULL: run_mechanism_hgs_alns_v2,
        WITHOUT_HGS: run_mechanism_hgs_alns_v2_without_hgs,
        WITHOUT_EXPERTS: run_mechanism_hgs_alns_v2_without_experts,
    }
    result = runners[algorithm](
        bundle,
        seed=seed,
        eval_budget=budget,
        prices=prices,
        hgs_share=hgs_share,
        mechanism_share=mechanism_share,
    )
    recomputed = independent_cost(bundle, result.best_solution, prices)
    loaded = load_search_bundle(bundle)
    violations = check_solution(result.best_solution, loaded.instance, prices)
    return {
        "instance": bundle.name,
        "seed": int(seed),
        "budget": int(budget),
        "algorithm": algorithm,
        "reported_algorithm": result.algorithm,
        "cost": float(result.best_cost),
        "recomputed_cost": float(recomputed),
        "cost_match": abs(float(result.best_cost) - recomputed) <= 1.0e-7,
        "evaluations": int(result.evaluations),
        "budget_exact": int(result.evaluations) == int(budget),
        "elapsed_seconds": float(result.elapsed_seconds),
        "route_count": int(result.route_count),
        "feasible": bool(result.feasible and not violations),
        "violation_count": len(violations),
        "mechanism_activity": json.dumps(
            result.mechanism_activity,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def decide(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accounting_passed = all(
        bool(row["budget_exact"])
        and bool(row["cost_match"])
        and bool(row["feasible"])
        and int(row["violation_count"]) == 0
        for row in rows
    )
    paired: list[dict[str, Any]] = []
    for instance in sorted({str(row["instance"]) for row in rows}):
        seeds = sorted(
            int(row["seed"])
            for row in rows
            if str(row["instance"]) == instance
        )
        for seed in sorted(set(seeds)):
            group = {
                str(row["algorithm"]): row
                for row in rows
                if str(row["instance"]) == instance and int(row["seed"]) == seed
            }
            if set(group) != set(ALGORITHMS):
                continue
            full = group[FULL]
            full_cost = float(full["recomputed_cost"])
            no_hgs_cost = float(group[WITHOUT_HGS]["recomputed_cost"])
            no_experts_cost = float(group[WITHOUT_EXPERTS]["recomputed_cost"])
            activity = json.loads(str(full["mechanism_activity"]))
            warm_cost = float(activity.get("warm_cost", full_cost))
            skeleton_cost = float(activity.get("skeleton_cost", warm_cost))
            hgs_calls = int(
                activity.get("hgs_activity", {}).get("hgs_native_calls", 0)
            )
            expert = activity.get("expert_activity", {})
            expert_improvements = int(
                expert.get("depot_expert_improvements", 0)
            ) + int(expert.get("fleet_charge_expert_improvements", 0))
            hgs_ablation_win = full_cost < no_hgs_cost - 1.0e-9
            expert_ablation_win = full_cost < no_experts_cost - 1.0e-9
            paired.append(
                {
                    "instance": instance,
                    "seed": seed,
                    "full_cost": full_cost,
                    "without_hgs_cost": no_hgs_cost,
                    "without_experts_cost": no_experts_cost,
                    "full_beats_without_hgs": hgs_ablation_win,
                    "full_beats_without_experts": expert_ablation_win,
                    "strict_double_ablation_win": (
                        hgs_ablation_win and expert_ablation_win
                    ),
                    "warm_cost": warm_cost,
                    "hgs_skeleton_cost": skeleton_cost,
                    "hgs_skeleton_improved_warm": (
                        skeleton_cost < warm_cost - 1.0e-9
                    ),
                    "official_hgs_calls": hgs_calls,
                    "expert_improvements": expert_improvements,
                }
            )
    hgs_wins = sum(bool(row["full_beats_without_hgs"]) for row in paired)
    expert_wins = sum(
        bool(row["full_beats_without_experts"]) for row in paired
    )
    double_wins = sum(
        bool(row["strict_double_ablation_win"]) for row in paired
    )
    hgs_skeleton_improvements = sum(
        bool(row["hgs_skeleton_improved_warm"]) for row in paired
    )
    strong = (
        accounting_passed
        and bool(paired)
        and double_wins == len(paired)
        and all(int(row["official_hgs_calls"]) > 0 for row in paired)
        and all(int(row["expert_improvements"]) > 0 for row in paired)
    )
    return {
        "decision": (
            "COMPONENT_STORY_SUPPORTED_ON_SMALL_DEVELOPMENT_SET"
            if strong
            else "HOLD_COMPONENT_CONTRIBUTION_NOT_PROVEN"
        ),
        "formal_search_allowed": False,
        "accounting_passed": accounting_passed,
        "strong_effect": strong,
        "paired_tasks": len(paired),
        "full_beats_without_hgs": hgs_wins,
        "full_beats_without_experts": expert_wins,
        "strict_double_ablation_wins": double_wins,
        "hgs_skeleton_improvements": hgs_skeleton_improvements,
        "rule": (
            "On every same-instance same-seed task, the full candidate must "
            "strictly beat both equal-budget ablations. Official HGS must be "
            "called and a mechanism expert must improve the solution. Ties fail."
        ),
        "paired_details": paired,
    }


def write_records(
    *,
    out: Path,
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
    bundles: tuple[Path, ...],
    seeds: tuple[int, ...],
    budget: int,
    battery_kwh: float,
    hgs_share: float,
    mechanism_share: float,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with (out / "raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write_json(out / "decision.json", decision)
    write_json(
        out / "metadata.json",
        {
            "schema_version": "resetp.mechanism-hgs-alns-v2-ablation.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval": "EA-HGS-002-development-only",
            "development_only": True,
            "formal_search_allowed": False,
            "algorithms": list(ALGORITHMS),
            "bundles": [str(path.relative_to(REPO)) for path in bundles],
            "seeds": list(seeds),
            "complete_evaluation_budget_per_arm": int(budget),
            "battery_kwh": float(battery_kwh),
            "candidate_hgs_share": float(hgs_share),
            "candidate_mechanism_share": float(mechanism_share),
            "official_hgs_commit": OFFICIAL_COMMIT,
            "official_hgs_library": str(OFFICIAL_LIBRARY.relative_to(REPO)),
            "official_hgs_library_sha256": OFFICIAL_LIBRARY_SHA256,
            "strict_gate": decision["rule"],
            "claim_boundary": (
                "Small development ablation only. It tests whether each named "
                "component adds value under the same complete-evaluation budget; "
                "it does not authorize formal experiments."
            ),
        },
    )
    report = [
        "# HGS 与机制办法拆件验证",
        "",
        "本门只回答两个问题：拿掉 HGS 会不会变差，拿掉机制专用办法会不会变差。",
        "所有版本使用相同题目、种子、总计分次数和统一复算。",
        "",
        f"- 判定：`{decision['decision']}`",
        f"- 账目通过：`{decision['accounting_passed']}`",
        (
            f"- 完整版胜过去掉 HGS：{decision['full_beats_without_hgs']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- 完整版胜过去掉机制办法："
            f"{decision['full_beats_without_experts']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- 两项同时严格胜出："
            f"{decision['strict_double_ablation_wins']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- HGS 先手方案直接改善起点："
            f"{decision['hgs_skeleton_improvements']}/"
            f"{decision['paired_tasks']}"
        ),
        "",
        "任何平局都不算贡献。若本门失败，不能把当前版本写成每个组件都有效的"
        "HGS-ALNS 创新算法。",
    ]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    files = []
    for path in sorted(out.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        ):
            files.append(
                {
                    "path": str(path.relative_to(out)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    write_json(
        out / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "files": files,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--bundles", nargs="*", type=Path)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--hgs-share", type=float, default=0.02)
    parser.add_argument("--mechanism-share", type=float, default=0.12)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=HERE / "official_v2_b100_component_ablation",
    )
    args = parser.parse_args()
    if args.budget <= 0:
        raise ValueError("ablation budget must be positive")
    bundles = tuple(
        path.resolve() for path in (args.bundles or DEFAULT_BUNDLES)
    )
    seeds = tuple(
        int(value) for value in args.seeds.split(",") if value.strip()
    )
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ALGORITHMS:
                rows.append(
                    run_arm(
                        algorithm=algorithm,
                        bundle=bundle,
                        seed=seed,
                        budget=int(args.budget),
                        prices=prices,
                        hgs_share=float(args.hgs_share),
                        mechanism_share=float(args.mechanism_share),
                    )
                )
    decision = decide(rows)
    write_records(
        out=args.out_dir.resolve(),
        rows=rows,
        decision=decision,
        bundles=bundles,
        seeds=seeds,
        budget=int(args.budget),
        battery_kwh=float(args.battery_kwh),
        hgs_share=float(args.hgs_share),
        mechanism_share=float(args.mechanism_share),
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["accounting_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
