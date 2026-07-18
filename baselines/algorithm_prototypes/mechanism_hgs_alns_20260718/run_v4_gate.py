#!/usr/bin/env python3
"""Minimal five-arm gate for the mechanism-first ALNS candidate.

The three unchanged controls are reused from the verified B100 confirmation
artifact.  Only the full v4 candidate and its joint-decoder ablation are run
again.  This keeps the gate cheap without changing any comparison condition.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import median
import sys
from typing import Any, Callable


REPO = Path(__file__).resolve().parents[3]
SOLVER_SRC = REPO / "solver/src"
HERE = Path(__file__).resolve().parent
REFERENCE_ALNS = REPO / "Reference Algorithm" / "ALNS-7.0.0@N-Wouda"
for path in (SOLVER_SRC, HERE, REFERENCE_ALNS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prototype import independent_cost  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from v4_mechanism_alns_solver import (  # noqa: E402
    run_mechanism_alns_v4,
    run_mechanism_alns_v4_without_joint,
)


CONTROL_SOURCE = HERE / "official_v2_b100_confirmation_gate"
DEFAULT_BUNDLES = (
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-20c-01",
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-25c-01",
    REPO
    / "models/data_bundle/generated_instances/L-main_size_preserving_v2_archive_20260710"
    / "L-main-threeshift-50c-01",
)
OFFICIAL_HGS = "official_vidal_hgs_neutral_resetp_adapter"
ORIGINAL_ALNS = "original_n_wouda_alns_7_0_0_neutral_resetp_adapter"
CURRENT_ALNS = "current_project_alns"
FULL = "mechanism_alns_v4"
WITHOUT_JOINT = "mechanism_alns_v4_without_joint_ablation"
CONTROLS = (OFFICIAL_HGS, ORIGINAL_ALNS, CURRENT_ALNS)
ALGORITHMS = (*CONTROLS, FULL, WITHOUT_JOINT)


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


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_verified_controls(
    *,
    bundles: tuple[Path, ...],
    seeds: tuple[int, ...],
    budget: int,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    raw_path = CONTROL_SOURCE / "raw_runs.csv"
    manifest_path = CONTROL_SOURCE / "artifact_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        str(item["path"]): str(item["sha256"])
        for item in manifest.get("files", [])
    }.get("raw_runs.csv")
    actual = sha256(raw_path)
    if not expected or expected != actual:
        raise RuntimeError("control source raw_runs.csv hash verification failed")
    wanted_instances = {path.name for path in bundles}
    rows: list[dict[str, Any]] = []
    with raw_path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            if (
                raw["algorithm"] not in CONTROLS
                or raw["instance"] not in wanted_instances
                or int(raw["seed"]) not in seeds
                or int(raw["budget"]) != int(budget)
            ):
                continue
            rows.append(
                {
                    "instance": raw["instance"],
                    "seed": int(raw["seed"]),
                    "budget": int(raw["budget"]),
                    "algorithm": raw["algorithm"],
                    "reported_algorithm": raw["reported_algorithm"],
                    "cost": float(raw["cost"]),
                    "recomputed_cost": float(raw["recomputed_cost"]),
                    "cost_match": _bool(raw["cost_match"]),
                    "evaluations": int(raw["evaluations"]),
                    "budget_exact": _bool(raw["budget_exact"]),
                    "elapsed_seconds": float(raw["elapsed_seconds"]),
                    "route_count": int(raw["route_count"]),
                    "feasible": _bool(raw["feasible"]),
                    "violation_count": int(raw["violation_count"]),
                    "mechanism_activity": raw["mechanism_activity"],
                    "evidence_origin": str(
                        raw_path.relative_to(REPO)
                    ),
                }
            )
    expected_rows = len(bundles) * len(seeds) * len(CONTROLS)
    if len(rows) != expected_rows:
        raise RuntimeError(
            f"control source coverage mismatch: {len(rows)}/{expected_rows}"
        )
    return rows, {
        "control_raw_runs": str(raw_path.relative_to(REPO)),
        "control_raw_runs_sha256": actual,
        "control_artifact_manifest": str(manifest_path.relative_to(REPO)),
        "control_artifact_manifest_sha256": sha256(manifest_path),
    }


def run_new_arm(
    *,
    algorithm: str,
    bundle: Path,
    seed: int,
    budget: int,
    prices: Any,
    depot_room: int,
) -> dict[str, Any]:
    runners: dict[str, Callable[..., Any]] = {
        FULL: run_mechanism_alns_v4,
        WITHOUT_JOINT: run_mechanism_alns_v4_without_joint,
    }
    result = runners[algorithm](
        bundle,
        seed=seed,
        eval_budget=budget,
        prices=prices,
        depot_room=depot_room,
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
        "evidence_origin": "current_v4_gate_run",
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
            full_cost = float(group[FULL]["recomputed_cost"])
            controls = {
                algorithm: float(group[algorithm]["recomputed_cost"])
                for algorithm in CONTROLS
            }
            without_joint = float(group[WITHOUT_JOINT]["recomputed_cost"])
            activity = json.loads(str(group[FULL]["mechanism_activity"]))
            joint = activity.get("joint_activity", {})
            open_source_wins = {
                OFFICIAL_HGS: full_cost < controls[OFFICIAL_HGS] - 1.0e-9,
                ORIGINAL_ALNS: full_cost < controls[ORIGINAL_ALNS] - 1.0e-9,
            }
            paired.append(
                {
                    "instance": instance,
                    "seed": seed,
                    "full_cost": full_cost,
                    "control_costs": controls,
                    "without_joint_cost": without_joint,
                    "beats_original_open_sources": all(
                        open_source_wins.values()
                    ),
                    "beats_current_project_alns": (
                        full_cost < controls[CURRENT_ALNS] - 1.0e-9
                    ),
                    "ties_current_project_alns": (
                        abs(full_cost - controls[CURRENT_ALNS]) <= 1.0e-9
                    ),
                    "beats_without_joint": (
                        full_cost < without_joint - 1.0e-9
                    ),
                    "joint_decoder_improved": int(
                        joint.get("improvements", 0)
                    )
                    > 0,
                    "joint_complete_evaluations": int(
                        joint.get("complete_evaluations", 0)
                    ),
                    "route_proxy_evaluations": int(
                        joint.get("route_proxy_evaluations", 0)
                    ),
                }
            )
    open_source_wins = sum(
        bool(row["beats_original_open_sources"]) for row in paired
    )
    current_wins = sum(
        bool(row["beats_current_project_alns"]) for row in paired
    )
    current_ties = sum(
        bool(row["ties_current_project_alns"]) for row in paired
    )
    ablation_wins = sum(bool(row["beats_without_joint"]) for row in paired)
    joint_improvements = sum(
        bool(row["joint_decoder_improved"]) for row in paired
    )
    full_contract = (
        accounting_passed
        and bool(paired)
        and open_source_wins == len(paired)
        and current_wins == len(paired)
        and ablation_wins == len(paired)
        and joint_improvements == len(paired)
    )
    non_saturated = [
        row for row in paired if "-20c-" not in str(row["instance"])
    ]
    non_saturated_strong = bool(non_saturated) and all(
        bool(row["beats_original_open_sources"])
        and bool(row["beats_current_project_alns"])
        and bool(row["beats_without_joint"])
        and bool(row["joint_decoder_improved"])
        for row in non_saturated
    )
    wall_clock_seconds_by_algorithm: dict[str, dict[str, float]] = {}
    for algorithm in ALGORITHMS:
        elapsed = [
            float(row["elapsed_seconds"])
            for row in rows
            if str(row["algorithm"]) == algorithm
        ]
        if elapsed:
            wall_clock_seconds_by_algorithm[algorithm] = {
                "median": round(float(median(elapsed)), 6),
                "total": round(float(sum(elapsed)), 6),
            }
    full_wall = wall_clock_seconds_by_algorithm.get(FULL, {}).get("total", 0.0)
    current_wall = wall_clock_seconds_by_algorithm.get(
        CURRENT_ALNS, {}
    ).get("total", 0.0)
    wall_clock_delta_percent = (
        round(100.0 * (full_wall / current_wall - 1.0), 3)
        if current_wall > 0.0
        else None
    )
    return {
        "decision": (
            "STRONG_FULL_SMALL_GATE"
            if full_contract
            else "HOLD_FULL_CONTRACT_SMALL_SATURATION_OR_COMPONENT_GAP"
        ),
        "formal_search_allowed": False,
        "accounting_passed": accounting_passed,
        "full_contract_passed": full_contract,
        "original_open_source_floor_met": (
            bool(paired) and open_source_wins == len(paired)
        ),
        "paired_tasks": len(paired),
        "original_open_source_double_wins": open_source_wins,
        "current_project_alns_strict_wins": current_wins,
        "current_project_alns_ties": current_ties,
        "joint_ablation_strict_wins": ablation_wins,
        "joint_decoder_improvements": joint_improvements,
        "non_saturated_25_50_strong": non_saturated_strong,
        "candidate_vs_current_total_wall_clock_percent": (
            wall_clock_delta_percent
        ),
        "wall_clock_seconds_by_algorithm": wall_clock_seconds_by_algorithm,
        "rule": (
            "Every pair must strictly beat both pinned original open-source "
            "controls, the current project ALNS, and the equal-budget joint-"
            "decoder ablation. The joint decoder must improve with one complete "
            "evaluation. Ties fail the full contract."
        ),
        "claim_boundary": (
            "This gate tests the joint fleet/charging component only. The "
            "cross-depot, fairness, carbon-price, and dynamic components remain "
            "unproven because these development bundles do not expose their "
            "required mechanisms."
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
    depot_room: int,
    source: dict[str, str],
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
            "schema_version": "resetp.mechanism-alns-v4-gate.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval": "EA-HGS-002-development-only-pivot",
            "development_only": True,
            "formal_search_allowed": False,
            "algorithms": list(ALGORITHMS),
            "bundles": [str(path.relative_to(REPO)) for path in bundles],
            "seeds": list(seeds),
            "complete_evaluation_budget_per_arm": int(budget),
            "battery_kwh": float(battery_kwh),
            "cross_depot_reserved_evaluations": int(depot_room),
            "control_reuse": source,
            "strict_gate": decision["rule"],
            "claim_boundary": decision["claim_boundary"],
        },
    )
    report = [
        "# 机制化 ALNS v4 最小五方门",
        "",
        "本门复用已核验且配置完全相同的三套控制结果，只新跑完整版和"
        "“拿掉整套车型—充电选择”的版本。",
        "",
        f"- 总判定：`{decision['decision']}`",
        f"- 预算、可行性与独立复算：`{decision['accounting_passed']}`",
        (
            f"- 同时胜过两套原装开源算法："
            f"{decision['original_open_source_double_wins']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- 严格胜过当前项目 ALNS："
            f"{decision['current_project_alns_strict_wins']}/"
            f"{decision['paired_tasks']}；平局 "
            f"{decision['current_project_alns_ties']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- 严格胜过拿掉联合选择的版本："
            f"{decision['joint_ablation_strict_wins']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- 联合选择实际改善："
            f"{decision['joint_decoder_improvements']}/"
            f"{decision['paired_tasks']}"
        ),
        (
            f"- 25/50 客户非饱和小面强信号："
            f"`{decision['non_saturated_25_50_strong']}`"
        ),
        (
            "- 九任务总墙钟：完整版 "
            f"{decision['wall_clock_seconds_by_algorithm'][FULL]['total']:.3f} "
            "秒，当前项目 ALNS "
            f"{decision['wall_clock_seconds_by_algorithm'][CURRENT_ALNS]['total']:.3f} "
            "秒，完整版约慢 "
            f"{decision['candidate_vs_current_total_wall_clock_percent']:.1f}%；"
            "官方 HGS 对照 "
            f"{decision['wall_clock_seconds_by_algorithm'][OFFICIAL_HGS]['total']:.3f} "
            "秒，原装 ALNS 对照 "
            f"{decision['wall_clock_seconds_by_algorithm'][ORIGINAL_ALNS]['total']:.3f} "
            "秒。单任务中位数依次为 "
            f"{decision['wall_clock_seconds_by_algorithm'][FULL]['median']:.3f}、"
            f"{decision['wall_clock_seconds_by_algorithm'][CURRENT_ALNS]['median']:.3f}、"
            f"{decision['wall_clock_seconds_by_algorithm'][OFFICIAL_HGS]['median']:.3f}、"
            f"{decision['wall_clock_seconds_by_algorithm'][ORIGINAL_ALNS]['median']:.3f} "
            "秒。该短门墙钟只用于如实记账，不作正式速度结论。"
        ),
        "",
        "边界：这里只证明车型与充电联合选择。多车场责任、公平、碳价冲突和"
        "动态重规划尚未在相应机制数据上证明，不能写成已经完成。",
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
    parser.add_argument("--depot-room", type=int, default=2)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=HERE / "mechanism_v4_b100_minimal_gate",
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
    controls, source = load_verified_controls(
        bundles=bundles,
        seeds=seeds,
        budget=int(args.budget),
    )
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    rows = list(controls)
    for bundle in bundles:
        for seed in seeds:
            for algorithm in (FULL, WITHOUT_JOINT):
                rows.append(
                    run_new_arm(
                        algorithm=algorithm,
                        bundle=bundle,
                        seed=seed,
                        budget=int(args.budget),
                        prices=prices,
                        depot_room=int(args.depot_room),
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
        depot_room=int(args.depot_room),
        source=source,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["accounting_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
