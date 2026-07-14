#!/usr/bin/env python3
"""Minimum E7 probe with cooperation, forecast timing, and participation active.

This probe deliberately runs only stream 1 and the first two rolling stages.
It does not replace the sealed two-arm dynamic diagnostic.  Its purpose is to
prove that the three paper mechanisms are present in the released decisions
before any five-stream formal batch is allowed to start.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e4_e5 import e4_multiday_forecast_probe_20260713 as e4
from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as base
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.dynamic_multitrip_schedule import (
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    reschedule_dynamic_charging,
)
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
    reschedule_between_trip_charging,
    validate_multitrip_certificate,
)
from setp_solver.solution import ChargingAction, Route, Solution


OUT = ROOT / "baselines/e7_dynamic/e7_full_mechanism_probe_v2_20260714"
CONTRACT_ID = "E7_FULL_MECHANISM_PROBE_V2_IMMEDIATE_CLOCK_CHECK"
OPERATING_DAY = date(2025, 11, 13)
STREAM_SEED = 1
MAX_STAGES = 2
DEFAULT_EVALUATIONS = 8
ARMS = ("full", "no_cooperation", "carbon_blind")
TOL = 1e-6
SOURCE_FILES = (
    Path(__file__).resolve(),
    Path(base.__file__).resolve(),
    ROOT / "solver/src/setp_solver/search/dynamic_multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/profit.py",
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def route_hash(solution: Solution) -> str:
    return canonical_sha256([asdict(route) for route in solution.routes])


def energy_hash(solution: Solution) -> str:
    return canonical_sha256(
        sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.energy_kwh), 12),
                round(float(action.occupancy_minutes), 12),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
        )
    )


def _profiles() -> dict[int, list[dict[str, Any]]]:
    return e4.profiles_for_operating_day(e4.load_national_rows(), OPERATING_DAY)


def _sources_for_day() -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    sources = dict(base.load_arm("cooperative"))
    profiles = _profiles()
    bundle = sources["bundle"]
    sources["bundle"] = SearchBundle(
        bundle.bundle_dir,
        bundle.instance,
        profiles[0],
    )
    return sources, profiles


def _initial_plan(
    arm: str,
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
) -> tuple[Solution, Any, dict[str, Any]]:
    strategy = "naive" if arm == "carbon_blind" else "aware"
    original_solution = sources["solution"]
    original_certificate = sources["certificate"]
    timed = reschedule_between_trip_charging(
        original_solution,
        original_certificate,
        sources["bundle"].instance,
        profiles[0],
        strategy=strategy,
        carbon_profiles_by_day_offset=profiles,
        intensity_field="forecast_gco2_per_kwh",
    )
    synced_solution, synced_certificate = prepare_multitrip_solution(
        timed,
        sources["bundle"].instance,
        sources["prices"],
    )
    validate_multitrip_certificate(
        synced_certificate,
        list(synced_solution.routes),
        sources["prices"],
    )
    if route_hash(original_solution) != route_hash(synced_solution):
        raise RuntimeError("initial carbon timing changed routes")
    if energy_hash(original_solution) != energy_hash(synced_solution):
        raise RuntimeError("initial carbon timing changed charging energy")
    old_starts = {
        action.vehicle_id: float(action.charge_start_second)
        for action in original_solution.charging_actions
    }
    moved = sum(
        abs(float(action.charge_start_second) - old_starts[action.vehicle_id]) > TOL
        for action in synced_solution.charging_actions
    )
    return synced_solution, synced_certificate, {
        "strategy": strategy,
        "moved_action_count": moved,
        "route_sha256": route_hash(synced_solution),
        "energy_sha256": energy_hash(synced_solution),
    }


def _profit_values(
    solution: Solution,
    instance: Any,
    sources: Mapping[str, Any],
    owners: Mapping[str, str],
    *,
    prior_profit: Mapping[str, float] | None = None,
) -> dict[str, float]:
    rows = calculate_depot_profits(
        solution,
        instance,
        sources["bundle"].carbon_profile,
        sources["prices"],
        customer_home_depot=dict(owners),
        prior_profit=dict(prior_profit or {}),
        carbon_quota_kg=0.0,
    )
    return {depot: float(row.profit) for depot, row in rows.items()}


def _add_committed_profit(
    prior: Mapping[str, float],
    routes: Sequence[Route],
    actions: Sequence[ChargingAction],
    instance: Any,
    sources: Mapping[str, Any],
    owners: Mapping[str, str],
) -> dict[str, float]:
    return _profit_values(
        Solution(routes=list(routes), charging_actions=list(actions)),
        instance,
        sources,
        owners,
        prior_profit=prior,
    )


def _same_state_no_cooperation(
    construction: Any,
    sources: Mapping[str, Any],
    cut: Any,
    owners: dict[str, str],
    committed_customers: set[str],
    *,
    trigger: float,
    seed: int,
    evaluations: int,
) -> dict[str, Any]:
    owner_fixed = base.asset_aware_future_repack_candidate(
        construction,
        owners,
        sources["prices"],
        asset_states=cut.asset_states,
        stage_start_second=trigger,
        allow_cross_depot=False,
    )
    if owner_fixed is None:
        raise RuntimeError("could not build the same-state no-cooperation start")
    controlled = replace(construction, solution=owner_fixed)

    def no_cross_gate(solution: Solution, _certificate: Any, _cost: float) -> bool:
        return not base._cross_site_ids_for_routes(
            solution.routes,
            construction.effective_instance,
            owners,
        )

    result = base.search_stage(
        controlled,
        sources,
        cut,
        owners,
        committed_customers,
        trigger=trigger,
        seed=seed,
        evaluations=evaluations,
        allow_cross_depot=False,
        candidate_best_gate=no_cross_gate,
    )
    if base._cross_site_ids_for_routes(
        result["solution"].routes,
        construction.effective_instance,
        owners,
    ):
        raise RuntimeError("same-state no-cooperation plan crossed depots")
    return result


def _controlled_stage(
    arm: str,
    construction: Any,
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
    cut: Any,
    owners: dict[str, str],
    committed_customers: set[str],
    committed_profit: Mapping[str, float],
    *,
    trigger: float,
    seed: int,
    evaluations: int,
) -> dict[str, Any]:
    baseline = _same_state_no_cooperation(
        construction,
        sources,
        cut,
        owners,
        committed_customers,
        trigger=trigger,
        seed=seed,
        evaluations=evaluations,
    )
    baseline_future_profit = _profit_values(
        baseline["solution"],
        construction.effective_instance,
        sources,
        owners,
    )
    selected = baseline
    if arm != "no_cooperation":
        cooperative_start = replace(
            construction,
            solution=baseline["search_structure"],
        )

        def participation_gate(
            solution: Solution,
            _certificate: Any,
            _cost: float,
        ) -> bool:
            candidate = _profit_values(
                solution,
                construction.effective_instance,
                sources,
                owners,
            )
            return all(
                candidate.get(depot, -math.inf) >= value - TOL
                for depot, value in baseline_future_profit.items()
            )

        selected = base.search_stage(
            cooperative_start,
            sources,
            cut,
            owners,
            committed_customers,
            trigger=trigger,
            seed=seed,
            evaluations=evaluations,
            allow_cross_depot=True,
            candidate_best_gate=participation_gate,
        )
        selected_profit = _profit_values(
            selected["solution"],
            construction.effective_instance,
            sources,
            owners,
        )
        if selected["future_cost"] > baseline["future_cost"] + TOL:
            raise RuntimeError("cooperation lost the same-state cost fallback")
        if any(
            selected_profit.get(depot, -math.inf) < value - TOL
            for depot, value in baseline_future_profit.items()
        ):
            raise RuntimeError("cooperation violated the same-state participation floor")

    before_route = route_hash(selected["solution"])
    before_energy = energy_hash(selected["solution"])
    strategy = "naive" if arm == "carbon_blind" else "aware"
    timed_solution, timed_certificate, timing = reschedule_dynamic_charging(
        selected["solution"],
        selected["certificate"],
        construction.effective_instance,
        profiles[0],
        sources["prices"],
        asset_states=cut.asset_states,
        stage_start_second=trigger,
        locked_charging_actions=cut.locked_charging_actions,
        strategy=strategy,
        intensity_field="forecast_gco2_per_kwh",
    )
    if route_hash(timed_solution) != before_route or energy_hash(timed_solution) != before_energy:
        raise RuntimeError("dynamic carbon timing changed routes or energy")
    selected_future_profit = _profit_values(
        timed_solution,
        construction.effective_instance,
        sources,
        owners,
    )
    full_baseline_profit = {
        depot: float(committed_profit.get(depot, 0.0)) + value
        for depot, value in baseline_future_profit.items()
    }
    full_selected_profit = {
        depot: float(committed_profit.get(depot, 0.0))
        + selected_future_profit.get(depot, 0.0)
        for depot in baseline_future_profit
    }
    ratios = {
        depot: (
            full_selected_profit[depot] / full_baseline_profit[depot]
            if full_baseline_profit[depot] > TOL
            else math.nan
        )
        for depot in full_baseline_profit
    }
    return {
        **selected,
        "solution": timed_solution,
        "certificate": timed_certificate,
        "timing": timing,
        "charging_strategy": strategy,
        "same_state_baseline_cost": float(baseline["future_cost"]),
        "same_state_baseline_profit": baseline_future_profit,
        "selected_future_profit": selected_future_profit,
        "full_baseline_profit": full_baseline_profit,
        "full_selected_profit": full_selected_profit,
        "profit_ratios": ratios,
        "minimum_profit_ratio": min(
            (value for value in ratios.values() if math.isfinite(value)),
            default=math.nan,
        ),
        "same_state_cost_saving_pct": 100.0
        * (float(baseline["future_cost"]) - float(selected["future_cost"]))
        / max(float(baseline["future_cost"]), TOL),
        "shadow_evaluations": int(baseline["evaluations"]),
    }


def run_probe_arm(arm: str, *, evaluations: int) -> dict[str, Any]:
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm}")
    sources, profiles = _sources_for_day()
    events, owners, event_path, owner_path = base.load_stream(STREAM_SEED)
    batches = base._validated_trigger_batches(STREAM_SEED, events)[:MAX_STAGES]
    current_solution, current_certificate, initial_timing = _initial_plan(
        arm, sources, profiles
    )
    current_instance = sources["bundle"].instance
    inherited_states = None
    inherited_locked_actions: Sequence[ChargingAction] = ()
    previous_stage_start = None
    committed_customers: set[str] = set()
    booked_route_ids: set[str] = set()
    booked_action_keys: set[tuple[Any, ...]] = set()
    committed_profit = {
        node.node_id: 0.0
        for node in current_instance.nodes
        if node.node_type.lower() == "d"
    }
    rows: list[dict[str, Any]] = []

    for stage_index, batch in enumerate(batches, start=1):
        started = time.perf_counter()
        trigger = float(batch["trigger_time"])
        if stage_index == 1:
            cut = cut_certificate_at_trigger(
                current_solution,
                current_certificate,
                current_instance,
                sources["prices"],
                trigger_second=trigger,
            )
        else:
            cut = cut_dynamic_certificate_at_trigger(
                current_solution,
                current_certificate,
                current_instance,
                sources["prices"],
                inherited_asset_states=inherited_states,
                previous_stage_start_second=float(previous_stage_start),
                trigger_second=trigger,
                inherited_locked_charging_actions=inherited_locked_actions,
            )
        locked_ids = [*cut.completed_route_ids, *cut.in_progress_route_ids]
        locked_routes = base.gate._cut_routes(current_solution, locked_ids)
        new_routes = [
            route for route in locked_routes if route.vehicle_id not in booked_route_ids
        ]
        for route in new_routes:
            committed_customers.update(base.p2.route_customers(route, current_instance))
        booked_route_ids.update(route.vehicle_id for route in new_routes)
        new_actions = [
            action
            for action in cut.locked_charging_actions
            if base.action_key(action) not in booked_action_keys
        ]
        booked_action_keys.update(base.action_key(action) for action in new_actions)
        if new_routes or new_actions:
            committed_profit = _add_committed_profit(
                committed_profit,
                new_routes,
                new_actions,
                current_instance,
                sources,
                owners,
            )

        construction = base.gate.build_open_stage(
            base.gate._cut_routes(current_solution, cut.editable_route_ids),
            current_instance,
            batch["events"],
            trigger,
            committed_customers,
            owners,
            sources["prices"],
            stage_index=stage_index,
            isolate_changed_customers=True,
        )
        base._validate_stage_application(construction, batch["events"])
        result = _controlled_stage(
            arm,
            construction,
            sources,
            profiles,
            cut,
            owners,
            committed_customers,
            committed_profit,
            trigger=trigger,
            seed=STREAM_SEED * 1000 + stage_index,
            evaluations=evaluations,
        )
        future_customers = [
            customer_id
            for route in result["solution"].routes
            for customer_id in base.p2.route_customers(
                route, construction.effective_instance
            )
        ]
        active_customers = {
            node.node_id
            for node in construction.effective_instance.nodes
            if node.node_type.lower() == "c"
        }
        if len(future_customers) != len(set(future_customers)):
            raise RuntimeError("future plan contains duplicate customers")
        if committed_customers | set(future_customers) != active_customers:
            raise RuntimeError("customer accounting did not close")
        if committed_customers & set(future_customers):
            raise RuntimeError("a committed customer was planned twice")
        rows.append(
            {
                "arm": arm,
                "stream_seed": STREAM_SEED,
                "stage": stage_index,
                "trigger_second": trigger,
                "main_evaluations": int(result["evaluations"]),
                "shadow_evaluations": int(result["shadow_evaluations"]),
                "future_cost": float(result["future_cost"]),
                "same_state_baseline_cost": float(result["same_state_baseline_cost"]),
                "same_state_cost_saving_pct": float(result["same_state_cost_saving_pct"]),
                "minimum_profit_ratio": float(result["minimum_profit_ratio"]),
                "participation_gate_rejections": int(
                    result["best_gate_rejection_count"]
                ),
                "charging_strategy": result["charging_strategy"],
                "eligible_charge_actions": int(
                    result["timing"]["eligible_action_count"]
                ),
                "charge_actions_at_earliest": int(
                    result["timing"]["actions_at_earliest_count"]
                ),
                "moved_charge_actions": int(result["timing"]["moved_action_count"]),
                "moved_charge_kwh": float(result["timing"]["moved_energy_kwh"]),
                "cross_site_customer_count": len(
                    base._cross_site_ids_for_routes(
                        result["solution"].routes,
                        construction.effective_instance,
                        owners,
                    )
                ),
                "customer_accounting_pass": True,
                "route_sha256": route_hash(result["solution"]),
                "energy_sha256": energy_hash(result["solution"]),
                "solution_sha256": canonical_sha256(
                    base.solution_to_dict(result["solution"])
                ),
                "certificate_sha256": canonical_sha256(
                    result["certificate"].as_dict()
                ),
                "full_baseline_profit_json": json.dumps(
                    result["full_baseline_profit"], sort_keys=True
                ),
                "full_selected_profit_json": json.dumps(
                    result["full_selected_profit"], sort_keys=True
                ),
                "profit_ratios_json": json.dumps(
                    result["profit_ratios"], sort_keys=True
                ),
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
        inherited_states = cut.asset_states
        inherited_locked_actions = cut.locked_charging_actions
        previous_stage_start = trigger
        current_solution = result["solution"]
        current_certificate = result["certificate"]
        current_instance = construction.effective_instance

    return {
        "arm": arm,
        "rows": rows,
        "initial_timing": initial_timing,
        "event_path": str(event_path.relative_to(ROOT)),
        "event_sha256": sha256(event_path),
        "owner_path": str(owner_path.relative_to(ROOT)),
        "owner_sha256": sha256(owner_path),
        "final_solution": base.solution_to_dict(current_solution),
        "final_certificate": current_certificate.as_dict(),
    }


def _artifact_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluations", type=int, default=DEFAULT_EVALUATIONS)
    args = parser.parse_args()
    if args.evaluations <= 0:
        raise ValueError("evaluations must be positive")
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    payloads = [run_probe_arm(arm, evaluations=args.evaluations) for arm in ARMS]
    rows = [row for payload in payloads for row in payload["rows"]]
    write_csv(OUT / "raw_runs.csv", rows)
    write_json(OUT / "sessions.json", payloads)

    protected_hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in SOURCE_FILES
        if path.name in {"cost.py", "check.py", "evaluation.py"}
    }
    failures: list[str] = []
    if len(rows) != len(ARMS) * MAX_STAGES:
        failures.append("row count did not close")
    if any(int(row["main_evaluations"]) != args.evaluations for row in rows):
        failures.append("main search budget did not close")
    if any(int(row["shadow_evaluations"]) != args.evaluations for row in rows):
        failures.append("same-state comparison budget did not close")
    if any(not bool(row["customer_accounting_pass"]) for row in rows):
        failures.append("customer accounting failed")
    cooperative_rows = [row for row in rows if row["arm"] != "no_cooperation"]
    if any(float(row["same_state_cost_saving_pct"]) < -TOL for row in cooperative_rows):
        failures.append("cooperation lost its same-state fallback")
    if any(float(row["minimum_profit_ratio"]) < 1.0 - TOL for row in cooperative_rows):
        failures.append("participation floor failed")
    aware_rows = [row for row in rows if row["charging_strategy"] == "aware"]
    if sum(int(row["moved_charge_actions"]) for row in aware_rows) <= 0:
        failures.append("forecast timing moved no dynamic charging action")
    carbon_blind_rows = [row for row in rows if row["arm"] == "carbon_blind"]
    if any(
        int(row["charge_actions_at_earliest"])
        != int(row["eligible_charge_actions"])
        for row in carbon_blind_rows
    ):
        failures.append("carbon-blind arm did not keep immediate charging")
    verdict = "E7_FULL_MECHANISM_PROBE_PASS" if not failures else "HALT_E7_FULL_MECHANISM_PROBE"
    metadata = {
        "schema": "setp.e7.full_mechanism_probe.v2",
        "contract_id": CONTRACT_ID,
        "source_commit": git_head(),
        "operating_day": OPERATING_DAY.isoformat(),
        "operating_day_reason": (
            "The paper had already designated 2025-11-13 as its reference carbon day; "
            "the date was not selected from this probe's result."
        ),
        "stream_seed": STREAM_SEED,
        "stages": MAX_STAGES,
        "evaluations_per_search": args.evaluations,
        "arms": list(ARMS),
        "elapsed_seconds": time.perf_counter() - started,
        "protected_file_hashes": protected_hashes,
        "source_file_hashes": {
            str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_FILES
        },
        "scientific_boundary": (
            "This probe checks mechanism wiring only. Direction is not an expansion gate, "
            "except that cooperation must retain the same-state no-cooperation fallback."
        ),
    }
    decision = {
        "verdict": verdict,
        "failures": failures,
        "mechanical_checks": {
            "row_count": len(rows),
            "customer_accounting_all_pass": all(
                bool(row["customer_accounting_pass"]) for row in rows
            ),
            "minimum_cooperative_same_state_saving_pct": min(
                float(row["same_state_cost_saving_pct"])
                for row in cooperative_rows
            ),
            "minimum_cooperative_profit_ratio": min(
                float(row["minimum_profit_ratio"]) for row in cooperative_rows
            ),
            "aware_moved_action_count": sum(
                int(row["moved_charge_actions"]) for row in aware_rows
            ),
        },
        "formal_expansion_allowed": not failures,
    }
    write_json(OUT / "metadata.json", metadata)
    write_json(OUT / "decision.json", decision)
    report = [
        "# E7三机制最小探针",
        "",
        f"判定：`{verdict}`。",
        "",
        "本探针只运行第1条订单流的前2次调整。每次调整先在同一车辆状态和同一订单集合上计算一份从此各自经营的保底续排，再允许跨场调整；正式输出不得比保底方案更贵，也不得让任一车场收益低于保底方案。低碳组按预测碳强度移动尚未开始的充电，碳盲组有空即充。",
        "",
        f"共得到 {len(rows)} 行阶段结果；低碳安排移动 {decision['mechanical_checks']['aware_moved_action_count']} 个充电动作；合作方案相对同状态保底的最小节省为 {decision['mechanical_checks']['minimum_cooperative_same_state_saving_pct']:.6f}%；双方收益比最低值为 {decision['mechanical_checks']['minimum_cooperative_profit_ratio']:.6f}。",
        "",
        "这不是正式动态结论。只有探针机械通过后，才允许扩到五条订单流和四种正式对照。",
    ]
    if failures:
        report.extend(["", "失败项：" + "；".join(failures)])
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_json(OUT / "artifact_hashes.json", _artifact_hashes())
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
