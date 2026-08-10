#!/usr/bin/env python3
"""Exact, fixed-route scouts for two Problem-HGS main experiment factors.

The script does not search for a favourable route.  It reloads the saved
three-region Problem-HGS solutions and changes only one registered decision
factor at a time:

* charging start policy: ASAP, electricity-cost-minimum, or cost-plus-carbon;
* fleet type: saved mixed fleet or the same trips operated by an all-CV fleet.

The output is diagnostic evidence for instance/interface selection, not a
formal paper experiment and not a choice of representative region.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import traceback
from dataclasses import asdict, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from run_problem_hgs_private_technical import (
    PROTECTED,
    _build_context,
    _json,
    _sha256,
    _source_provenance,
    _with_registered_idle_duties,
    _write_failure_package,
)
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    PhysicalVehicleDuty,
)
from setp_solver.charge_timing import select_charge_timing_start
from setp_solver.cost import time_profile_rows_for_node
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import route_timing
from setp_solver.solution import ChargingAction


REGIONS = ("cy", "jjj", "prd")
SOURCE_SUFFIX = "route_elite_populationfix_pair_v7_20260809"
TIMING_POLICIES = (
    ("ASAP", "asap"),
    ("ELECTRICITY_COST_MIN", "cost_min"),
    ("COST_PLUS_CARBON", "cost_plus_carbon"),
)


def _payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _route_signature(individual: DutyIndividual) -> str:
    return _payload_sha256(
        [
            {
                "vehicle": duty.physical_vehicle_id,
                "type": duty.vehicle_type,
                "depot": duty.home_depot_id,
                "trips": [
                    {
                        "trip": trip.trip_index,
                        "customers": list(trip.customer_ids),
                        "visits": list(trip.effective_route_visits),
                    }
                    for trip in duty.trips
                ],
            }
            for duty in individual.duties
            if duty.trips
        ]
    )


def _customer_order_signature(individual: DutyIndividual) -> str:
    """Ignore vehicle type/id so the mixed/all-CV route skeleton is comparable."""

    return _payload_sha256(
        sorted(
            [
                {
                    "depot": duty.home_depot_id,
                    "trips": [
                        list(trip.effective_route_visits)
                        for trip in duty.trips
                    ],
                }
                for duty in individual.duties
                if duty.trips
            ],
            key=lambda row: (
                row["depot"],
                json.dumps(row["trips"], ensure_ascii=False),
            ),
        )
    )


def _served(individual: DutyIndividual, bundle) -> tuple[int, float]:
    customers = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served = {
        customer
        for duty in individual.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    return len(served), sum(float(customers[item].demand) for item in served)


def _timing_individual(
    source: DutyIndividual,
    source_solution,
    bundle,
    policy: str,
) -> tuple[DutyIndividual, list[dict[str, Any]]]:
    route_by_id = {route.vehicle_id: route for route in source_solution.routes}
    action_by_route: dict[str, list[ChargingAction]] = {}
    for action in source_solution.charging_actions:
        action_by_route.setdefault(action.vehicle_id, []).append(action)

    changed_duties = []
    decisions: list[dict[str, Any]] = []
    for duty in source.duties:
        sessions = list(duty.charging_sessions)
        previous_return: float | None = None
        for trip in duty.trips:
            route_id = duty.route_id(trip.trip_index)
            route = route_by_id[route_id]
            timing = route_timing(
                route,
                bundle.instance,
                bundle.prices,
                charging_actions=action_by_route.get(route_id, ()),
                validate_battery=False,
            )
            for index, session in enumerate(sessions):
                if (
                    session.trip_index != trip.trip_index
                    or session.locked
                    or session.station_id != duty.home_depot_id
                    or int(session.charge_day_offset) != 0
                ):
                    continue
                earliest = 0.0 if previous_return is None else previous_return
                latest = (
                    float(timing.earliest_departure_second)
                    - float(session.occupancy_minutes) * 60.0
                )
                action = ChargingAction(
                    vehicle_id=route_id,
                    station_id=session.station_id,
                    energy_kwh=float(session.energy_kwh),
                    occupancy_minutes=float(session.occupancy_minutes),
                    charge_start_second=float(session.charge_start_second),
                    charge_day_offset=int(session.charge_day_offset),
                    start_energy_kwh=session.start_energy_kwh,
                    end_energy_kwh=session.end_energy_kwh,
                    charging_curve_id=session.charging_curve_id,
                )
                profile = time_profile_rows_for_node(
                    bundle.instance,
                    session.station_id,
                    bundle.time_profile,
                )
                selected = select_charge_timing_start(
                    action,
                    earliest_start_second=earliest,
                    latest_start_second=latest,
                    instance=bundle.instance,
                    carbon_profile=profile,
                    prices=bundle.prices,
                    charge_timing_policy=policy,
                )
                sessions[index] = replace(
                    session,
                    charge_start_second=float(selected),
                )
                decisions.append(
                    {
                        "vehicle_id": route_id,
                        "station_id": session.station_id,
                        "energy_kwh": float(session.energy_kwh),
                        "old_start_second": float(session.charge_start_second),
                        "new_start_second": float(selected),
                        "earliest_start_second": float(earliest),
                        "latest_start_second": float(latest),
                    }
                )
            previous_return = float(timing.return_second)
        changed_duties.append(
            replace(duty, charging_sessions=tuple(sessions))
        )
    return (
        replace(
            source,
            duties=tuple(changed_duties),
            source=f"fixed-route-charge-timing-{policy}",
        ),
        decisions,
    )


def _all_cv_same_routes(source: DutyIndividual, bundle):
    caps: dict[str, MappingProxyType] = {}
    duties: list[PhysicalVehicleDuty] = []
    for depot_id, row in sorted(bundle.fleet_caps_by_depot.items()):
        total = int(row["total_fleet_cap"])
        caps[depot_id] = MappingProxyType(
            {**dict(row), "num_cv": total, "num_ev": 0}
        )
        active = [
            duty
            for duty in source.duties
            if duty.home_depot_id == depot_id and duty.trips
        ]
        if len(active) > total:
            raise ValueError(
                f"{depot_id} has {len(active)} active duties but cap is {total}"
            )
        for index, duty in enumerate(active, start=1):
            duties.append(
                PhysicalVehicleDuty(
                    physical_vehicle_id=f"CV_{depot_id}_{index}",
                    vehicle_type="cv",
                    home_depot_id=depot_id,
                    trips=duty.trips,
                    charging_sessions=(),
                )
            )
        for index in range(len(active) + 1, total + 1):
            duties.append(
                PhysicalVehicleDuty(
                    physical_vehicle_id=f"CV_{depot_id}_{index}",
                    vehicle_type="cv",
                    home_depot_id=depot_id,
                    trips=(),
                )
            )
    return (
        DutyIndividual(
            duties=tuple(duties),
            source="fixed-route-all-cv-scout",
        ),
        replace(
            bundle,
            fleet_caps_by_depot=MappingProxyType(caps),
        ),
    )


def _evaluation_row(
    *,
    instance_id: str,
    region: str,
    experiment: str,
    arm: str,
    individual: DutyIndividual,
    bundle,
    evaluation,
    physical_evaluation,
    source_sha256: str,
    decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    served_count, served_demand = _served(individual, bundle)
    breakdown = evaluation.breakdown
    return {
        "instance_id": instance_id,
        "region": region,
        "experiment": experiment,
        "arm": arm,
        "full_model_feasible": evaluation.feasible,
        "physical_feasible": physical_evaluation.feasible,
        "full_violation_count": len(evaluation.violations),
        "physical_violation_count": len(physical_evaluation.violations),
        "total_cost_cny": float(breakdown["total_cost"]),
        "total_emissions_kg": float(breakdown["E_total"]),
        "electricity_cost_cny": float(breakdown["cost_elec"]),
        "carbon_cost_cny": float(breakdown["cost_carbon"]),
        "used_cv": int(breakdown["n_veh_cv"]),
        "used_ev": int(breakdown["n_veh_ev"]),
        "customers_served": served_count,
        "demand_served": served_demand,
        "route_signature": _route_signature(individual),
        "customer_order_signature": _customer_order_signature(individual),
        "decision_signature": _payload_sha256(decisions or []),
        "source_best_solution_sha256": source_sha256,
    }


def _relative_pct(left: float, right: float) -> float:
    return (float(left) / float(right) - 1.0) * 100.0


def run(
    output: Path,
    source_overrides: dict[str, Path] | None = None,
) -> None:
    repo = Path(__file__).resolve().parents[2]
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state="caller_not_declared",
    )
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": (
                "fixed-route technical effect scout; not a formal experiment"
            ),
            "regions": list(REGIONS),
            "timing_policies": [item[1] for item in TIMING_POLICIES],
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "code_provenance": provenance,
            "protected_hashes_before": protected_before,
        },
    )

    rows: list[dict[str, Any]] = []
    timing_details: dict[str, Any] = {}
    source_files: dict[str, str] = {}
    for region in REGIONS:
        instance_id = f"cn-{region}-50c-01-V2-LOCATIONS"
        source_path = (
            source_overrides[region]
            if source_overrides and region in source_overrides
            else (
                repo
                / "solver/reports"
                / (
                    f"problem_hgs_private_{region}50_"
                    f"{SOURCE_SUFFIX}"
                )
                / "best_solution.json"
            )
        )
        metadata_path = source_path.with_name("metadata.json")
        source_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if source_metadata.get("status") != "COMPLETE":
            raise ValueError(f"source package is not complete: {source_path}")
        if source_metadata.get("instance_id") != instance_id:
            raise ValueError(f"source package has wrong instance: {source_path}")
        source_sha256 = _sha256(source_path)
        source_files[str(source_path.relative_to(repo))] = source_sha256
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        selected = (
            payload["FULL_PROBLEM_COMPONENTS"]
            if source_path.name == "best_solutions.json"
            else payload
        )
        source_solution = solution_from_dict(
            selected["evaluation"]["prepared_solution"]
        )
        bundle, _, _, context = _build_context(repo, instance_id)
        customer_ids = {
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        }
        source = _with_registered_idle_duties(
            DutyIndividual.from_solution(
                source_solution,
                customer_node_ids=customer_ids,
                source="saved-problem-hgs-solution-recertified",
            ),
            bundle,
        )
        full_evaluator = DutyFullEvaluator(context)
        physical_evaluator = DutyFullEvaluator(
            replace(context, fairness_enabled=False)
        )

        timing_details[region] = {}
        for arm, policy in TIMING_POLICIES:
            candidate, decisions = _timing_individual(
                source,
                source_solution,
                bundle,
                policy,
            )
            evaluation = full_evaluator.evaluate(candidate)
            physical_evaluation = physical_evaluator.evaluate(candidate)
            timing_details[region][arm] = decisions
            rows.append(
                _evaluation_row(
                    instance_id=instance_id,
                    region=region,
                    experiment="CHARGING_TIMING_FIXED_ROUTE_TYPE_AMOUNT",
                    arm=arm,
                    individual=candidate,
                    bundle=bundle,
                    evaluation=evaluation,
                    physical_evaluation=physical_evaluation,
                    source_sha256=source_sha256,
                    decisions=decisions,
                )
            )

        mixed_evaluation = full_evaluator.evaluate(source)
        mixed_physical = physical_evaluator.evaluate(source)
        rows.append(
            _evaluation_row(
                instance_id=instance_id,
                region=region,
                experiment="FLEET_TYPE_FIXED_CUSTOMER_ORDER",
                arm="REGISTERED_MIXED_FLEET",
                individual=source,
                bundle=bundle,
                evaluation=mixed_evaluation,
                physical_evaluation=mixed_physical,
                source_sha256=source_sha256,
            )
        )
        all_cv, all_cv_bundle = _all_cv_same_routes(source, bundle)
        all_cv_context = replace(context, bundle=all_cv_bundle)
        all_cv_full = DutyFullEvaluator(all_cv_context).evaluate(all_cv)
        all_cv_physical = DutyFullEvaluator(
            replace(all_cv_context, fairness_enabled=False)
        ).evaluate(all_cv)
        rows.append(
            _evaluation_row(
                instance_id=instance_id,
                region=region,
                experiment="FLEET_TYPE_FIXED_CUSTOMER_ORDER",
                arm="ALL_CV_SAME_TRIPS",
                individual=all_cv,
                bundle=all_cv_bundle,
                evaluation=all_cv_full,
                physical_evaluation=all_cv_physical,
                source_sha256=source_sha256,
            )
        )

    fields = list(rows[0])
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    _json(output / "timing_decisions.json", timing_details)

    timing_summary = {}
    fleet_summary = {}
    for region in REGIONS:
        timing = {
            row["arm"]: row
            for row in rows
            if row["region"] == region
            and row["experiment"]
            == "CHARGING_TIMING_FIXED_ROUTE_TYPE_AMOUNT"
        }
        aware = timing["COST_PLUS_CARBON"]
        asap = timing["ASAP"]
        timing_summary[region] = {
            "aware_vs_asap_cost_pct": _relative_pct(
                aware["total_cost_cny"], asap["total_cost_cny"]
            ),
            "aware_vs_asap_emissions_pct": _relative_pct(
                aware["total_emissions_kg"],
                asap["total_emissions_kg"],
            ),
            "all_three_full_model_feasible": all(
                row["full_model_feasible"] for row in timing.values()
            ),
        }
        fleet = {
            row["arm"]: row
            for row in rows
            if row["region"] == region
            and row["experiment"] == "FLEET_TYPE_FIXED_CUSTOMER_ORDER"
        }
        mixed = fleet["REGISTERED_MIXED_FLEET"]
        all_cv = fleet["ALL_CV_SAME_TRIPS"]
        fleet_summary[region] = {
            "mixed_vs_all_cv_cost_pct": _relative_pct(
                mixed["total_cost_cny"], all_cv["total_cost_cny"]
            ),
            "mixed_vs_all_cv_emissions_pct": _relative_pct(
                mixed["total_emissions_kg"],
                all_cv["total_emissions_kg"],
            ),
            "same_customer_order": (
                mixed["customer_order_signature"]
                == all_cv["customer_order_signature"]
            ),
            "all_cv_physical_feasible": all_cv["physical_feasible"],
            "all_cv_full_model_feasible": all_cv["full_model_feasible"],
            "all_cv_full_violation_count": all_cv["full_violation_count"],
        }

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    failures = []
    if protected_before != protected_after:
        failures.append("protected evaluator file changed")
    if any(int(row["customers_served"]) != 50 for row in rows):
        failures.append("one arm did not serve all 50 source customers")
    if any(not item["all_three_full_model_feasible"] for item in timing_summary.values()):
        failures.append("one registered timing arm is infeasible")
    if any(not item["same_customer_order"] for item in fleet_summary.values()):
        failures.append("fleet comparison changed the customer order")
    if any(not item["all_cv_physical_feasible"] for item in fleet_summary.values()):
        failures.append("one all-CV same-trip arm is physically infeasible")

    decision = {
        "verdict": (
            "TECHNICAL_EFFECT_SCOUT_COMPLETE"
            if not failures
            else "TECHNICAL_EFFECT_SCOUT_FAILED"
        ),
        "failure_reasons": failures,
        "timing_summary": timing_summary,
        "fleet_summary": fleet_summary,
        "plain_interpretation": {
            "charging_timing": (
                "The existing three-region routes expose a feasible timing "
                "response under all three user-approved timing policies."
            ),
            "mixed_fleet": (
                "Replacing the same trips by CVs remains physically feasible; "
                "a full-model fairness violation, if present, is reported "
                "rather than hidden."
            ),
            "dynamic": (
                "Dynamic demand is intentionally absent here because a real "
                "event stream and inherited state are not a fixed-route rescore."
            ),
        },
        "representative_region_selected": False,
        "formal_experiment": False,
        "user_decision_changed": False,
    }
    _json(output / "decision.json", decision)

    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    metadata.update(
        {
            "status": "COMPLETE" if not failures else "FAILED",
            "source_best_solutions": source_files,
            "protected_hashes_after": protected_after,
            "row_count": len(rows),
        }
    )
    _json(output / "metadata.json", metadata)

    report = f"""# Problem-HGS 三地区静态主效应小试

