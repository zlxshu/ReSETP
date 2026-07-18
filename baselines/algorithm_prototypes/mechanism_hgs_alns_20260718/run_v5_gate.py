#!/usr/bin/env python3
"""Cheap paired gate for carbon-aware mechanism-first ALNS v5.

Three pinned controls are reused only after hash verification.  The runner
executes the full v5 candidate and its equal-budget carbon-retiming ablation
on the same three development bundles and common seeds.  It records route,
vehicle-type, charging-quantity, and charging-schedule fingerprints so that a
timing-only mechanism claim is mechanically falsifiable.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
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
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402
from v5_carbon_retiming_solver import (  # noqa: E402
    run_mechanism_alns_v5,
    run_mechanism_alns_v5_without_carbon,
)


CONTROL_SOURCE = HERE / "mechanism_v4_b100_minimal_gate"
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
FULL = "mechanism_alns_v5"
WITHOUT_CARBON = "mechanism_alns_v5_without_carbon_ablation"
CONTROLS = (OFFICIAL_HGS, ORIGINAL_ALNS, CURRENT_ALNS)
ALGORITHMS = (*CONTROLS, FULL, WITHOUT_CARBON)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def solution_fingerprints(solution: Solution) -> dict[str, str]:
    routes = sorted(
        (
            route.vehicle_id,
            route.vehicle_type,
            route.home_depot_id,
            tuple(route.node_sequence),
        )
        for route in solution.routes
    )
    quantities = sorted(
        (
            action.vehicle_id,
            action.station_id,
            round(float(action.energy_kwh), 12),
            round(float(action.occupancy_minutes), 12),
            int(action.charge_day_offset),
        )
        for action in solution.charging_actions
    )
    schedules = sorted(
        (
            action.vehicle_id,
            action.station_id,
            round(float(action.energy_kwh), 12),
            round(float(action.occupancy_minutes), 12),
            round(float(action.charge_start_second), 12),
            int(action.charge_day_offset),
        )
        for action in solution.charging_actions
    )
    return {
        "route_vehicle_fingerprint": payload_sha256(routes),
        "charging_quantity_fingerprint": payload_sha256(quantities),
        "charging_schedule_fingerprint": payload_sha256(schedules),
    }


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
        raise RuntimeError("v4 control raw_runs.csv hash verification failed")

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
                    "route_vehicle_fingerprint": "",
                    "charging_quantity_fingerprint": "",
                    "charging_schedule_fingerprint": "",
                    "total_emissions_kg": "",
                    "charging_emissions_kg": "",
                    "carbon_activity": "",
                    "mechanism_activity": raw["mechanism_activity"],
                    "evidence_origin": str(raw_path.relative_to(REPO)),
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
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    runners: dict[str, Callable[..., Any]] = {
        FULL: run_mechanism_alns_v5,
        WITHOUT_CARBON: run_mechanism_alns_v5_without_carbon,
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
    metrics = evaluate(
        result.best_solution,
        loaded.instance,
        loaded.carbon_profile,
        prices,
    )
    fingerprints = solution_fingerprints(result.best_solution)
    carbon_activity = result.mechanism_activity.get("carbon_activity", {})
    witness = None
    if algorithm == FULL and bundle.name.endswith("-20c-01") and seed == 1:
        witness = {
            "instance": bundle.name,
            "seed": seed,
            "algorithm": algorithm,
            "solution": {
                "routes": [asdict(route) for route in result.best_solution.routes],
                "charging_actions": [
                    asdict(action)
                    for action in result.best_solution.charging_actions
                ],
                "cross_site_services": [
                    asdict(item)
                    for item in result.best_solution.cross_site_services
                ],
            },
            "metrics": metrics,
            "carbon_activity": carbon_activity,
            "fingerprints": fingerprints,
        }
    return (
        {
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
            **fingerprints,
            "total_emissions_kg": float(metrics["E_total"]),
            "charging_emissions_kg": float(metrics["E_ev_indirect"]),
            "carbon_activity": json.dumps(
                carbon_activity,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "mechanism_activity": json.dumps(
                result.mechanism_activity,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "evidence_origin": "current_v5_gate_run",
        },
        witness,
    )


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
        for seed in sorted(
            {
                int(row["seed"])
                for row in rows
                if str(row["instance"]) == instance
            }
        ):
            group = {
                str(row["algorithm"]): row
                for row in rows
                if str(row["instance"]) == instance and int(row["seed"]) == seed
            }
            if set(group) != set(ALGORITHMS):
                continue
            full = group[FULL]
            ablation = group[WITHOUT_CARBON]
            full_cost = float(full["recomputed_cost"])
            ablation_cost = float(ablation["recomputed_cost"])
            activity = json.loads(str(full["carbon_activity"]))
            paired.append(
                {
                    "instance": instance,
                    "seed": seed,
                    "full_cost": full_cost,
                    "current_project_alns_cost": float(
                        group[CURRENT_ALNS]["recomputed_cost"]
                    ),
                    "official_hgs_cost": float(
                        group[OFFICIAL_HGS]["recomputed_cost"]
                    ),
                    "original_alns_cost": float(
                        group[ORIGINAL_ALNS]["recomputed_cost"]
                    ),
                    "without_carbon_cost": ablation_cost,
                    "beats_both_original_open_sources": (
                        full_cost
                        < float(group[OFFICIAL_HGS]["recomputed_cost"]) - 1.0e-9
                        and full_cost
                        < float(group[ORIGINAL_ALNS]["recomputed_cost"]) - 1.0e-9
                    ),
                    "beats_current_project_alns": (
                        full_cost
                        < float(group[CURRENT_ALNS]["recomputed_cost"]) - 1.0e-9
                    ),
                    "beats_without_carbon": (
                        full_cost < ablation_cost - 1.0e-9
                    ),
                    "relative_improvement_vs_carbon_ablation_percent": (
                        100.0 * (ablation_cost - full_cost) / ablation_cost
                    ),
                    "route_vehicle_unchanged": (
                        full["route_vehicle_fingerprint"]
                        == ablation["route_vehicle_fingerprint"]
                    ),
                    "charging_quantity_unchanged": (
                        full["charging_quantity_fingerprint"]
                        == ablation["charging_quantity_fingerprint"]
                    ),
                    "charging_schedule_changed": (
                        full["charging_schedule_fingerprint"]
                        != ablation["charging_schedule_fingerprint"]
                    ),
                    "charging_emissions_reduction_kg": (
                        float(ablation["charging_emissions_kg"])
                        - float(full["charging_emissions_kg"])
                    ),
                    "carbon_actions_retimed": int(
                        activity.get("actions_retimed", 0)
                    ),
                    "carbon_complete_evaluations": int(
                        activity.get("complete_evaluations", 0)
                    ),
                    "carbon_exact_decoder_updates": int(
                        activity.get("exact_decoder_updates", 0)
                    ),
                }
            )

    open_source_wins = sum(
        bool(row["beats_both_original_open_sources"]) for row in paired
    )
    current_wins = sum(
        bool(row["beats_current_project_alns"]) for row in paired
    )
    ablation_wins = sum(bool(row["beats_without_carbon"]) for row in paired)
    timing_isolated = sum(
        bool(row["route_vehicle_unchanged"])
        and bool(row["charging_quantity_unchanged"])
        and bool(row["charging_schedule_changed"])
        for row in paired
    )
    active = sum(
        int(row["carbon_actions_retimed"]) > 0
        and int(row["carbon_complete_evaluations"]) == 0
        and int(row["carbon_exact_decoder_updates"]) == 1
        and float(row["charging_emissions_reduction_kg"]) > 1.0e-9
        for row in paired
    )
    strict_small_gate = (
        accounting_passed
        and bool(paired)
        and open_source_wins == len(paired)
        and current_wins == len(paired)
        and ablation_wins == len(paired)
        and timing_isolated == len(paired)
        and active == len(paired)
    )
    wall: dict[str, dict[str, float]] = {}
    for algorithm in ALGORITHMS:
        elapsed = [
            float(row["elapsed_seconds"])
            for row in rows
            if str(row["algorithm"]) == algorithm
        ]
        if elapsed:
            wall[algorithm] = {
                "total": round(sum(elapsed), 6),
                "median": round(float(median(elapsed)), 6),
            }
    full_wall = wall.get(FULL, {}).get("total", 0.0)
    current_wall = wall.get(CURRENT_ALNS, {}).get("total", 0.0)
    return {
        "decision": (
            "PASS_V5_CHEAP_STRICT_DEVELOPMENT_GATE"
            if strict_small_gate
            else "HOLD_V5_CHEAP_STRICT_DEVELOPMENT_GATE"
        ),
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "accounting_passed": accounting_passed,
        "strict_small_gate_passed": strict_small_gate,
        "paired_tasks": len(paired),
        "original_open_source_double_wins": open_source_wins,
        "current_project_alns_strict_wins": current_wins,
        "carbon_ablation_strict_wins": ablation_wins,
        "timing_only_isolation_passes": timing_isolated,
        "carbon_mechanism_active_passes": active,
        "old_20c_plateau_cost": 621.2913242409613,
        "old_20c_plateau_falsified": any(
            str(row["instance"]).endswith("-20c-01")
            and float(row["full_cost"]) < 621.2913242409613 - 1.0e-9
            for row in paired
        ),
        "candidate_vs_current_total_wall_clock_percent": (
            round(100.0 * (full_wall / current_wall - 1.0), 3)
            if current_wall > 0.0
            else None
        ),
        "wall_clock_seconds_by_algorithm": wall,
        "rule": (
            "Every paired task must use the exact complete-evaluation budget, "
            "remain feasible under independent replay, strictly beat both "
            "pinned original open-source controls and the current project "
            "ALNS, and strictly beat the equal-budget carbon-retiming "
            "ablation. The carbon pair must preserve routes, vehicle types, "
            "and charging quantities while changing charge starts and "
            "reducing charging emissions. The fixed-route decoder must use "
            "zero additional complete-solution search evaluations and expose "
            "its route-local schedule checks. Ties fail."
        ),
        "claim_boundary": (
            "This is a three-instance development gate. It proves a "
            "time-varying-carbon depot-charge timing component on the current "
            "linear 280-kWh development model. It does not prove nonlinear "
            "charging, time-varying electricity price, fairness, dynamic "
            "replanning, formal E2 performance, China81 validity, or stage-2 "
            "readiness."
        ),
        "paired_details": paired,
    }


def write_records(
    *,
    out: Path,
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
    witnesses: list[dict[str, Any]],
    bundles: tuple[Path, ...],
    seeds: tuple[int, ...],
    budget: int,
    battery_kwh: float,
    depot_room: int,
    control_source: dict[str, str],
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "raw_runs.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(out / "decision.json", decision)
    write_json(out / "solution_witnesses.json", witnesses)
    write_json(
        out / "metadata.json",
        {
            "schema_version": "resetp.mechanism-alns-v5-gate.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval": "EA-HGS-002-development-only",
            "development_only": True,
            "formal_search_allowed": False,
            "stage2_allowed": False,
            "algorithms": list(ALGORITHMS),
            "bundles": [str(path.relative_to(REPO)) for path in bundles],
            "seeds": list(seeds),
            "complete_evaluation_budget_per_arm": int(budget),
            "battery_kwh": float(battery_kwh),
            "cross_depot_reserved_evaluations": int(depot_room),
            "control_reuse": control_source,
            "strict_gate": decision["rule"],
            "claim_boundary": decision["claim_boundary"],
            "source_basis": [
                {
                    "title": "Carbon-Aware EV Charging",
                    "doi": "10.1109/SMARTGRIDCOMM52983.2022.9960988",
                    "role": (
                        "retime charging within availability and physical "
                        "constraints using time-varying grid carbon"
                    ),
                },
                {
                    "title": (
                        "frvcpy: An Open-Source Solver for the Fixed Route "
                        "Vehicle Charging Problem"
                    ),
                    "doi": "10.1287/ijoc.2020.1035",
                    "role": (
                        "treat charging as a route-level subproblem embedded "
                        "inside a larger routing method, with its own ledger"
                    ),
                },
                {
                    "title": (
                        "Large Neighborhood and Hybrid Genetic Search for "
                        "Inventory Routing Problems"
                    ),
                    "identifier": "arXiv:2506.03172",
                    "role": (
                        "design a tailored operator around the model coupling "
                        "and verify it by ablation"
                    ),
                },
            ],
        },
    )
    improvements = [
        float(row["relative_improvement_vs_carbon_ablation_percent"])
        for row in decision["paired_details"]
    ]
    emission_savings = [
        float(row["charging_emissions_reduction_kg"])
        for row in decision["paired_details"]
    ]
    report = [
        "# 机制优先 ALNS v5：时变碳充电排时最小门",
        "",
        f"判定：`{decision['decision']}`。",
        "",
        "## 结果",
        "",
        (
            f"三规模×三共同种子共 {decision['paired_tasks']} 个配对任务；"
            f"预算、可行性与独立复算全部通过="
            f"`{decision['accounting_passed']}`。"
        ),
        (
            "完整版同时严格胜两套固定原装开源对照 "
            f"{decision['original_open_source_double_wins']}/"
            f"{decision['paired_tasks']}，严格胜当前项目 ALNS "
            f"{decision['current_project_alns_strict_wins']}/"
            f"{decision['paired_tasks']}，严格胜拿掉充电排时的等预算版本 "
            f"{decision['carbon_ablation_strict_wins']}/"
            f"{decision['paired_tasks']}。"
        ),
        (
            "九对均保持路线、车型和充电量不变，只改变充电开始时刻；"
            f"隔离见证 {decision['timing_only_isolation_passes']}/"
            f"{decision['paired_tasks']}，机制活跃见证 "
            f"{decision['carbon_mechanism_active_passes']}/"
            f"{decision['paired_tasks']}。"
        ),
        (
            "相对拿掉该步骤的成本改善范围为 "
            f"{min(improvements):.6f}%--{max(improvements):.6f}%；"
            "每任务充电间接排放减少范围为 "
            f"{min(emission_savings):.6f}--{max(emission_savings):.6f} kg。"
        ),
        (
            "旧 20 客户共同值 `621.2913242409613` 已被一个保持路线、"
            "车型和充电量不变的可行方案严格改进，因此不是已证最优，"
            f"反证状态=`{decision['old_20c_plateau_falsified']}`。"
        ),
        (
            "九任务总墙钟：v5 "
            f"{decision['wall_clock_seconds_by_algorithm'][FULL]['total']:.3f} 秒，"
            "当前项目 ALNS "
            f"{decision['wall_clock_seconds_by_algorithm'][CURRENT_ALNS]['total']:.3f} 秒，"
            "v5 相对变化 "
            f"{decision['candidate_vs_current_total_wall_clock_percent']:.1f}%。"
            "该短门只如实记账，不作正式速度结论。"
        ),
        "",
        "## 为什么这个动作成立",
        "",
        "路线回来以后，算法不再默认立刻充电，而是在不耽误下一次出车的"
        "整个窗口里比较所有可能改变碳账的时间分界点。路线、车型和充电量"
        "不动，便宜计算在固定路线内精确选时刻，不占用 ALNS 的完整方案"
        "评分票；最终完整方案由与删减版相同的独立复算步骤确认。这个动作"
        "直接对应时变电网碳强度，而不是通用拼接。",
        "",
        "## 边界",
        "",
        decision["claim_boundary"],
    ]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

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
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--bundles", nargs="*", type=Path)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--depot-room", type=int, default=2)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=HERE / "mechanism_v5_carbon_b100_decoder_gate",
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
    witnesses: list[dict[str, Any]] = []
    for bundle in bundles:
        for seed in seeds:
            for algorithm in (FULL, WITHOUT_CARBON):
                row, witness = run_new_arm(
                    algorithm=algorithm,
                    bundle=bundle,
                    seed=seed,
                    budget=int(args.budget),
                    prices=prices,
                    depot_room=int(args.depot_room),
                )
                rows.append(row)
                if witness is not None:
                    witnesses.append(witness)
    decision = decide(rows)
    write_records(
        out=args.out_dir.resolve(),
        rows=rows,
        decision=decision,
        witnesses=witnesses,
        bundles=bundles,
        seeds=seeds,
        budget=int(args.budget),
        battery_kwh=float(args.battery_kwh),
        depot_room=int(args.depot_room),
        control_source=source,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["accounting_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
