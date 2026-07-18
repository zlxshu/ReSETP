#!/usr/bin/env python3
"""Run the cheapest four-arm gate for the official-HGS-backed candidate."""

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
from prototype import independent_cost, run_pure_alns  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from v2_solver import (  # noqa: E402
    ORIGINAL_ALNS_COMMIT,
    run_mechanism_hgs_alns_v2,
    run_official_hgs_neutral,
    run_original_n_wouda_alns_neutral,
)


DEFAULT_BUNDLES = (
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-25c-01",
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-50c-01",
)
ALGORITHMS = (
    "official_vidal_hgs_neutral_resetp_adapter",
    "original_n_wouda_alns_7_0_0_neutral_resetp_adapter",
    "current_project_alns",
    "mechanism_hgs_alns_v2",
)
CANDIDATE = "mechanism_hgs_alns_v2"


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
        "official_vidal_hgs_neutral_resetp_adapter": run_official_hgs_neutral,
        "original_n_wouda_alns_7_0_0_neutral_resetp_adapter": (
            run_original_n_wouda_alns_neutral
        ),
        "current_project_alns": run_pure_alns,
        "mechanism_hgs_alns_v2": run_mechanism_hgs_alns_v2,
    }
    kwargs: dict[str, Any] = {
        "seed": int(seed),
        "eval_budget": int(budget),
        "prices": prices,
    }
    if algorithm == CANDIDATE:
        kwargs.update(
            {
                "hgs_share": float(hgs_share),
                "mechanism_share": float(mechanism_share),
            }
        )
    result = runners[algorithm](bundle, **kwargs)
    recomputed = independent_cost(bundle, result.best_solution, prices)
    loaded = load_search_bundle(bundle)
    violations = check_solution(result.best_solution, loaded.instance, prices)
    activity = dict(result.mechanism_activity)
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
            activity,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def _candidate_expert_improvements(row: dict[str, Any]) -> int:
    activity = json.loads(str(row["mechanism_activity"]))
    expert = activity.get("expert_activity", {})
    return int(expert.get("depot_expert_improvements", 0)) + int(
        expert.get("fleet_charge_expert_improvements", 0)
    )