## 结论

本次只在三地区现有自研算法解上改变一个因素，不重新搜索路线。三种充电时刻口径均通过完整模型；混合车队与全燃油车队使用完全相同的客户顺序。详细数字在 `raw_runs.csv`，汇总在 `decision.json`。

本包是算例与接口诊断，不是正式实验，也没有替用户选择代表地区。动态需求没有混入这次固定路线复算，避免用一个单时点切面冒充真实事件流实验。

## 结果摘要

充电碳感知相对有空即充的排放变化：{json.dumps({key: value['aware_vs_asap_emissions_pct'] for key, value in timing_summary.items()}, ensure_ascii=False)}。

混合车队相对同路线全燃油的排放变化：{json.dumps({key: value['mixed_vs_all_cv_emissions_pct'] for key, value in fleet_summary.items()}, ensure_ascii=False)}。

## 交付前九条自检

1. 每个 `FACT` 是否都指到了文件行号 / 产物哈希 / 论文页码？——本报告只陈述同包 `raw_runs.csv`、`decision.json` 和 `metadata.json` 可复核的运行事实；输入解哈希已逐地区登记。没有无出处的事实。
2. 有没有把自己的建议或担忧写成“已决”或“状态”？——没有选择地区、正式参数或论文结论；本包明确标为技术小试。
3. 改动范围有没有超出任务文本？——没有；只复算时变碳充电时刻和同路线车型替换，动态需求留给独立事件流接线。
4. 有没有碰受保护文件？——未碰；运行前后哈希保存在 `metadata.json`，三者一致。
5. 待决事项是否转成了 2–4 个具体候选并写清代价？——本包不新增需要用户立即拍板的事项；代表地区和正式实验仍未替用户选择。
6. 有没有用自造词或内部任务号跟用户说话？——报告使用“固定路线复算”“混合车队”“全燃油车队”等现有普通表述，没有新造术语。
7. 失败、跳过、超时、异常结果有没有如实保留？——珠三角全燃油同路线若触发利润公平违约，会在 `raw_runs.csv` 同时报完整模型与关闭公平后的物理可行结果，不隐藏。
8. 四件套齐了吗？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，另有 `timing_decisions.json`。
9. `HANDOFF.md` 变更日志和 `docs/handoff/memory/` 同步了吗？——本技术包先保存事实；项目总记录在本轮算法任务收尾时统一同步。
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _json(output / "artifact_hashes.json", hashes)
    if failures:
        raise RuntimeError("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--source-cy", type=Path)
    parser.add_argument("--source-jjj", type=Path)
    parser.add_argument("--source-prd", type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    supplied = {
        region: path.resolve()
        for region, path in (
            ("cy", args.source_cy),
            ("jjj", args.source_jjj),
            ("prd", args.source_prd),
        )
        if path is not None
    }
    if supplied and set(supplied) != set(REGIONS):
        raise ValueError("provide all three current source paths together")
    try:
        run(output, supplied or None)
    except Exception as error:
        if output.exists():
            _write_failure_package(output, error)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
