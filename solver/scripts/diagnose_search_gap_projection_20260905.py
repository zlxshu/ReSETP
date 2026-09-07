#!/usr/bin/env python3
"""把已知可行解投影进 MTC-HGS 内核视角，量代理定价与精确成本的方向差。

2026-09-05。要回答的问题：③（MTC-HGS 自己搜）的可行域按定义包含 ②（MT-HGS 的
路线固定、只把充电时刻按 cost_plus_carbon 重排）的每一个解，为什么 ③ 连 ② 的
最好都够不着（②最好 2616.23，③最好 2629.75；`solver/reports/
charge_timing_comparison_v2_20260904/summary.json`）。

办法：把 ② 的最优解与 ③ 的最优解**放进同一个内核引擎配置**里投影，逐条报
可行性（时间窗时移、载重、回场次数）与内核代理成本，再和精确成本对照。
本脚本不开任何搜索，只做投影与评价。

用法::

    export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'
    .public-hgs-venv/bin/python3 solver/scripts/diagnose_search_gap_projection_20260905.py \
        --solution-two <resettled>/MT-HGS/run_07/cost_plus_carbon.json \
        --solution-three solver/reports/ablation_formal_10x_v5_20260904/MTC-HGS/run_04/best_solution.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
for extra in ("solver/src", "third_party/setp_hgs_kernel", "models/src", "solver/scripts"):
    path = str(REPO / extra)
    if path not in sys.path:
        sys.path.insert(0, path)

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    FLEET_PARAMETER_CLASSES,
    _build_context,
    _policy,
)
from setp_solver.algorithms.problem_hgs.charging import (  # noqa: E402
    repair_changed_duties_outcome,
)
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator  # noqa: E402
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    RELOAD_GAP_QUANTILE,
    IndependentKernelDutyRouteProposalEngine,
    inter_trip_reload_seconds,
)
from setp_solver.algorithms.problem_hgs.model import (  # noqa: E402
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)


RELOAD_GAP_FLOOR_SECONDS = 1348.0


def _rebuild(payload):
    duties = []
    for duty in payload["individual"]["duties"]:
        duties.append(
            PhysicalVehicleDuty(
                physical_vehicle_id=duty["physical_vehicle_id"],
                vehicle_type=duty["vehicle_type"],
                home_depot_id=duty["home_depot_id"],
                trips=tuple(
                    DutyTrip(
                        trip_index=trip["trip_index"],
                        customer_ids=tuple(trip["customer_ids"]),
                        locked_customer_prefix=tuple(
                            trip.get("locked_customer_prefix", ())
                        ),
                        route_visits=tuple(trip.get("route_visits", ())),
                    )
                    for trip in duty["trips"]
                ),
                charging_sessions=tuple(
                    DutyChargingSession(**session)
                    for session in duty["charging_sessions"]
                ),
                has_dynamic_commitment=bool(duty.get("has_dynamic_commitment", False)),
            )
        )
    return DutyIndividual(duties=tuple(duties))


def _reload_counts(individual):
    """每辆车的回场次数 ＝ 装了客户的趟数 − 1。"""

    return {
        duty.physical_vehicle_id: max(
            0, len([t for t in duty.trips if t.customer_ids]) - 1
        )
        for duty in individual.duties
        if any(t.customer_ids for t in duty.trips)
    }


def _describe_projection(engine, individual, label):
    solution = engine.project(individual)
    evaluator = engine.penalty_manager.cost_evaluator()
    booster = engine.penalty_manager.booster_cost_evaluator()
    return {
        "label": label,
        "kernel_feasible": bool(solution.is_feasible()),
        "has_time_warp": bool(solution.has_time_warp()),
        "time_warp": int(solution.time_warp()),
        "has_excess_load": bool(solution.has_excess_load()),
        "excess_load": [int(v) for v in solution.excess_load()],
        "has_excess_distance": bool(solution.has_excess_distance()),
        "num_routes": int(solution.num_routes()),
        "distance": int(solution.distance()),
        "duration": int(solution.duration()),
        "proxy_cost": int(evaluator.cost(solution)),
        "proxy_penalised_cost": int(evaluator.penalised_cost(solution)),
        "proxy_penalised_cost_boosted": int(booster.penalised_cost(solution)),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--solution-two", type=Path, required=True)
    parser.add_argument("--solution-three", type=Path, required=True)
    parser.add_argument("--carbon-price", type=float, default=0.2)
    parser.add_argument("--max-reloads", type=int, default=8)
    parser.add_argument(
        "--batch-dir",
        type=Path,
        default=Path("solver/reports/ablation_formal_10x_v5_20260904"),
        help="③ 的源批：全批投影从这里读两个臂各 10 个 best_solution.json",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    bundle, initial, _neutral, context = _build_context(
        REPO,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    # 批次是用 --carbon-price 0.2 跑的；run_problem_hgs_private_technical.py
    # 用同样一句 replace 覆盖 bundle 的碳价（第 2030 行起）。
    bundle = replace(
        bundle,
        prices=replace(bundle.prices, carbon_price=args.carbon_price),
        carbon_price_cny_per_kg=args.carbon_price,
    )
    context = replace(context, bundle=bundle)
    assert abs(float(context.bundle.prices.carbon_price) - args.carbon_price) < 1e-9
    evaluator = DutyFullEvaluator(context)

    two = _rebuild(json.loads(args.solution_two.read_text(encoding="utf-8")))
    three = _rebuild(json.loads(args.solution_three.read_text(encoding="utf-8")))

    exact = {}
    for label, individual in (("2_same_route_cost_plus_carbon", two), ("3_MTC_run04", three)):
        full = evaluator.evaluate(individual)
        exact[label] = {
            "feasible": bool(full.feasible),
            "total_cost": float(full.total_cost),
            "breakdown": {
                k: float(v)
                for k, v in full.breakdown.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            },
            "reload_counts": _reload_counts(individual),
            "inter_trip_reload_p75": inter_trip_reload_seconds(
                individual, quantile=RELOAD_GAP_QUANTILE
            ),
            "inter_trip_reload_max": inter_trip_reload_seconds(individual, quantile=1.0),
            "vehicle_types": sorted(
                {duty.vehicle_type for duty in individual.duties if any(t.customer_ids for t in duty.trips)}
            ),
        }

    # 引擎配置。基准 ＝ **③ 批当时真正跑的那套接线**，不是今天的默认值。
    # 出处：solver/reports/ablation_formal_10x_v5_20260904/MTC-HGS/run_04/
    # metadata.json 的 route_engine_wiring.route_engine_source_id
    #   setp_hgs_kernel-0.12.2-...:half-load-propulsion:depot-split:
    #   volume-capacity:same-shift-neighbours:shift-aware-ev-price:
    #   ev-charge-time:ev-reload-gap:main_route
    # 按 kernel_proposals.py 第 324 行起的 source_id 拼法逐段反读：
    #   * 没有 ``policy-proxy-`` 段 ⇒ charge_timing_policy_for_proxy is None
    #     （班次感知定价按哪条政策计价是 2026-09-05 的 A2 改动，当时还没有）；
    #   * 没有 ``max-reloads-N`` 段 ⇒ max_reloads_per_vehicle is None（不限）；
    #   * 没有 ``vtype-dedup`` 段   ⇒ vehicle_type_dedup_enabled is False；
    #   * ``ev-charge-time`` 段只说明 ev_charge_time_proxy 这个属性非 None，
    #     而 metadata 里该块只有 reload_* 三个键、没有 curve_id/seconds_per_kwh，
    #     所以它是回场预留合并进去的，charge-time 代理本身是关的（COMMON 里的
    #     --no-ev-charge-time-proxy）。
    # 第 1 轮预留 2031.6707 s 与参考电量 33.7619 kWh 同样直接取自该 metadata 的
    # ev_charge_time_proxy 块（accounting.reload_gap_seconds_by_round[0] 一致）。
    ASRAN_RELOAD_SECONDS = 2031.6707043430688
    ASRAN_RELOAD_REFERENCE_KWH = 33.76187876229928

    def make_engine(
        *,
        reload_gap_seconds,
        policy_proxy,
        max_reloads,
        dedup,
        reference_kwh=ASRAN_RELOAD_REFERENCE_KWH,
    ):
        return IndependentKernelDutyRouteProposalEngine(
            context,
            initial,
            stream_role="main_route",
            depot_assignment_operator_enabled=True,
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
            charge_timing_policy_for_proxy=policy_proxy,
            ev_charge_time_proxy_enabled=False,
            ev_reload_gap_proxy_enabled=True,
            ev_reload_gap_reference_kwh=reference_kwh,
            ev_reload_gap_seconds=reload_gap_seconds,
            max_reloads_per_vehicle=max_reloads,
            vehicle_type_dedup_enabled=dedup,
            ev_unit_cost_cny_per_kwh=None,
        )

    asran = {
        "reload_gap_seconds": ASRAN_RELOAD_SECONDS,
        "policy_proxy": None,
        "max_reloads": None,
        "dedup": False,
    }
    # ② 自己的 p75 预留：③ 若要把 ② 这类解留在可行域里，至少要放宽到这个数。
    two_p75 = float(
        exact["2_same_route_cost_plus_carbon"]["inter_trip_reload_p75"] or 0.0
    )
    postfix = {
        "reload_gap_seconds": max(RELOAD_GAP_FLOOR_SECONDS, two_p75),
        "policy_proxy": "cost_plus_carbon",
        "max_reloads": args.max_reloads,
        "dedup": True,
    }
    # A ＝ 如实重建的 09-04 批；B–E ＝ 从 A 出发每次只翻一个 09-05 旋钮，
    # 好把"哪一项定价/可行性口径造成排序反转"定位到单一旋钮；F ＝ 全部 09-05。
    configs = {
        "A_asran_0904": dict(asran),
        "B_policy_proxy_on": {**asran, "policy_proxy": "cost_plus_carbon"},
        "C_max_reloads_8": {**asran, "max_reloads": args.max_reloads},
        "D_vtype_dedup_on": {**asran, "dedup": True},
        "E_reload_p75": {
            **asran,
            "reload_gap_seconds": max(RELOAD_GAP_FLOOR_SECONDS, two_p75),
        },
        "F_postfix_0905": dict(postfix),
    }

    sweep = {}
    for name, cfg in configs.items():
        engine = make_engine(**cfg)
        rows = [
            _describe_projection(engine, two, "2_same_route_cost_plus_carbon"),
            _describe_projection(engine, three, "3_MTC_run04"),
        ]
        sweep[name] = {
            "config": {
                **cfg,
                "reload_gap_reference_kwh": ASRAN_RELOAD_REFERENCE_KWH,
            },
            "kernel_source_id": str(engine.source_id),
            "kernel_num_vehicle_types": int(engine.data.num_vehicle_types),
            "kernel_num_vehicles": int(engine.data.num_vehicles),
            "rows": rows,
            # 想看的就这一条：代理把谁排在前面，和精确账的排序是否一致。
            "proxy_prefers": (
                "2"
                if rows[0]["proxy_penalised_cost"] < rows[1]["proxy_penalised_cost"]
                else "3"
            ),
        }

    # 充电修复层：③ 搜索里用的那个入口（runner 走的是 outcome 版），把 ② 的
    # 路线逐辆过一遍，看修复器判不判它可行、成本与 ② 是否逐位相同。
    policy = _policy(evaluator, charge_timing_policy="cost_plus_carbon")
    repair = {}
    for label, individual in (("2_same_route_cost_plus_carbon", two), ("3_MTC_run04", three)):
        changed = {duty.physical_vehicle_id for duty in individual.duties}
        outcome = repair_changed_duties_outcome(
            individual,
            individual,
            changed_duty_ids=changed,
            context=context,
            policy=policy,
            cache=None,
        )
        entry = {
            "candidate_is_none": outcome.candidate is None,
            "statuses": dict(getattr(outcome, "statuses", {}) or {}),
            "rejection_reasons": dict(getattr(outcome, "rejection_reasons", {}) or {}),
        }
        if outcome.candidate is not None:
            full = evaluator.evaluate(outcome.candidate)
            entry["feasible"] = bool(full.feasible)
            entry["total_cost"] = float(full.total_cost)
            entry["delta_vs_input"] = float(full.total_cost) - exact[label]["total_cost"]
        repair[label] = entry

    # ------------------------------------------------------------------
    # 全批投影：② 的 10 个解与 ③ 的 10 个解，同一把内核尺子上排一次序。
    # ② 的输入取 **MT-HGS 批自己的 best_solution.json**（asap 计时），再过一遍
    # ③ 搜索里用的 cost_plus_carbon 修复入口——这正是 ③ 的算子若生成了同一组
    # 路线时会走的那条路。修复后的成本若与落盘的 ②（重排结果）逐位相同，
    # 就说明 ③ 的实际可行域确实是 ② 的超集。
    # ------------------------------------------------------------------
    engine_asran = make_engine(**asran)
    batch = args.batch_dir if args.batch_dir.is_absolute() else REPO / args.batch_dir
    all_runs = {}
    for arm in ("MT-HGS", "MTC-HGS"):
        rows = []
        for run_dir in sorted((batch / arm).glob("run_*")):
            best = run_dir / "best_solution.json"
            if not best.is_file():
                continue
            individual = _rebuild(json.loads(best.read_text(encoding="utf-8")))
            native = evaluator.evaluate(individual)
            outcome = repair_changed_duties_outcome(
                individual,
                individual,
                changed_duty_ids={duty.physical_vehicle_id for duty in individual.duties},
                context=context,
                policy=policy,
                cache=None,
            )
            repaired_cost = None
            repaired_feasible = None
            if outcome.candidate is not None:
                repaired = evaluator.evaluate(outcome.candidate)
                repaired_cost = float(repaired.total_cost)
                repaired_feasible = bool(repaired.feasible)
                projected = _describe_projection(
                    engine_asran, outcome.candidate, f"{arm}/{run_dir.name}"
                )
            else:
                projected = None
            rows.append(
                {
                    "run": run_dir.name,
                    "native_total_cost": float(native.total_cost),
                    "native_feasible": bool(native.feasible),
                    "repair_candidate_is_none": outcome.candidate is None,
                    "repaired_total_cost": repaired_cost,
                    "repaired_feasible": repaired_feasible,
                    "kernel_feasible": None if projected is None else projected["kernel_feasible"],
                    "kernel_time_warp": None if projected is None else projected["time_warp"],
                    "proxy_penalised_cost": (
                        None if projected is None else projected["proxy_penalised_cost"]
                    ),
                }
            )
        all_runs[arm] = rows

    payload = {
        "instance_id": DEPOT_SEARCH_INSTANCE_ID,
        "all_runs_projection": all_runs,
        "carbon_price": float(context.bundle.prices.carbon_price),
        "solution_two": str(args.solution_two),
        "solution_three": str(args.solution_three),
        "exact": exact,
        "engine_config": {
            "arm": "MTC-HGS round 1",
            "charge_timing_policy_for_proxy": "cost_plus_carbon",
            "ev_charge_time_proxy_enabled": False,
            "ev_reload_gap_proxy_enabled": True,
            "max_reloads_per_vehicle": args.max_reloads,
            "vehicle_type_dedup_enabled": True,
            "ev_unit_cost_cny_per_kwh": None,
        },
        "reload_gap_sweep": sweep,
        "in_search_charging_repair": repair,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