def _candidate_official_hgs_calls(row: dict[str, Any]) -> int:
    activity = json.loads(str(row["mechanism_activity"]))
    hgs = activity.get("hgs_activity", {})
    return int(hgs.get("hgs_native_calls", 0))


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
            {
                int(row["seed"])
                for row in rows
                if str(row["instance"]) == instance
            }
        )
        for seed in seeds:
            group = {
                str(row["algorithm"]): row
                for row in rows
                if str(row["instance"]) == instance and int(row["seed"]) == seed
            }
            if set(group) != set(ALGORITHMS):
                continue
            candidate = group[CANDIDATE]
            candidate_cost = float(candidate["recomputed_cost"])
            controls = {
                algorithm: float(group[algorithm]["recomputed_cost"])
                for algorithm in ALGORITHMS
                if algorithm != CANDIDATE
            }
            expert_improvements = _candidate_expert_improvements(candidate)
            official_hgs_calls = _candidate_official_hgs_calls(candidate)
            strict_wins = {
                algorithm: candidate_cost < cost - 1.0e-9
                for algorithm, cost in controls.items()
            }
            paired.append(
                {
                    "instance": instance,
                    "seed": seed,
                    "candidate_cost": candidate_cost,
                    "control_costs": controls,
                    "strict_wins": strict_wins,
                    "strict_triple_win": all(strict_wins.values()),
                    "expert_improvements": expert_improvements,
                    "mechanism_effect_active": expert_improvements > 0,
                    "official_hgs_calls": official_hgs_calls,
                    "official_hgs_backbone_active": official_hgs_calls > 0,
                }
            )
    strict_triple_wins = sum(
        bool(row["strict_triple_win"]) for row in paired
    )
    mechanism_active_pairs = sum(
        bool(row["mechanism_effect_active"]) for row in paired
    )
    hgs_active_pairs = sum(
        bool(row["official_hgs_backbone_active"]) for row in paired
    )
    strong = (
        accounting_passed
        and bool(paired)
        and strict_triple_wins == len(paired)
        and mechanism_active_pairs == len(paired)
        and hgs_active_pairs == len(paired)
    )
    return {
        "decision": (
            "STRONG_POSITIVE_ELIGIBLE_TO_REQUEST_NEXT_APPROVAL"
            if strong
            else "HOLD_STRICT_OR_MECHANISM_GATE_NOT_MET"
        ),
        "formal_search_allowed": False,
        "accounting_passed": accounting_passed,
        "strong_effect": strong,
        "paired_tasks": len(paired),
        "strict_triple_wins": strict_triple_wins,
        "mechanism_active_pairs": mechanism_active_pairs,
        "official_hgs_active_pairs": hgs_active_pairs,
        "rule": (
            "Every paired task must strictly beat the pinned official HGS neutral "
            "adapter, the pinned original N-Wouda ALNS neutral adapter, and the "
            "current project ALNS. The candidate must also use official HGS and "
            "obtain at least one accepted mechanism-expert improvement. Ties fail."
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
    fields = [
        "instance",
        "seed",
        "budget",
        "algorithm",
        "reported_algorithm",
        "cost",
        "recomputed_cost",
        "cost_match",
        "evaluations",
        "budget_exact",
        "elapsed_seconds",
        "route_count",
        "feasible",
        "violation_count",
        "mechanism_activity",
    ]
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
            "schema_version": "resetp.mechanism-hgs-alns-v2-gate.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval": "EA-HGS-002",
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
            "original_alns_commit": ORIGINAL_ALNS_COMMIT,
            "strict_gate": decision["rule"],
            "claim_boundary": (
                "Non-formal mechanism-active ReSETP development evidence only. "
                "The official HGS control is the unmodified symmetric-CVRP core "
                "plus a neutral frozen-depot translation layer, not an upstream "
                "solver for the full ReSETP model."
            ),
        },
    )
    report_lines = [
        "# 官方原算法四方最低成本开发门",
        "",
        "本门只做非正式开发淘汰，不放行 E2、China81 或阶段二。",
        "",
        f"- 判定：`{decision['decision']}`",
        f"- 成本与预算账通过：`{decision['accounting_passed']}`",
        (
            f"- 严格三胜：{decision['strict_triple_wins']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- 专用办法实际带来改进：{decision['mechanism_active_pairs']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- 官方 HGS 主体实际调用：{decision['official_hgs_active_pairs']}/"
            f"{decision['paired_tasks']}"
        ),
        "",
        "通过条件：新算法在每个同题同种子的配对任务中，都必须同时严格胜过"
        "官方 HGS 中性适配、原版 N-Wouda ALNS 中性适配和当前项目 ALNS；"
        "同时官方 HGS 主体必须真的运行，至少一个机制专用办法必须真的改善最终方案。"
        "平局仍按失败。",
        "",
        "官方 HGS 原代码不懂多车场、车型、充电、碳和公平。控制臂只加了相同的"
        "数据翻译层，没有加入任何自研办法；最终成本统一由 ReSETP 计分器复算。",
    ]
    (out / "report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )
    files = []
    for path in sorted(out.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
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
    parser.add_argument("--budget", type=int, default=30)
    parser.add_argument("--seeds", default="1")
    parser.add_argument("--bundles", nargs="*", type=Path)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--hgs-share", type=float, default=0.08)
    parser.add_argument("--mechanism-share", type=float, default=0.12)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=HERE / "official_v2_cheapest_gate",
    )
    args = parser.parse_args()
    if args.budget <= 0:
        raise ValueError("performance gate budget must be positive")
    bundles = tuple(
        path.resolve() for path in (args.bundles or DEFAULT_BUNDLES)
    )
    seeds = tuple(
        int(value) for value in args.seeds.split(",") if value.strip()
    )
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=float(args.battery_kwh),
    )
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
