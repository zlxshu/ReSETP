#!/usr/bin/env python3
"""Run Problem-HGS on one real China81 input."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import traceback
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping, Sequence

from experiment_acceptance import (
    assess_run,
    finalize_run_output,
    result_exit_code,
)
from setp_solver.algorithms.problem_hgs.charging import (
    FIRST_TRIP_WINDOW_PREV_RETURN,
    FIRST_TRIP_WINDOW_SAME_DAY,
    FIRST_TRIP_WINDOWS,
    ChargingRepairPolicy,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (
    FIRST_TRIP_WINDOW_OPEN_QUANTILE,
    RELOAD_GAP_FLOOR_SECONDS,
    RELOAD_GAP_QUANTILE,
    population_first_trip_window_open_second,
    population_inter_trip_reload_seconds,
    reference_trip_energy_kwh,
)
from setp_solver.algorithms.problem_hgs.c0_witness_adapter import (
    adapt_witness_rows_to_duty,
)
from setp_solver.algorithms.problem_hgs.contracts import CandidateStatus
from setp_solver.algorithms.problem_hgs.dynamic import (
    DutyDynamicState,
    future_individual_from_cut,
)
from setp_solver.algorithms.problem_hgs.dynamic_insertion import (
    DynamicInsertionOperator,
)
from setp_solver.algorithms.problem_hgs.education import evaluate_move
from setp_solver.algorithms.problem_hgs.enterprise_adapter import (
    EnterpriseProblemSlice,
    slice_enterprise_problem,
)
from setp_solver.algorithms.problem_hgs.evaluation import (
    DutyEvaluationContext,
    DutyFullEvaluator,
    RebuiltRouteConstraintContract,
)
from setp_solver.algorithms.problem_hgs.fleet_registry import (
    register_all_vehicle_slots,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual
from setp_solver.algorithms.problem_hgs.operators import (
    generate_problem_moves,
)
from setp_solver.algorithms.problem_hgs.population import (
    PopulationParameters,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    PUBLIC_STATION_CANDIDATE_MODES,
    SPLIT_PUBLIC_STATION_CANDIDATE_MODE,
    charging_repair_runtime_diagnostics,
)
from setp_solver.algorithms.problem_hgs.initialization import build_initial_population
from setp_solver.algorithms.problem_hgs.kernel_proposals import (
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.runner import (
    CONFIRMING_ROUND_PATIENCE_FLOOR,
    MAX_OUTER_ROUNDS,
    SINGLE_OBJECTIVE,
    STOP_AFTER_NONIMPROVING_ROUNDS,
    ProblemHGSSearchParameters,
    run_integrated_problem_hgs,
    run_kernel_native_problem_hgs,
)
from setp_solver.charge_timing import CHARGE_TIMING_POLICIES
from setp_solver.china81 import (
    CHINA81_CARBON_PRICE_CNY_PER_KG,
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
    ENDOGENOUS_FLEET_PARAMETERS,
    FIXED_25_PERCENT_FLEET_PARAMETERS,
    China81FleetParameterClass,
    China81Bundle,
    _china_prices,
    _china_vehicle_parameters,
    _city_runtime_binding_from_profile,
    _diesel_price_map_from_profile,
    _load_time_profile,
)
from setp_solver.enterprise_accounting import build_enterprise_ledger
from setp_solver.instance_loader import Instance, Node, RoadProfileMatrices
from setp_solver.model_config import ModelConfig
from setp_solver.search.multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    prepare_multitrip_solution,
    set_active_recharge_mode,
)
from setp_solver.field_rename_compat import (
    configured_depot_gun_count,
    resolve_calendar_path,
)
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    cut_certificate_at_trigger,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict, solution_to_dict

INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
ARM = "one-cycle-real-input-wiring-trial"
NO_IMPROVEMENT_LIMIT = 20_000

# 2026-09-08：路由代理的两个"路线无关锚点"在 --proxy-estimate-source reference
# 下取的全批共用常数。
#
# 为什么不是"从共享的参照解上估"：本入口的参照解（_build_context 返回的见证解）
# 实测是纯燃油的——8 辆燃油车、0 条充电会话、0 趟电动行程（2026-09-08 离线核
# 验，只读，不开搜索）。两个估计器在这样的解上都返回 None：
# ``population_inter_trip_reload_seconds`` 没有 trip_index>=2 的会话，
# ``population_first_trip_window_open_second`` 没有电动行程。落到 None 就退回
# 两个已知更差的旧值（预留退回见证解最大趟的 2031.67 s 过度预留；窗口退回契约
# 末班结束 19:00，实测代理 1.243 对精确 0.873 元/kWh）。所以"参照"落在**一个
# 全批共用的常数**上，而不是"参照解自己的统计量"，这与
# docs/handoff/fleet_dispersion_kernel_vs_python_20260908.md 档 b2 的原话
# （"取一个全批共用的常数"）一致。
#
# 常数取值＝现行估计器在四臂各 10 跑（共 40 跑）上实测值的中位数，规则在开跑前
# 定死，不挑结果：
#   预留   40 跑落在 1348.00–2117.39 s，中位数 1757.5422714695778
#   窗口   40 跑落在 55618.62–58731.65 s，中位数 56808.17676999999
# 产物：solver/reports/grid2x2_v3_20260906/beijing/P=0.2/{MT-HGS,MTC-HGS} 与
# solver/reports/charging_arrangements_20260906/{cost_min,carbon_min} 的
# metadata.json ``route_engine_wiring.reload_gap_round1.seconds`` 与
# ``route_engine_wiring.first_trip_window_open_round1.second``。
#
# 预留这个数只进时长、不进弧成本，取大了会把可行解判成不可行（2026-09-05 实测：
# 2614.1 s 把 33 个精确可行解里的 25 个判为内核不可行）。这里的 1757.54 s
# **小于**四臂各自最优跑当时实际用的预留（1803.67 / 1961.77 / 1820.27 /
# 2044.94 s）；预留只往时长上加，所以在更大预留下内核找得到的解，在更小的预留
# 下必然仍旧可行——这就是"取这个常数不会缩小可行域"的证明，不需要再跑一遍。
PROXY_REFERENCE_RELOAD_GAP_SECONDS = 1757.5422714695778
PROXY_REFERENCE_FIRST_TRIP_WINDOW_OPEN_SECOND = 56808.17676999999
PROXY_ESTIMATE_SOURCES = ("population", "reference")
# 正式入口的默认档。库内／函数默认仍是"改动前的行为"（多起点 1、不冻结）：
# 换默认的是这条命令行入口，不是算法库。
ROUND_ONE_STARTS_DEFAULT = 3
PROXY_ESTIMATE_SOURCE_DEFAULT = "reference"
SUCCESS_VERDICT = "RUN_COMPLETE"
FAILURE_VERDICT = "RUN_FAILED"
ENTERPRISE_NATIVE_EXPECTATIONS = {
    "ENT_A": (50, 13264.0),
    "ENT_B": (50, 13264.0),
}

FLEET_PARAMETER_CLASSES = {
    "fixed25": FIXED_25_PERCENT_FLEET_PARAMETERS,
    "endogenous": ENDOGENOUS_FLEET_PARAMETERS,
}
MECHANISM_NAMES = frozenset(
    {"cross_depot", "multi_trip", "type_exchange", "charge_timing"}
)
DEPOT_SEARCH_INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
# Work-window lever (2026-09-04): a byte-for-byte copy of the DEPOTSEARCH
# instance directory whose PM shift and PM customer windows are shifted one
# hour later (lunch 11:00-14:00, PM 14:00-20:00).  It reuses the same sealed
# package, so its catalogue and fleet-cap rows are looked up under the base id.
LUNCH_WINDOW_INSTANCE_ID = f"{DEPOT_SEARCH_INSTANCE_ID}-LUNCH1114"
DEPOT_SEARCH_INSTANCE_IDS = (DEPOT_SEARCH_INSTANCE_ID, LUNCH_WINDOW_INSTANCE_ID)
# Instance ids that share another instance's rows in ``instance_catalog.csv``
# and ``fleet_caps.csv``; only those two package-level lookups are aliased, the
# saved instance directory is always read under the real id.
PACKAGE_CATALOG_ALIAS = {LUNCH_WINDOW_INSTANCE_ID: DEPOT_SEARCH_INSTANCE_ID}
DEFAULT_TARIFF_CALENDAR_AUTHORITY = (
    "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)
# 碳限额与交易（2026-09-06）：算例的出厂配额。0 kg ＝ 无免费配额，全部排放按
# 碳价买单，这是本项目此前所有已落盘结果的口径。
DEFAULT_CARBON_QUOTA_KG = 0.0


def _resolve_tariff_calendar_authority(
    repo: Path,
    authority: Path | str | None,
) -> Path:
    """Resolve the runtime tariff/carbon calendar directory inside the repo.

    ``None`` keeps the approved default authority.  The directory must live
    under the repository root because the bundle records every input path
    relative to it (``relative_to(repo)`` below).
    """

    candidate = Path(
        DEFAULT_TARIFF_CALENDAR_AUTHORITY if authority is None else authority
    )
    if ".." in candidate.parts:
        raise ValueError(
            "tariff calendar authority must not contain '..': "
            f"{candidate}"
        )
    root = repo / candidate
    try:
        root.relative_to(repo)
    except ValueError as error:
        raise ValueError(
            "tariff calendar authority must live under the repository root: "
            f"{root}"
        ) from error
    if not root.is_dir():
        raise FileNotFoundError(
            f"tariff calendar authority directory is missing: {root}"
        )
    return root


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_kernel_trace_csvs(output: Path, accounting: Any) -> tuple[Path, Path]:
    """把内核轮内改善轨迹与每轮小结落盘（纯遥测，不改搜索行为）。

    2026-09-05：``convergence.csv`` 每个外层轮只写一行，七分钟的跑只留下两到
    四个点，轮内的改善曲线完全看不见。runner 现在把内核每次刷新轮内最优的
    时刻记进 ``accounting.improvement_events``、把每轮小结记进
    ``accounting.kernel_round_summaries``；这里按 ``convergence.csv`` 同样的
    落点（运行输出目录）写成两份 CSV。

    非 kernel_native 路径不记录这两条序列，此时只写表头。某轮内核最优若始终
    停在不可行哨兵上，``kernel_best_cost`` 写空单元格而不是字符串 "None"。
    """

    trace_path = output / "improvement_trace.csv"
    rounds_path = output / "kernel_rounds.csv"
    output.mkdir(parents=True, exist_ok=True)
    with trace_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("round", "iteration", "kernel_best_cost"),
            lineterminator="\n",
        )
        writer.writeheader()
        for event in getattr(accounting, "improvement_events", ()):
            writer.writerow(
                {
                    "round": int(event["round"]),
                    "iteration": int(event["iteration"]),
                    "kernel_best_cost": (
                        f"{float(event['kernel_best_cost']):.12f}"
                    ),
                }
            )
        handle.flush()
    with rounds_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "round",
                "iterations",
                "runtime_seconds",
                "improvements",
                "kernel_best_cost",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        for summary in getattr(accounting, "kernel_round_summaries", ()):
            cost = summary["kernel_best_cost"]
            writer.writerow(
                {
                    "round": int(summary["round"]),
                    "iterations": int(summary["iterations"]),
                    "runtime_seconds": f"{float(summary['runtime_seconds']):.9f}",
                    "improvements": int(summary["improvements"]),
                    "kernel_best_cost": (
                        "" if cost is None else f"{float(cost):.12f}"
                    ),
                }
            )
        handle.flush()
    return trace_path, rounds_path


def _trip_clock_rows(evaluation) -> list[dict[str, Any]]:
    """Per-trip departure / return / recharge-end clocks of the best solution.

    2026-09-05 (A5): ``FullEvaluation.certificate.trips`` has carried these
    instants all along, but ``best_solution.json`` never wrote them, so no
    consumer could tell when a duty's trips actually ran.  Serialised at the
    TOP level (never inside ``DutyTrip``, which is frozen and feeds the duty
    fingerprint and the solution's identity), so ``asdict(result.best)`` and
    every existing consumer stay bit-for-bit unchanged.

    ``ScheduledTrip.charge_start_second`` is the depot charge that runs AFTER
    its own trip and feeds the next departure, so the causal floor is that
    same trip's ``return_second``: a vehicle cannot start charging before it
    is back.  This mirrors ``charging.py`` ``earliest = previous_return``.
    The check is deliberately SINGLE-SIDED -- under ``cost_plus_carbon`` a
    charge may legitimately wait for a cheaper slot long after the return.
    """

    rows = [
        asdict(trip)
        for trip in sorted(
            evaluation.certificate.trips,
            key=lambda item: (item.physical_vehicle_id, item.trip_index),
        )
    ]
    for row in rows:
        start = row.get("charge_start_second")
        if start is None:
            continue
        if float(start) < float(row["return_second"]) - 1e-6:
            raise ValueError(
                "depot charge starts before its own trip returns: "
                f"{row['physical_vehicle_id']} trip {row['trip_index']} "
                f"charge_start={float(start)!r} "
                f"return={float(row['return_second'])!r}"
            )
    return rows


def _load_registered_initial_solution(path: Path, bundle: China81Bundle) -> DutyIndividual:
    payload = json.loads(path.read_text(encoding="utf-8"))
    solution_payload = payload.get("evaluation", {}).get("prepared_solution", payload)
    customer_ids = (
        node.node_id for node in bundle.instance.nodes if node.node_type == "c"
    )
    individual = DutyIndividual.from_solution(
        solution_from_dict(solution_payload),
        customer_node_ids=customer_ids,
        source="external-initial",
    )
    return register_all_vehicle_slots(individual, bundle)


def _format_full_evaluation_result(
    *,
    feasible: bool,
    violation_count: int,
) -> str:
    status = "可行" if feasible else "不可行"
    return f"完整评价判定{status}，违规数为 {violation_count}"


def _policy(
    evaluator: DutyFullEvaluator,
    *,
    first_trip_prev_night_enabled: bool = False,
    charge_timing_policy: str = "cost_plus_carbon",
    frvcpy_enabled: bool = False,
    first_trip_window: str = FIRST_TRIP_WINDOW_SAME_DAY,
    public_station_candidate_mode: str = SPLIT_PUBLIC_STATION_CANDIDATE_MODE,
) -> ChargingRepairPolicy:
    return ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        charge_amount_strategy="just_enough",
        public_station_candidate_mode=public_station_candidate_mode,
        carbon_profiles_by_day_offset=None,
        first_trip_prev_night_enabled=first_trip_prev_night_enabled,
        frvcpy_enabled=frvcpy_enabled,
        first_trip_window=first_trip_window,
    )


def _parameters(
    *,
    population_mode: str = "copied_hgs_defaults",
    objective_mode: str = SINGLE_OBJECTIVE,
    education_depth_limit: int | None = None,
) -> ProblemHGSSearchParameters:
    if population_mode == "copied_hgs_defaults":
        population = PopulationParameters.copied_hgs_defaults()
    elif population_mode == "technical_two_parent":
        population = PopulationParameters(
            min_pop_size=4,
            generation_size=2,
            num_elite=1,
            num_close=1,
            tournament_size=2,
            lb_diversity=0.0,
            ub_diversity=1.0,
        )
    else:
        raise ValueError(f"unknown population mode: {population_mode}")
    return ProblemHGSSearchParameters(
        population=population,
        stagnation_patience=NO_IMPROVEMENT_LIMIT,
        objective_mode=objective_mode,
        education_depth_limit=education_depth_limit,
    )


def _effective_population_metadata(
    mode: str,
    population: PopulationParameters,
) -> dict[str, Any]:
    """Record the named mode and every effective population parameter."""

    return {
        "mode": mode,
        "min_pop_size": population.min_pop_size,
        "generation_size": population.generation_size,
        "max_pop_size": population.max_pop_size,
        "num_elite": population.num_elite,
        "num_close": population.num_close,
        "tournament_size": population.tournament_size,
        "lb_diversity": population.lb_diversity,
        "ub_diversity": population.ub_diversity,
    }


def _build_context(
    repo: Path,
    instance_id: str = INSTANCE_ID,
    *,
    fleet_parameters: China81FleetParameterClass = (
        FIXED_25_PERCENT_FLEET_PARAMETERS
    ),
    depot_charging_scenario_name: str = "60kw",
    ev_cap_override: Mapping[str, int | tuple[int, int]] | None = None,
    tariff_calendar_authority: Path | str | None = None,
    ev_daily_premium_cny: float | None = None,
    carbon_quota_kg: float | None = None,
):
    if instance_id.endswith("-V3-TWO-SHIFT-PRDFIX"):
        if depot_charging_scenario_name != "60kw":
            raise ValueError("PRDFIX suite is frozen at the 60 kW depot scenario")
        if ev_cap_override:
            raise ValueError("ev-cap override is only wired for the DEPOTSEARCH lane")
        return _build_saved_suite_context(
            repo,
            instance_id,
            package_root=repo / "data/ChinaInstances/china81_suite_prd_fix_v1_20260812",
            report_root=repo / "solver/reports/suite_prd_fix_20260812",
            fleet_parameters=fleet_parameters,
            tariff_calendar_authority=tariff_calendar_authority,
            ev_daily_premium_cny=ev_daily_premium_cny,
            carbon_quota_kg=carbon_quota_kg,
        )
    if instance_id in DEPOT_SEARCH_INSTANCE_IDS:
        if depot_charging_scenario_name != "60kw":
            raise ValueError(
                "DEPOTSEARCH instance is frozen at the 60 kW depot scenario"
            )
        return _build_saved_suite_context(
            repo,
            instance_id,
            package_root=repo / "data/ChinaInstances/china81_final_suite_v2_20260815",
            report_root=repo / "solver/reports/instance_build_only_d996f755bd_20260815",
            fleet_parameters=fleet_parameters,
            ev_cap_override=ev_cap_override,
            tariff_calendar_authority=tariff_calendar_authority,
            ev_daily_premium_cny=ev_daily_premium_cny,
            carbon_quota_kg=carbon_quota_kg,
        )
    raise ValueError(f"inactive private instance: {instance_id}")


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _suite_matrix_from_reference(
    path: Path,
    *,
    target_node_ids: Sequence[str],
    source_node_by_target: Mapping[str, str],
) -> tuple[tuple[float, ...], ...]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows or len(rows[0]) < 2 or not rows[0][0].strip():
        raise ValueError(f"suite matrix has no row-id corner cell: {path}")
    column_ids = rows[0][1:]
    values = {
        row[0]: {column_id: float(value) for column_id, value in zip(column_ids, row[1:], strict=True)}
        for row in rows[1:]
    }
    source_ids = [source_node_by_target[node_id] for node_id in target_node_ids]
    if set(source_ids) != set(column_ids) or set(values) != set(column_ids):
        raise ValueError(f"suite matrix node identity differs from source mapping: {path}")
    return tuple(
        tuple(values[left][right] for right in source_ids)
        for left in source_ids
    )


def _apply_ev_cap_override(
    fleet_caps: Mapping[str, Mapping[str, int]],
    ev_cap_override: Mapping[str, int | tuple[int, int]],
) -> Mapping[str, Mapping[str, int]]:
    """Reshape per-depot type caps for fleet-configuration sensitivity runs.

    Two override shapes share this channel:

    * ``int`` -- the original slot-redistribution form.  The depot keeps its
      total slot cap; num_ev is set from the override and num_cv absorbs the
      remainder, so pure-CV and pure-EV endpoints are expressible exactly like
      the template's power-configuration ladder.
    * ``(num_cv, num_ev)`` -- the explicit fleet-mix form.  Both type counts are
      written as given and the redundant total becomes their sum, so a rung can
      state a fleet composition that the depot's own slot total cannot express.
    """
    unknown = set(ev_cap_override) - set(fleet_caps)
    if unknown:
        raise ValueError(f"ev-cap override names unknown depots: {sorted(unknown)}")
    adjusted = {}
    for depot_id, caps in fleet_caps.items():
        if depot_id in ev_cap_override:
            override = ev_cap_override[depot_id]
            if isinstance(override, tuple):
                num_cv, num_ev = (int(value) for value in override)
                if num_cv < 0 or num_ev < 0:
                    raise ValueError(
                        f"fleet-mix override for {depot_id} must be non-negative"
                    )
                # A depot may hold no vehicle at all (fleet-composition
                # enumeration places the whole fleet at the other depot);
                # only the plan-wide total must stay positive (checked below).
                caps = MappingProxyType(
                    {
                        "num_cv": num_cv,
                        "num_ev": num_ev,
                        "total_fleet_cap": num_cv + num_ev,
                    }
                )
            else:
                total = int(caps["total_fleet_cap"])
                num_ev = int(override)
                if not 0 <= num_ev <= total:
                    raise ValueError(
                        f"ev-cap override for {depot_id} must lie in [0, {total}]"
                    )
                caps = MappingProxyType(
                    {
                        "num_cv": total - num_ev,
                        "num_ev": num_ev,
                        "total_fleet_cap": total,
                    }
                )
        adjusted[depot_id] = caps
    if sum(
        int(caps["num_cv"]) + int(caps["num_ev"]) for caps in adjusted.values()
    ) < 1:
        raise ValueError("fleet-mix override leaves no vehicles in the plan")
    return MappingProxyType(adjusted)


def _with_public_station_power(
    bundle: China81Bundle,
    power_kw: float,
) -> China81Bundle:
    """Rescale every public charging station's rated power (node type ``f``).

    2026-09-08 尝试性开关（``--public-station-power-kw``），默认不启用。

    公共站的充电曲线**形状**仍旧取 ``prices.public_charging_*``，也就是
    Montoya 等（2017）归一化快充形状；本函数只换
    ``PiecewiseChargingCurve.from_spec`` 的参考功率。调研结论是换曲线 id
    不改 20–80% 段的时长，参考功率才是唯一杠杆（见
    ``docs/handoff/public_charger_power_curve_survey_20260908.md``）。
    因此曲线 id 仍写着 ``M17_FAST_SHAPE_SCALED_60KW_PWL``——名字里的 60KW
    指的是形状的出处，不是本轮生效的功率；生效功率见节点与
    ``charger_scenario_by_node``。

    车场功率（``prices.depot_charge_power_kw``）、站点电价、枪数一律不动。
    评价、修复、检查三条链都从 ``node.charge_power_kw`` 读站功率
    （``cost.py:585``、``search/charging.py:894``、``check.py:941``），
    所以改节点即全链生效；内核代理只读车场曲线，不看站功率。
    """

    power = float(power_kw)
    if not math.isfinite(power) or power <= 0.0:
        raise ValueError("--public-station-power-kw must be finite and positive")
    station_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "f"
    }
    if not station_ids:
        raise ValueError("instance carries no public station to rescale")
    instance = replace(
        bundle.instance,
        nodes=[
            replace(node, charge_power_kw=power)
            if node.node_id in station_ids
            else node
            for node in bundle.instance.nodes
        ],
    )
    charger_scenario = MappingProxyType(
        {
            node_id: (
                MappingProxyType({**dict(values), "charge_power_kw": power})
                if node_id in station_ids
                else values
            )
            for node_id, values in bundle.charger_scenario_by_node.items()
        }
    )
    return replace(
        bundle,
        instance=instance,
        charger_scenario_by_node=charger_scenario,
    )


def _load_v3_suite_bundle(
    repo: Path,
    *,
    package_root: Path,
    instance_id: str,
    fleet_parameters: China81FleetParameterClass,
    ev_cap_override: Mapping[str, int | tuple[int, int]] | None = None,
    tariff_calendar_authority: Path | str | None = None,
    ev_daily_premium_cny: float | None = None,
) -> tuple[China81Bundle, Mapping[str, Mapping[str, str]]]:
    """Load a V3 suite only from its sealed package and shared runtime authority.

    The construction scripts retain historical source identities for
    provenance, but a runtime lane must not call the generic China81 loader on
    an old V2 instance or old finite-fleet authority.  This adapter therefore
    reads the target package's nodes, orders, fleet caps, and matrix reference
    directly, then joins the approved shared runtime parameter calendar.
    """

    from setp_solver.china81 import FLEET_CAP_SEMANTICS

    saved_root = package_root / "instances" / instance_id
    # A derived instance (see PACKAGE_CATALOG_ALIAS) keeps its own directory but
    # shares the base instance's package-level catalogue and fleet-cap rows.
    package_row_id = PACKAGE_CATALOG_ALIAS.get(instance_id, instance_id)
    catalog_rows = [
        row
        for row in _csv_rows(package_root / "instance_catalog.csv")
        if row["instance_id"] == package_row_id
    ]
    if len(catalog_rows) != 1:
        raise ValueError(f"V3 suite catalog row is not unique for {instance_id}")
    catalog = catalog_rows[0]
    node_rows = _csv_rows(saved_root / "nodes.csv")
    order_rows = _csv_rows(saved_root / "orders.csv")
    orders_by_customer = {
        row["customer_id"]: row for row in order_rows
    }
    if len(orders_by_customer) != len(order_rows):
        raise ValueError(f"V3 suite has duplicate customers for {instance_id}")
    expected_customers = int(catalog["customer_count"])
    if len(order_rows) != expected_customers:
        raise ValueError(f"V3 suite order count disagrees for {instance_id}")

    fleet_rows = [
        row
        for row in _csv_rows(package_root / "fleet_caps.csv")
        if row["instance_id"] == package_row_id
    ]
    if not fleet_rows:
        raise ValueError(f"V3 suite fleet rows are missing for {instance_id}")
    fleet_caps = MappingProxyType(
        {
            row["depot_id"]: MappingProxyType(
                dict(fleet_parameters.depot_caps(row))
            )
            for row in fleet_rows
        }
    )
    if ev_cap_override:
        fleet_caps = _apply_ev_cap_override(fleet_caps, ev_cap_override)
    if {row["fleet_parameter_class"] for row in fleet_rows} != {
        fleet_parameters.parameter_class_id
    }:
        raise ValueError(f"V3 suite fleet class disagrees for {instance_id}")

    facilities_path = package_root / "facilities.csv"
    if not facilities_path.is_file():
        facilities_path = package_root / "source_pools" / "facilities.csv"
    facilities = {
        row["city"].strip().lower(): row
        for row in _csv_rows(facilities_path)
    }
    station_assignments = {
        row["station_id"]: row
        for row in (
            _csv_rows(package_root / "station_parameter_assignments.csv")
            if (package_root / "station_parameter_assignments.csv").is_file()
            else []
        )
    }
    customer_home_depot = MappingProxyType({})
    depot_ids = sorted(
        str(row["node_id"])
        for row in node_rows
        if str(row["node_type"]).strip().lower() == "depot"
    )
    if len(depot_ids) != 2:
        raise ValueError("the paper instance requires exactly two enterprise depots")
    enterprise_depot_by_id = {
        "ENT_A": depot_ids[0],
        "ENT_B": depot_ids[1],
    }
    nodes: list[Node] = []
    for row in node_rows:
        node_id = str(row["node_id"])
        node_type = str(row["node_type"]).strip().lower()
        city = str(row["city"]).strip().lower()
        common = {
            "node_id": node_id,
            "x": float(row["longitude"]),
            "y": float(row["latitude"]),
            "city": city,
        }
        facility = facilities[city]
        if node_type == "depot":
            fleet = next(item for item in fleet_rows if item["depot_id"] == node_id)
            nodes.append(
                Node(
                    node_type="d",
                    ready_time=float(CHINA81_HORIZON_START_SECOND),
                    due_time=float(CHINA81_HORIZON_END_SECOND),
                    charge_power_kw=float(fleet["depot_charge_power_kw"]),
                    station_chargers=None,
                    **common,
                )
            )
        elif node_type == "station":
            station = station_assignments.get(node_id)
            nodes.append(
                Node(
                    node_type="f",
                    ready_time=float(CHINA81_HORIZON_START_SECOND),
                    due_time=float(CHINA81_HORIZON_END_SECOND),
                    charge_power_kw=float(
                        station["power_kw"]
                        if station is not None
                        else facility["station_power_kw"]
                    ),
                    station_chargers=int(
                        station["gun_count"]
                        if station is not None
                        else facility["station_gun_count"]
                    ),
                    **common,
                )
            )
        elif node_type == "customer":
            order = orders_by_customer[node_id]
            nodes.append(
                Node(
                    node_type="c",
                    demand=float(order["demand_kg"]),
                    ready_time=float(order["time_window_early_minute"]) * 60.0,
                    due_time=float(order["time_window_late_minute"]) * 60.0,
                    service_time=float(order["service_minutes"]) * 60.0,
                    **common,
                )
            )
        else:
            raise ValueError(f"V3 suite has unsupported node type {node_type!r}")

    source_mapping = {
        row["new_node_id"]: row["source_node_id"]
        for row in _csv_rows(saved_root / "source_mapping.csv")
    }
    target_node_ids = [node.node_id for node in nodes]
    if set(source_mapping) != set(target_node_ids):
        raise ValueError(f"V3 suite source mapping is incomplete for {instance_id}")
    reference = json.loads(
        (saved_root / "matrix_reference.json").read_text(encoding="utf-8")
    )
    matrix_authority = repo / str(reference["source_authority"])
    matrix_instance_id = str(reference["source_instance_id"])
    matrix_root = matrix_authority / "instances" / matrix_instance_id
    profiles = {
        profile: RoadProfileMatrices(
            distance_m=_suite_matrix_from_reference(
                matrix_root / profile / "road_distance_m.csv",
                target_node_ids=target_node_ids,
                source_node_by_target=source_mapping,
            ),
            duration_s=_suite_matrix_from_reference(
                matrix_root / profile / "road_duration_s.csv",
                target_node_ids=target_node_ids,
                source_node_by_target=source_mapping,
            ),
            sum_v2d_m3_s2=_suite_matrix_from_reference(
                matrix_root / profile / "road_sum_v2d_m3_s2.csv",
                target_node_ids=target_node_ids,
                source_node_by_target=source_mapping,
            ),
        )
        for profile in ("cv", "ev")
    }
    cost_contract_path = package_root / "vehicle_cost_contract.json"
    if cost_contract_path.is_file():
        cost_contract = json.loads(
            cost_contract_path.read_text(encoding="utf-8")
        )
        fixed_costs = {
            "cv": float(cost_contract["cv"]["daily_fixed_cny"]),
            "ev": float(cost_contract["ev"]["daily_fixed_cny"]),
        }
    else:
        cost_rows = {
            row["vehicle_type"]: row
            for row in _csv_rows(
                repo
                / "data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv"
            )
        }
        fixed_costs = {
            "cv": float(cost_rows["cv"]["effective_daily_fixed_cost_cny"]),
            "ev": float(cost_rows["ev"]["effective_daily_fixed_cost_cny"]),
        }
    if ev_daily_premium_cny is not None:
        # EV subsidy lever (2026-09-04): the daily fixed premium an EV carries
        # over a CV is the authority's ``ev - cv`` difference, so overriding the
        # premium means rewriting the EV daily fixed cost.  The proxy
        # (kernel_proposals.py) and the exact account (cost.py) both read this
        # same ``vehicle_fixed_cost_per_day``, and
        # ``problem_hgs/evaluation.py`` asserts the context premium equals this
        # difference, so both must move together.
        fixed_costs = dict(fixed_costs)
        fixed_costs["ev"] = fixed_costs["cv"] + float(ev_daily_premium_cny)
    vehicle_parameters = _china_vehicle_parameters(fixed_costs)
    num_cv = sum(int(caps["num_cv"]) for caps in fleet_caps.values())
    num_ev = sum(int(caps["num_ev"]) for caps in fleet_caps.values())
    instance = Instance(
        nodes=nodes,
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        num_cv=num_cv,
        num_ev=num_ev,
        road_profiles=profiles,
        vehicle_parameters=vehicle_parameters,
        demand_mass_per_unit_kg=1.0,
    )
    cities = {
        str(node.city).strip().lower()
        for node in nodes
        if node.city is not None
    }
    runtime_root = _resolve_tariff_calendar_authority(
        repo,
        tariff_calendar_authority,
    )
    time_profile = _load_time_profile(
        resolve_calendar_path(runtime_root),
        cities=cities,
        date="2025-02-12",
        require_explicit_mapping=True,
    )
    runtime_binding = _city_runtime_binding_from_profile(
        time_profile,
        cities=cities,
        date="2025-02-12",
    )
    diesel_prices = _diesel_price_map_from_profile(
        time_profile,
        cities=cities,
        date="2025-02-12",
    )
    prices = _china_prices(
        time_profile,
        diesel_price_by_city=diesel_prices,
        vehicle_parameters=vehicle_parameters,
    )
    charger_scenario = MappingProxyType(
        {
            node.node_id: MappingProxyType(
                {
                    "charger_count": (
                        configured_depot_gun_count(
                            next(
                                item
                                for item in fleet_rows
                                if item["depot_id"] == node.node_id
                            )
                        )
                        if node.node_type == "d"
                        else int(node.station_chargers or 0)
                    ),
                    "active_concurrency_limit": (
                        "UNBOUNDED" if node.node_type == "d" else int(node.station_chargers or 0)
                    ),
                    "capacity_mode": "unbounded" if node.node_type == "d" else "finite_instance",
                    "charge_power_kw": float(node.charge_power_kw),
                    "parameter_class": (
                        next(item for item in fleet_rows if item["depot_id"] == node.node_id)["charger_parameter_class"]
                        if node.node_type == "d"
                        else (
                            station_assignments[node.node_id]["parameter_class"]
                            if node.node_id in station_assignments
                            else facilities[str(node.city)]["station_parameter_class"]
                        )
                    ),
                }
            )
            for node in nodes
            if node.node_type in {"d", "f"}
        }
    )
    source_paths = {
        "catalog": str((package_root / "instance_catalog.csv").relative_to(repo)),
        "nodes": str((saved_root / "nodes.csv").relative_to(repo)),
        "orders": str((saved_root / "orders.csv").relative_to(repo)),
        "road_matrices": str(matrix_root.relative_to(repo)),
        "tariff_carbon_calendar": str(
            resolve_calendar_path(runtime_root).relative_to(repo)
        ),
        "vehicle_cost_authority": str(
            (
                cost_contract_path
                if cost_contract_path.is_file()
                else repo / "data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv"
            ).relative_to(repo)
        ),
        "finite_fleet_authority": str(
            (package_root / "fleet_caps.csv").relative_to(repo)
        ),
        "facilities": str(facilities_path.relative_to(repo)),
    }
    bundle = China81Bundle(
        instance_id=instance_id,
        region=str(catalog["region"]).strip().lower(),
        date="2025-02-12",
        instance=instance,
        time_profile=time_profile,
        prices=prices,
        source_paths=MappingProxyType(source_paths),
        customer_home_depot=customer_home_depot,
        price_area_by_city=MappingProxyType(
            {city: runtime_binding[city]["price_area_id"] for city in sorted(cities)}
        ),
        carbon_source_column_by_city=MappingProxyType(
            {city: runtime_binding[city]["carbon_source_column"] for city in sorted(cities)}
        ),
        diesel_zone_by_city=MappingProxyType(
            {city: runtime_binding[city]["diesel_zone"] for city in sorted(cities)}
        ),
        diesel_price_by_city=MappingProxyType(diesel_prices),
        fleet_caps_by_depot=fleet_caps,
        fleet_parameter_class_id=fleet_parameters.parameter_class_id,
        has_additional_total_fleet_cap=fleet_parameters.has_additional_total_fleet_cap,
        charger_scenario_by_node=charger_scenario,
        fleet_cap_semantics=FLEET_CAP_SEMANTICS,
        diesel_price_source_id="CHINA-E3-FORMAL-RELEASE-001__2025-02-12_CITY_DEPOT_PRICE",
        static_input_authority=str(package_root.relative_to(repo)),
        road_matrix_authority=str(matrix_authority.relative_to(repo)),
        runtime_parameter_authority=str(runtime_root.relative_to(repo)),
        fleet_authority=str(package_root.relative_to(repo)),
        model_config=MappingProxyType(ModelConfig().as_metadata()),
        formal_search_allowed=False,
        enterprise_depot_by_id=MappingProxyType(enterprise_depot_by_id),
    )
    return bundle, orders_by_customer




def _suite_context_from_built(
    repo: Path,
    instance_id: str,
    *,
    package_root: Path,
    report_root: Path,
    built: Any,
    template: Any,
    matrix_authority: str,
    fleet_parameters: China81FleetParameterClass,
    ev_cap_override: Mapping[str, int | tuple[int, int]] | None = None,
    ev_daily_premium_cny: float | None = None,
    carbon_quota_kg: float | None = None,
):
    """Turn one saved V3 two-shift construction into a private context."""

    from setp_solver.private_instance_rebuild_20260811 import (
        EV_DAILY_FIXED_PREMIUM_CNY,
    )

    effective_ev_daily_premium_cny = (
        EV_DAILY_FIXED_PREMIUM_CNY
        if ev_daily_premium_cny is None
        else float(ev_daily_premium_cny)
    )
    # 碳限额与交易杠杆（2026-09-06）：算例自带的配额是 0 kg，即"全部排放都要
    # 买单"。把它调高就是发放免费配额，cost.py:230 的碳成本
    # ``(E_total - Q) * carbon_price`` 线性且允许为负，负值即把富余配额卖出。
    # 这里只改评价上下文里的 Q，不动车辆权威值，也不动受保护文件。
    effective_carbon_quota_kg = (
        DEFAULT_CARBON_QUOTA_KG
        if carbon_quota_kg is None
        else float(carbon_quota_kg)
    )

    saved_root = package_root / "instances" / instance_id
    shift_contract = json.loads(
        (saved_root / "shift_contract.json").read_text(encoding="utf-8")
    )
    shift_windows = {
        shift_id: (
            float(row["start_minute"]) * 60.0,
            float(row["end_minute"]) * 60.0,
        )
        for shift_id, row in shift_contract["shifts"].items()
    }
    fleet_rows = [
        row
        for row in _csv_rows(package_root / "fleet_caps.csv")
        if row["instance_id"] == PACKAGE_CATALOG_ALIAS.get(instance_id, instance_id)
    ]
    if not fleet_rows:
        raise ValueError(f"suite fleet rows are missing for {instance_id}")
    if {row["fleet_parameter_class"] for row in fleet_rows} != {
        fleet_parameters.parameter_class_id
    }:
        raise ValueError(f"suite fleet class disagrees for {instance_id}")
    fleet_caps = MappingProxyType(
        {
            row["depot_id"]: MappingProxyType(
                {
                    "num_cv": int(row["base_all_cv_routes_Rd"]),
                    "num_ev": int(row["base_all_ev_routes_Re"]),
                    "total_fleet_cap": (
                        int(row["base_all_cv_routes_Rd"])
                        + int(row["base_all_ev_routes_Re"])
                    ),
                }
            )
            for row in fleet_rows
        }
    )
    if ev_cap_override:
        fleet_caps = _apply_ev_cap_override(fleet_caps, ev_cap_override)
    instance = replace(
        built.instance,
        num_cv=sum(caps["num_cv"] for caps in fleet_caps.values()),
        num_ev=sum(caps["num_ev"] for caps in fleet_caps.values()),
    )
    if instance.num_cv + instance.num_ev < 1:
        raise ValueError(f"suite fleet caps leave no vehicles for {instance_id}")
    if ev_cap_override is None and (instance.num_cv < 1 or instance.num_ev < 1):
        raise ValueError(f"suite fleet caps have no active mixed fleet for {instance_id}")
    depot_charger_scenario = {
            row["depot_id"]: MappingProxyType(
                {
                    "charger_count": configured_depot_gun_count(row),
                    "active_concurrency_limit": "UNBOUNDED",
                    "capacity_mode": "unbounded",
                    "charge_power_kw": float(row["depot_charge_power_kw"]),
                    "parameter_class": row["charger_parameter_class"],
                }
            )
            for row in fleet_rows
        }
    public_station_ids = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "f"
    }
    charger_scenario = MappingProxyType(
        {
            **{
                node_id: template.charger_scenario_by_node[node_id]
                for node_id in public_station_ids
            },
            **depot_charger_scenario,
        }
    )
    bundle = replace(
        template,
        instance_id=instance_id,
        region=built.identity.region,
        instance=instance,
        time_profile=list(built.time_profile),
        prices=built.prices,
        source_paths=MappingProxyType(
            {
                **dict(template.source_paths),
                "suite": str(package_root.relative_to(repo)),
                "instance": str(saved_root.relative_to(repo)),
                "matrix_reference": str(
                    (saved_root / "matrix_reference.json").relative_to(repo)
                ),
                "health_witness_routes": str(
                    (report_root / "health_witness_routes.csv").relative_to(repo)
                ),
                "shift_contract": str(
                    (saved_root / "shift_contract.json").relative_to(repo)
                ),
            }
        ),
        customer_home_depot=built.customer_home_depot,
        fleet_caps_by_depot=fleet_caps,
        fleet_parameter_class_id=fleet_parameters.parameter_class_id,
        has_additional_total_fleet_cap=fleet_parameters.has_additional_total_fleet_cap,
        charger_scenario_by_node=charger_scenario,
        static_input_authority=str(package_root.relative_to(repo)),
        road_matrix_authority=matrix_authority,
        fleet_authority=str(package_root.relative_to(repo)),
        formal_search_allowed=False,
    )
    # A derived instance (see PACKAGE_CATALOG_ALIAS) shares the base instance's
    # saved health witness: the witness is a route skeleton over the same
    # customers, depots and shift ids, and its departure/return minutes are
    # only validated as numbers, never carried into the individual.
    witness_row_id = PACKAGE_CATALOG_ALIAS.get(instance_id, instance_id)
    try:
        individual = adapt_witness_rows_to_duty(
            (
                row
                for row in _csv_rows(report_root / "health_witness_routes.csv")
                if row["instance_id"] == witness_row_id
            ),
            instance_id=witness_row_id,
            bundle=bundle,
            register_idle_duties=_with_registered_idle_duties,
        )
    except RuntimeError:
        if not ev_cap_override:
            raise
        # Fleet-configuration rungs can retire the CV slots the all-CV health
        # witness occupies; those rungs start from registered idle slots with
        # every customer unserved instead.
        individual = register_all_vehicle_slots(
            DutyIndividual(
                duties=(),
                unserved_customers=tuple(sorted(built.orders_by_customer)),
                source="config-axis-idle-init",
            ),
            bundle,
        )
    neutral = {
        node.node_id: 1.0
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    }
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=neutral,
        prior_profit={depot_id: 0.0 for depot_id in neutral},
        theta=0.0,
        carbon_quota_kg=effective_carbon_quota_kg,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
        fairness_enabled=False,
        ev_daily_fixed_premium_cny=effective_ev_daily_premium_cny,
        shift_aware_departure_enabled=True,
        rebuilt_route_constraints=RebuiltRouteConstraintContract(
            source_id=str((saved_root / "shift_contract.json").relative_to(repo)),
            customer_shift_by_id={
                customer_id: str(row["shift_id"])
                for customer_id, row in built.orders_by_customer.items()
            },
            customer_volume_m3_by_id={
                customer_id: float(row["source_volume_m3"])
                for customer_id, row in built.orders_by_customer.items()
            },
            shift_window_second_by_id=shift_windows,
            vehicle_volume_capacity_m3=float(
                shift_contract["vehicle_volume_capacity_m3"]
            ),
        ),
    )
    return bundle, individual, neutral, context


def _build_saved_suite_context(
    repo: Path,
    instance_id: str,
    *,
    package_root: Path,
    report_root: Path,
    fleet_parameters: China81FleetParameterClass,
    ev_cap_override: Mapping[str, int | tuple[int, int]] | None = None,
    tariff_calendar_authority: Path | str | None = None,
    ev_daily_premium_cny: float | None = None,
    carbon_quota_kg: float | None = None,
):
    """Load any sealed V3 two-shift suite through its package contract."""

    bundle, orders_by_customer = _load_v3_suite_bundle(
        repo,
        package_root=package_root,
        instance_id=instance_id,
        fleet_parameters=fleet_parameters,
        ev_cap_override=ev_cap_override,
        tariff_calendar_authority=tariff_calendar_authority,
        ev_daily_premium_cny=ev_daily_premium_cny,
    )
    return _suite_context_from_built(
        repo,
        instance_id,
        package_root=package_root,
        report_root=report_root,
        built=SimpleNamespace(
            identity=SimpleNamespace(region=bundle.region),
            instance=bundle.instance,
            time_profile=bundle.time_profile,
            prices=bundle.prices,
            source_bundle=bundle,
            customer_home_depot=bundle.customer_home_depot,
            orders_by_customer=orders_by_customer,
        ),
        template=bundle,
        matrix_authority=bundle.road_matrix_authority,
        fleet_parameters=fleet_parameters,
        ev_cap_override=ev_cap_override,
        ev_daily_premium_cny=ev_daily_premium_cny,
        carbon_quota_kg=carbon_quota_kg,
    )



def _with_registered_idle_duties(
    individual: DutyIndividual,
    bundle,
) -> DutyIndividual:
    """Represent every registered vehicle, including currently idle assets."""
    return register_all_vehicle_slots(individual, bundle)


def _dynamic_insertion_technical_cut(
    bundle,
    initial: DutyIndividual,
    context: DutyEvaluationContext,
) -> tuple[DutyIndividual, DutyEvaluationContext, str]:
    """Build one controlled 13:00 reveal without reading a truth stream."""

    target_asset = "CV_D_guangzhou_4"
    rebuilt_duties = []
    revealed = None
    for duty in initial.duties:
        if duty.physical_vehicle_id != target_asset:
            rebuilt_duties.append(duty)
            continue
        if not duty.trips or not duty.trips[0].customer_ids:
            raise ValueError("dynamic insertion probe target duty is empty")
        trip = duty.trips[0]
        revealed = trip.customer_ids[-1]
        rebuilt_duties.append(
            replace(
                duty,
                trips=(
                    replace(
                        trip,
                        customer_ids=trip.customer_ids[:-1],
                    ),
                ),
            )
        )
    if revealed is None:
        raise ValueError("dynamic insertion probe target asset is absent")

    partial = replace(
        initial,
        duties=tuple(rebuilt_duties),
        unserved_customers=(revealed,),
        source="dynamic-insertion-technical-cut",
    )
    source_solution, source_certificate = prepare_multitrip_solution(
        partial.to_solution(),
        bundle.instance,
        bundle.prices,
        depot_charge_window_mode=context.depot_charge_window_mode,
    )
    trigger = 46_800.0
    cut = cut_certificate_at_trigger(
        source_solution,
        source_certificate,
        bundle.instance,
        bundle.prices,
        trigger_second=trigger,
    )
    battery_capacity = bundle.instance.battery_capacity_kwh(
        fallback=bundle.prices.B_battery_kwh
    )
    assets = {
        duty.physical_vehicle_id: cut.asset_states.get(
            duty.physical_vehicle_id,
            DynamicAssetState(
                duty.physical_vehicle_id,
                duty.vehicle_type,
                duty.home_depot_id,
                trigger,
                battery_capacity if duty.vehicle_type == "ev" else 0.0,
                1,
            ),
        )
        for duty in initial.duties
    }
    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    committed_route_ids = {
        *cut.completed_route_ids,
        *cut.in_progress_route_ids,
    }
    committed_customers = {
        node_id
        for route in source_solution.routes
        if route.vehicle_id in committed_route_ids
        for node_id in route.node_sequence[1:-1]
        if node_id in customer_ids
    }
    state = DutyDynamicState(
        source_solution=source_solution,
        cut=cut,
        asset_states=MappingProxyType(assets),
        future_customer_ids=frozenset(
            customer_ids.difference(committed_customers)
        ),
        customer_appearance_second={
            customer_id: trigger if customer_id == revealed else 0.0
            for customer_id in customer_ids
        },
        charging_strategy="aware",
        charging_intensity_field="forecast_gco2_per_kwh",
    )
    future = future_individual_from_cut(
        state,
        source_certificate,
        bundle.instance,
    )
    return (
        future,
        replace(
            context,
            dynamic_state=state,
        ),
        revealed,
    )


def _parse_mechanism_off(value: str) -> frozenset[str]:
    requested = frozenset(
        item.strip() for item in str(value).split(",") if item.strip()
    )
    unknown = sorted(requested.difference(MECHANISM_NAMES))
    if unknown:
        raise ValueError("unknown mechanism group(s): " + ", ".join(unknown))
    return requested


def _customer_structure(
    individual: DutyIndividual,
) -> tuple[dict[str, str], dict[str, str]]:
    depot_by_customer: dict[str, str] = {}
    type_by_customer: dict[str, str] = {}
    for duty in individual.duties:
        for trip in duty.trips:
            for customer in trip.customer_ids:
                depot_by_customer[customer] = duty.home_depot_id
                type_by_customer[customer] = duty.vehicle_type
    return depot_by_customer, type_by_customer


def _mechanism_closure_violations(
    reference: DutyIndividual,
    candidate: DutyIndividual,
    mechanism_enabled: Mapping[str, bool],
) -> tuple[str, ...]:
    reference_depot, reference_type = _customer_structure(reference)
    candidate_depot, candidate_type = _customer_structure(candidate)
    violations: list[str] = []
    if not mechanism_enabled["cross_depot"]:
        changed = sorted(
            customer
            for customer, depot_id in reference_depot.items()
            if candidate_depot.get(customer) != depot_id
        )
        if changed:
            violations.append("cross_depot:" + ",".join(changed))
    if not mechanism_enabled["type_exchange"]:
        changed = sorted(
            customer
            for customer, vehicle_type in reference_type.items()
            if candidate_type.get(customer) != vehicle_type
        )
        if changed:
            violations.append("type_exchange:" + ",".join(changed))
    if not mechanism_enabled["multi_trip"]:
        changed = sorted(
            duty.physical_vehicle_id
            for duty in candidate.duties
            if len(duty.trips) > 1
        )
        if changed:
            violations.append("multi_trip:" + ",".join(changed))
    return tuple(violations)


def _move_mechanism_enabled(
    channel: str,
    mechanism_enabled: Mapping[str, bool],
) -> bool:
    mechanism_by_channel = {
        "depot_collaboration": "cross_depot",
        "fairness_cross_depot": "cross_depot",
        "multi_trip": "multi_trip",
        "whole_duty_type_exchange": "type_exchange",
        "time_varying_carbon_charge": "charge_timing",
    }
    mechanism = mechanism_by_channel.get(str(channel))
    return mechanism is None or bool(mechanism_enabled[mechanism])


def _single_trip_initial(individual: DutyIndividual) -> DutyIndividual:
    """Place every existing trip on one same-type, same-depot idle asset."""

    if any(
        trip.locked_customer_prefix
        or trip.trip_index in duty.locked_charging_trip_indices
        or any(session.locked for session in duty.charging_sessions)
        for duty in individual.duties
        for trip in duty.trips
    ):
        raise ValueError("single-trip initialization cannot rewrite locked Duty")
    duties = list(individual.duties)
    idle_by_group: dict[tuple[str, str], list[int]] = {}
    for index, duty in enumerate(duties):
        if not duty.trips:
            idle_by_group.setdefault(
                (duty.home_depot_id, duty.vehicle_type), []
            ).append(index)
    for index, duty in enumerate(tuple(duties)):
        if len(duty.trips) <= 1:
            continue
        group = (duty.home_depot_id, duty.vehicle_type)
        extras = duty.trips[1:]
        available = idle_by_group.get(group, [])
        if len(available) < len(extras):
            raise ValueError(
                "single-trip initialization lacks same-type, same-depot idle assets"
            )
        duties[index] = replace(
            duty,
            trips=(replace(duty.trips[0], trip_index=1),),
            charging_sessions=(),
        )
        for trip in extras:
            receiver_index = available.pop(0)
            receiver = duties[receiver_index]
            duties[receiver_index] = replace(
                receiver,
                trips=(
                    replace(
                        trip,
                        trip_index=1,
                        locked_customer_prefix=(),
                    ),
                ),
                charging_sessions=(),
            )
    result = DutyIndividual(
        duties=tuple(duties),
        unserved_customers=individual.unserved_customers,
        source=individual.source + ":single-trip-mechanism-off",
    )
    if any(len(duty.trips) > 1 for duty in result.duties):
        raise RuntimeError("single-trip initialization remained multi-trip")
    if _customer_structure(result) != _customer_structure(individual):
        raise RuntimeError("single-trip initialization changed customer structure")
    return result


def _prepare_population(
    initial: DutyIndividual,
    evaluator: DutyFullEvaluator,
    policy: ChargingRepairPolicy,
    *,
    mechanism_enabled: Mapping[str, bool] | None = None,
):
    initial_evaluation = evaluator.evaluate(initial)
    second = None
    second_evaluation = None
    for move in generate_problem_moves(
        initial,
        initial_evaluation,
        evaluator.context.bundle.instance,
    ):
        if mechanism_enabled is not None and not _move_mechanism_enabled(
            move.channel,
            mechanism_enabled,
        ):
            continue
        outcome = evaluate_move(
            initial,
            move,
            evaluator=evaluator,
            charging_policy=policy,
        )
        if (
            outcome.status == CandidateStatus.EVALUATED
            and outcome.candidate is not None
            and outcome.evaluation is not None
            and outcome.candidate != initial
            and (
                mechanism_enabled is None
                or not _mechanism_closure_violations(
                    initial,
                    outcome.candidate,
                    mechanism_enabled,
                )
            )
        ):
            second = outcome.candidate
            second_evaluation = outcome.evaluation
            break
    if second is None or second_evaluation is None:
        raise RuntimeError("no deterministic, fully evaluated distinct second parent")

    candidates = (initial, second, initial, second)
    return candidates, initial_evaluation, (initial_evaluation, second_evaluation) * 2



def _write_failure_package(output: Path, error: Exception) -> bool:
    """Complete an output directory created by this invocation as failed."""

    metadata_path = output / "metadata.json"
    if not metadata_path.is_file():
        return False
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "RUNNING":
        return False
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("verdict", "error_type", "error"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "verdict": FAILURE_VERDICT,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    failure_reason = f"{type(error).__name__}: {error}"
    acceptance = assess_run(
        termination_ok=None,
        feasible_ok=None,
        customers_complete=None,
        demand_complete=None,
        extra_failure_reasons=(failure_reason,),
        success_verdict=SUCCESS_VERDICT,
        failure_verdict=FAILURE_VERDICT,
    )
    decision = {
        "traceback": traceback.format_exc(),
    }
    report = f"""# Problem-HGS 真实输入运行失败报告

## 结论

错误类型为 `{type(error).__name__}`，错误信息为：{error}。完整调用栈保存在 `decision.json`。
"""
    finalize_run_output(
        output,
        acceptance=acceptance,
        metadata=metadata,
        decision=decision,
        report_text=report,
    )
    return True

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--data-repo-root", type=Path)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument(
        "--tariff-calendar-authority",
        type=Path,
        default=Path(DEFAULT_TARIFF_CALENDAR_AUTHORITY),
        help=(
            "repository-relative directory holding "
            "tariff_carbon_hourly_calendar.csv; the default is the approved "
            "runtime parameter authority"
        ),
    )
    parser.add_argument(
        "--ev-daily-premium",
        type=float,
        default=None,
        help=(
            "EV daily fixed premium over a CV in CNY/day; the default keeps the "
            "approved vehicle authority (EV_DAILY_FIXED_PREMIUM_CNY = 100). "
            "Lowering it is the electric-vehicle subsidy lever: it rewrites the "
            "EV daily fixed cost to CV + premium, so both the kernel proxy and "
            "the exact account see it"
        ),
    )
    parser.add_argument(
        "--carbon-quota-kg",
        type=float,
        default=None,
        help=(
            "free carbon allowance in kgCO2e per day; the default keeps the "
            f"instance value ({DEFAULT_CARBON_QUOTA_KG:g} kg = no free "
            "allowance). The exact account charges "
            "(E_total - quota) * carbon_price and allows a negative carbon "
            "cost, so a quota above the plan's emissions is sold back. The "
            "route proxy carries no quota term, which is consistent: the term "
            "is a constant in the emissions, so its marginal effect on any "
            "routing decision is zero"
        ),
    )
    parser.add_argument(
        "--enterprise-id",
        help="run one enterprise's depot and fleet over the full shared market",
    )
    parser.add_argument(
        "--initial-solution",
        type=Path,
        help="inject one saved complete solution into the initial population",
    )
    parser.add_argument(
        "--enterprise-init-constructor",
        choices=("random", "greedy_repair"),
        default="random",
        help="native constructor for an enterprise initial population",
    )
    parser.add_argument(
        "--carbon-price",
        type=float,
        default=CHINA81_CARBON_PRICE_CNY_PER_KG,
        help="carbon price in CNY/kg; default preserves the China81 constant",
    )
    parser.add_argument(
        "--ev-cap-override",
        help=(
            "fleet-configuration sensitivity: comma-joined DEPOT_ID=NUM_EV pairs; "
            "each depot keeps its total slot cap and num_cv becomes total-num_ev"
        ),
    )
    parser.add_argument(
        "--fleet-mix-override",
        help=(
            "fleet-configuration sensitivity: comma-joined DEPOT_ID=NUM_CV/NUM_EV "
            "triples; both type counts are written as given, so a rung can state a "
            "fleet composition the depot's own slot total cannot express. "
            "Mutually exclusive with --ev-cap-override."
        ),
    )
    parser.add_argument(
        "--recharge-mode",
        choices=("on_demand", "full"),
        default="on_demand",
        help="charging-function arm: on_demand keeps the formal rule; full recharges to capacity after every trip",
    )
    parser.add_argument(
        "--depot-curve",
        choices=("registered", "linear"),
        default="registered",
        help="charging-function arm: linear swaps the depot curve for the constant-power L100 control",
    )
    parser.add_argument("--convergence-csv", type=Path)
    parser.add_argument(
        "--education-depth-limit",
        type=int,
        default=None,
        help=(
            "maximum education rounds per child; omitted keeps the current "
            "unlimited behavior"
        ),
    )
    parser.add_argument(
        "--population-mode",
        choices=("technical_two_parent", "copied_hgs_defaults"),
        default="copied_hgs_defaults",
    )
    parser.add_argument(
        "--objective-mode",
        choices=(SINGLE_OBJECTIVE,),
        default=SINGLE_OBJECTIVE,
    )
    parser.add_argument("--arm", default=ARM)
    parser.add_argument(
        "--fleet-parameter-class",
        choices=tuple(FLEET_PARAMETER_CLASSES),
        default="fixed25",
    )
    parser.add_argument(
        "--depot-charging-scenario",
        choices=("60kw",),
        default="60kw",
        help="active private-suite depot power/registered-curve pairing",
    )
    parser.add_argument(
        "--first-trip-prev-night",
        action="store_true",
        help=(
            "merge previous-day and same-day predeparture charging candidates "
            "for the first trip of each physical-vehicle duty"
        ),
    )
    parser.add_argument(
        "--first-trip-window",
        choices=FIRST_TRIP_WINDOWS,
        default=FIRST_TRIP_WINDOW_PREV_RETURN,
        help=(
            "when the first trip's pre-departure depot charge may start: "
            "'prev_return' opens the window when the vehicle came back to the "
            "depot the preceding evening -- the paper's formal setting since "
            "2026-09-06 and the default here; 'same_day' opens it at the "
            "simulation day's 00:00, the behaviour of every batch run before "
            "that date, kept so those batches can be reproduced"
        ),
    )
    parser.add_argument(
        "--charge-timing-policy",
        choices=tuple(sorted(CHARGE_TIMING_POLICIES)),
        default="cost_plus_carbon",
        help="charging-start policy used by both paired arms",
    )
    parser.add_argument(
        "--lazy-exact",
        action="store_true",
        help=(
            "only charge-repair and exactly evaluate a crossover child whose "
            "kernel penalised cost is no worse than the worst exact feasible "
            "member (integrated search mode)"
        ),
    )
    parser.add_argument(
        "--ev-departure-gap-proxy",
        action="store_true",
        help=(
            "route kernel: every EV arc leaving a depot carries the charge "
            "time of the largest reference trip, so kernel-feasible chains "
            "always leave a gap the exact repair can fill"
        ),
    )
    parser.add_argument(
        "--ev-reload-gap-proxy",
        action="store_true",
        help=(
            "route kernel (fleet-composition experiment only): every depot "
            "gets a reload copy; EV arcs leaving the copy carry the "
            "between-trip charging time, arcs leaving the real depot carry "
            "none because the first trip charges before the day starts.  "
            "Which charging time: in round one the --reload-gap-quantile "
            "order statistic of the initial population's own pooled "
            "between-trip sessions, and from round two on the same order "
            "statistic of the exact best's sessions.  At --reload-gap-quantile "
            "exactly 1.0 round one has no population statistic to fall back "
            "on and reserves the charge time of the witness's largest trip "
            "instead, which is the pre-2026-09-05 behaviour.  Exclusive with "
            "--ev-departure-gap-proxy"
        ),
    )
    parser.add_argument(
        "--reload-gap-quantile",
        type=float,
        default=RELOAD_GAP_QUANTILE,
        help=(
            "route kernel, --ev-reload-gap-proxy only: which order statistic "
            "of measured between-trip charging sessions a round reserves -- "
            "the initial population's pooled sessions in round one, the "
            "exact best's own sessions from round two on.  Exactly 1.0 is a "
            "discontinuity, not a limit: it reproduces the pre-2026-09-05 "
            "behaviour bit for bit, which means round one reserves the charge "
            "time of the witness's largest trip (no population statistic) and "
            "later rounds reserve the longest single session.  The 0.75 default is internal "
            "calibration on this instance and machine, not a literature "
            "value: the 101 real sessions of the P=0.2 midday-valley batch "
            "have p50 1348 s, p75 1875 s, p90 2614 s, while reserving the "
            "longest booked 2380-2642 s -- at 2614.1 s the kernel judged 25 "
            "of 33 exactly-feasible solutions infeasible, at the 1875.3 s "
            "this default feeds back it judges 4 (docs/handoff/"
            "second_root_cause_reload_gap_20260905.md section 3.2)"
        ),
    )
    parser.add_argument(
        "--round-one-starts",
        type=int,
        default=ROUND_ONE_STARTS_DEFAULT,
        help=(
            "route kernel, --search-mode kernel_native only: how many "
            "independent kernel searches round one runs before the exact "
            "stage.  The start with the lowest kernel_best_cost (the "
            "kernel's own in-round feasible proxy best, already recorded "
            "every round) is kept and the run continues from it; the losers "
            "are dropped without ever reaching a complete evaluation, which "
            "is why K starts cost about K times round one's KERNEL time and "
            "nothing else.  1 reproduces the pre-2026-09-08 behaviour bit "
            "for bit (one start per run).  The default is 3, not 1, because "
            "a run's outcome is settled in round one -- round-one exact best "
            "against final cost has Spearman 0.748 -- and under one start "
            "that round is a lottery worth 37-60 CNY of proxy cost on one "
            "and the same cost table (docs/handoff/"
            "fleet_dispersion_kernel_vs_python_20260908.md sections 2.4, 3.4)"
        ),
    )
    parser.add_argument(
        "--proxy-estimate-source",
        choices=PROXY_ESTIMATE_SOURCES,
        default=PROXY_ESTIMATE_SOURCE_DEFAULT,
        help=(
            "route kernel: where the two route-independent anchors of the EV "
            "proxy come from -- the between-trip charging reservation and the "
            "opening instant of the first shift's charging window.  "
            "'population' is the pre-2026-09-08 behaviour: each run estimates "
            "both from its OWN random initial population and re-estimates the "
            "reservation every round, which made 40 measured runs spread "
            "1348-2117 s and 55619-58732 s, i.e. ten runs of an arm were ten "
            "different proxy problems.  'reference' (the default) takes both "
            "from batch-wide constants and holds them for every round of the "
            "run, so the ten runs of an arm face one and the same cost table "
            "and the round-two reservation can no longer push the previous "
            "round's own exact best into the kernel's infeasible "
            "subpopulation.  The constants are the 40-run medians of the same "
            "estimator, NOT statistics of the reference solution: that "
            "solution is all-fuel and carries neither statistic (see "
            "PROXY_REFERENCE_RELOAD_GAP_SECONDS).  It does not touch the "
            "second-phase ev_unit_cost feedback, which still rescales the "
            "price LEVEL each round"
        ),
    )
    parser.add_argument(
        "--max-reloads-per-vehicle",
        default="8",
        help=(
            "route kernel: how many depot reload slots each vehicle gets in "
            "the kernel model.  ``auto`` (or 0) restores the theoretical "
            "bound of one trip per customer, 49 on the 50-customer instance, "
            "which is what the kernel carried up to 2026-09-05.  The default "
            "8 is internal calibration, not a literature value: the largest "
            "duty in every dumped best_solution.json of the 2026-09-04/05 "
            "batches runs 5 trips (4 reloads), so 8 leaves headroom of three "
            "trips above anything the exact model has ever accepted"
        ),
    )
    parser.add_argument(
        "--kernel-vehicle-type-dedup",
        choices=("on", "off"),
        default="on",
        help=(
            "route kernel: give one kernel vehicle type to each distinct "
            "parameter vector (``on``, the default) instead of one to each "
            "physical vehicle (``off``, the pre-2026-09-05 model).  The "
            "per-vehicle type only ever existed so a returned route could be "
            "mapped back to its asset; the decoder now recovers that inside "
            "the group.  The kernel probes empty routes once per vehicle type "
            "for every customer and every step and 14-15 of the 20 routes sit "
            "empty in every dumped plan, so the count is a real per-iteration "
            "cost: 3.451 -> 3.140 ms/iteration measured on this instance "
            "(docs/handoff/per_iteration_cost_design_20260905.md sections "
            "1.2/2.1).  Merging is by full parameter vector -- it collapses "
            "20 types to 4 and 4 profiles to 2 on the static batch and falls "
            "back to one type per vehicle under a dynamic cut, where tw_early "
            "differs per vehicle.  The solution space and every cost field are "
            "unchanged (verified bit for bit on 48 dumped plans), but the "
            "empty-route probe order is not, so the same seed walks a "
            "different trajectory than an ``off`` run"
        ),
    )
    parser.add_argument(
        "--confirming-round",
        action="store_true",
        help=(
            "kernel_native: keep repeating the priced search phase until a "
            "round no longer improves the exact best (default: exactly one "
            "priced phase)"
        ),
    )
    parser.add_argument(
        "--confirming-round-patience-mode",
        choices=("fixed", "adaptive"),
        default="adaptive",
        help=(
            "kernel_native: how many non-improving kernel iterations a round "
            "from the second on is given.  ``fixed`` gives every round "
            "--stagnation-patience and reproduces the pre-2026-09-05 "
            "behaviour bit for bit.  ``adaptive`` (default) is internal "
            "calibration on this run's own round one, not a literature "
            "value: the round is given the widest wait between two "
            "consecutive kernel improvements observed so far, clamped into "
            "[--confirming-patience-floor, --stagnation-patience].  Round one "
            "always keeps --stagnation-patience.  Evidence: across the 6 runs "
            "/ 16 rounds of solver/reports/reload_fix_shortrun_20260905, 8 of "
            "the 10 rounds after the first improved nothing and each burned "
            "the full 20000 (43%% of total wall clock), while the two rounds "
            "that did improve found it at in-round iteration 2720 and 13258 "
            "-- both inside that run's own round-one widest wait of 15812.  "
            "The rule reaches round two of an ordinary two-phase run too, not "
            "only the repeated rounds of --confirming-round"
        ),
    )
    parser.add_argument(
        "--confirming-patience-floor",
        type=int,
        default=CONFIRMING_ROUND_PATIENCE_FLOOR,
        help=(
            "kernel_native, --confirming-round-patience-mode adaptive only: "
            "the shortest patience a round from the second on may be given, "
            "so a round one that converged fast does not turn the confirming "
            "round into a formality.  --stagnation-patience still wins a "
            "conflict: no round may run longer than the run's declared upper "
            "bound"
        ),
    )
    parser.add_argument(
        "--stop-after-nonimproving-rounds",
        type=int,
        default=STOP_AFTER_NONIMPROVING_ROUNDS,
        help=(
            "kernel_native, --confirming-round only: how many outer rounds in "
            "a row must fail to improve the exact best before the run stops.  "
            "1 reproduces the pre-2026-09-05 rule (any single non-improving "
            "round ends the run) bit for bit.  The default 2 is internal "
            "calibration on this project's own runs, not a literature value: "
            "docs/handoff/run_variance_diagnosis_20260905.md measures a run "
            "that reached a third round at 18.47 CNY (B batch, 2CV/3EV, 4 vs "
            "2 runs) and 19.19 CNY (A batch, same fleet, 1 vs 5) below one "
            "that did not, while the charge-timing effect under test is 7-10 "
            "CNY -- so whether a run got its third round was a coin flip, not "
            "a convergence test.  Expect 40-70 percent more wall clock"
        ),
    )
    parser.add_argument(
        "--max-outer-rounds",
        type=int,
        default=MAX_OUTER_ROUNDS,
        help=(
            "kernel_native only: hard ceiling on the number of outer rounds.  "
            "Before 2026-09-05 the --confirming-round loop had no ceiling at "
            "all; with --stop-after-nonimproving-rounds above 1 an "
            "improve/no-improve alternation would never terminate without "
            "one.  Every run on record stopped within 4 rounds, so the "
            "default 8 has never bound"
        ),
    )
    parser.add_argument(
        "--search-mode",
        choices=("integrated", "kernel_native"),
        default="integrated",
        help=(
            "integrated: one exact evaluation per child (current loop); "
            "kernel_native: the kernel searches the route proxy to the "
            "stopping rule, the exact model judges its population, realised "
            "EV price feeds back (Montoya 2017 / Froger 2019 decomposition)"
        ),
    )
    parser.add_argument(
        "--no-ev-charge-time-proxy",
        action="store_true",
        help=(
            "build the route kernel without EV charge-time amortisation "
            "(2026-09-02 A: EV arc duration = travel + energy / P_eff)"
        ),
    )
    parser.add_argument(
        "--proxy-feasible-slots",
        action="store_true",
        help=(
            "shift-aware EV route proxy prices each charging window only from "
            "calendar rows that can host the reference charge before departure "
            "(2026-09-10); default off keeps every existing run bit-identical"
        ),
    )
    parser.add_argument(
        "--frvcpy-charging",
        action="store_true",
        help=(
            "use pinned frvcpy for fixed-route charging sites and amounts; "
            "default keeps the existing charging repair"
        ),
    )
    parser.add_argument(
        "--depot-assignment-operator",
        action="store_true",
        help=(
            "enable incremental cross-depot prefix/suffix migration into an "
            "empty same-vehicle-class duty"
        ),
    )
    parser.add_argument(
        "--dynamic-insertion-operator",
        action="store_true",
        help=(
            "technical V3 cut: insert one newly revealed PM order through "
            "the cached incremental dynamic operator; default is disabled"
        ),
    )
    parser.add_argument(
        "--mechanism-off",
        default="",
        help=(
            "comma-separated closed mechanism groups: cross_depot,"
            "multi_trip,type_exchange,charge_timing"
        ),
    )
    parser.add_argument(
        "--init-witness",
        action="store_true",
        help=(
            "restore the witness-perturbation initial population for the "
            "DEPOTSEARCH instance (default: reference + random construction)"
        ),
    )
    parser.add_argument(
        "--include-charging-candidates",
        action="store_true",
        help=(
            "re-enable the pre-built charging-schedule candidate channel "
            "(off in formal runs: 72,880 evaluations for 1 accept)"
        ),
    )
    parser.add_argument(
        "--charging-prescreen",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable the exact route-clock prescreen",
    )
    parser.add_argument(
        "--public-station-candidate-mode",
        choices=tuple(sorted(PUBLIC_STATION_CANDIDATE_MODES)),
        default=SPLIT_PUBLIC_STATION_CANDIDATE_MODE,
        help=(
            "public-station charging candidates per trip: fallback keeps "
            "stations as a range rescue only, parallel adds one candidate per "
            "station that covers the whole remaining trip, split also divides "
            "the trip energy between the depot and that station"
        ),
    )
    parser.add_argument(
        "--public-station-power-kw",
        type=float,
        default=None,
        help=(
            "exploratory 2026-09-08 switch: rated charging power of every "
            "public station (node type f), in kW.  Unset (the default) keeps "
            "the instance's own 60 kW and executes no override at all.  Only "
            "the reference power the shared fast-charging shape is scaled by "
            "moves; depot power, station tariffs and gun counts are untouched."
        ),
    )
    args = parser.parse_args()
    if args.education_depth_limit is not None and args.education_depth_limit < 1:
        raise ValueError("education depth limit must be positive")
    if not math.isfinite(args.carbon_price) or args.carbon_price < 0.0:
        raise ValueError("carbon price must be finite and non-negative")
    if (
        args.enterprise_id is not None
        and args.population_mode != "copied_hgs_defaults"
    ):
        raise ValueError(
            "enterprise native initialization requires copied_hgs_defaults"
        )
    if (
        args.enterprise_id is None
        and args.enterprise_init_constructor != "random"
    ):
        raise ValueError(
            "enterprise init constructor requires an enterprise id"
        )
    repo = Path(__file__).resolve().parents[2]
    data_repo = (
        repo
        if args.data_repo_root is None
        else args.data_repo_root.resolve()
    )
    output = args.output_dir.resolve()
    mechanism_off = _parse_mechanism_off(args.mechanism_off)
    mechanism_enabled = {
        name: name not in mechanism_off for name in sorted(MECHANISM_NAMES)
    }
    # Reload slots per vehicle in the kernel model (2026-09-05).  ``auto`` and
    # any non-positive integer restore the historic ``len(customers) - 1``
    # bound; a positive integer caps the dimension there.
    _requested_max_reloads = str(args.max_reloads_per_vehicle).strip().lower()
    if _requested_max_reloads == "auto":
        max_reloads_per_vehicle: int | None = None
    else:
        try:
            _parsed_max_reloads = int(_requested_max_reloads)
        except ValueError as error:
            raise ValueError(
                "--max-reloads-per-vehicle expects an integer or 'auto'"
            ) from error
        max_reloads_per_vehicle = (
            None if _parsed_max_reloads <= 0 else _parsed_max_reloads
        )
    charging_prescreen_enabled = bool(args.charging_prescreen)
    effective_first_trip_window = str(args.first_trip_window)
    # The preceding-day half of the first-trip window only survives the ledger
    # replay under the ``full_gap`` depot-window mode: under
    # ``same_day_predeparture`` ``prepare_multitrip_solution`` rewrites every
    # first-trip depot charge onto day offset 0.  So the window rule and the
    # depot-window mode are flipped together, exactly as ``--first-trip-prev-
    # night`` already does below.
    effective_first_trip_prev_night = bool(args.first_trip_prev_night) or (
        effective_first_trip_window == FIRST_TRIP_WINDOW_PREV_RETURN
    )
    effective_depot_assignment_operator = bool(
        args.depot_assignment_operator
        or (
            args.instance_id in DEPOT_SEARCH_INSTANCE_IDS
            and mechanism_enabled["cross_depot"]
        )
    )
    effective_charge_timing_policy = (
        args.charge_timing_policy
        if mechanism_enabled["charge_timing"]
        else "asap"
    )
    from setp_solver.private_instance_rebuild_20260811 import (
        EV_DAILY_FIXED_PREMIUM_CNY,
    )

    effective_ev_daily_premium_cny = (
        EV_DAILY_FIXED_PREMIUM_CNY
        if args.ev_daily_premium is None
        else float(args.ev_daily_premium)
    )
    if (
        not math.isfinite(effective_ev_daily_premium_cny)
        or effective_ev_daily_premium_cny < 0.0
    ):
        raise ValueError("--ev-daily-premium must be finite and non-negative")
    effective_carbon_quota_kg = (
        DEFAULT_CARBON_QUOTA_KG
        if args.carbon_quota_kg is None
        else float(args.carbon_quota_kg)
    )
    if (
        not math.isfinite(effective_carbon_quota_kg)
        or effective_carbon_quota_kg < 0.0
    ):
        raise ValueError("--carbon-quota-kg must be finite and non-negative")
    parameters = _parameters(
        population_mode=args.population_mode,
        objective_mode=args.objective_mode,
        education_depth_limit=args.education_depth_limit,
    )
    effective_population = _effective_population_metadata(
        args.population_mode,
        parameters.population,
    )
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    purpose = "private experiment"
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": purpose,
            "requested_instance_id": args.instance_id,
            "requested_enterprise_id": args.enterprise_id,
            "requested_enterprise_init_constructor": (
                args.enterprise_init_constructor
            ),
            "requested_mechanism_off": sorted(mechanism_off),
            "effective_mechanism_enabled": mechanism_enabled,
            "stagnation_patience": NO_IMPROVEMENT_LIMIT,
            "requested_population_mode": args.population_mode,
            "effective_population": effective_population,
            "requested_objective_mode": args.objective_mode,
            "requested_fleet_parameter_class": args.fleet_parameter_class,
            "requested_depot_charging_scenario": (
                args.depot_charging_scenario
            ),
            "search_mode": args.search_mode,
            "confirming_round": args.confirming_round,
            "confirming_round_patience_mode": (
                args.confirming_round_patience_mode
            ),
            "confirming_patience_floor": int(args.confirming_patience_floor),
            "stop_after_nonimproving_rounds": int(
                args.stop_after_nonimproving_rounds
            ),
            "max_outer_rounds": int(args.max_outer_rounds),
            "lazy_exact": args.lazy_exact,
            "ev_departure_gap_proxy": args.ev_departure_gap_proxy,
            "ev_reload_gap_proxy": args.ev_reload_gap_proxy,
            # 2026-09-05 内部标定，非文献值：本算例本机器本批 101 次真实趟间
            # 充电 p50 1348 / p75 1875 / p90 2614 秒（证据见 docs/handoff/
            # second_root_cause_reload_gap_20260905.md §3.2）。1.0 = 取最大值，
            # 即 2026-09-05 之前的行为，此时第 1 轮取见证解最大趟。小于 1.0
            # 时两轮都用这个分位：第 1 轮取初始种群自己的趟间充电会话分位并
            # 压下限（见脚本内 round-one reload gap 段与
            # route_engine_wiring.reload_gap_round1），第 2 轮起取精确最优自己
            # 的会话分位。每轮实际预留见 accounting.reload_gap_seconds_by_round。
            "reload_gap_quantile": float(args.reload_gap_quantile),
            # 2026-09-05 内部标定，非文献值：所有已落盘 best_solution.json 里
            # 最长的一条任务是 5 趟（4 次回场），默认 8 留三趟余量。None =
            # 恢复历史的 len(customers)-1（本算例 49）。
            "requested_max_reloads_per_vehicle": args.max_reloads_per_vehicle,
            "effective_max_reloads_per_vehicle": max_reloads_per_vehicle,
            # 2026-09-05：内核车辆类型按完整参数向量去重（除车牌名外全同才合
            # 并），本静态批 20 类→4、4 份矩阵→2；动态切片下 tw_early 逐车不
            # 同，会自动退回 20 类。实际生效的份数见 route_engine_wiring 的
            # kernel_num_vehicle_types / kernel_num_profiles。
            "kernel_vehicle_type_dedup": args.kernel_vehicle_type_dedup,
            "fleet_exact_composition": bool(args.fleet_mix_override),
            "requested_charging_prescreen": args.charging_prescreen,
            "effective_charging_prescreen": charging_prescreen_enabled,
            "requested_first_trip_prev_night": args.first_trip_prev_night,
            "effective_first_trip_prev_night": (
                effective_first_trip_prev_night
            ),
            "requested_first_trip_window": args.first_trip_window,
            "effective_first_trip_window": effective_first_trip_window,
            "requested_charge_timing_policy": args.charge_timing_policy,
            "effective_charge_timing_policy": effective_charge_timing_policy,
            "requested_ev_daily_premium_cny": args.ev_daily_premium,
            "effective_ev_daily_premium_cny": effective_ev_daily_premium_cny,
            "requested_carbon_quota_kg": args.carbon_quota_kg,
            "effective_carbon_quota_kg": effective_carbon_quota_kg,
            "requested_frvcpy_charging": args.frvcpy_charging,
            "requested_depot_assignment_operator": (
                args.depot_assignment_operator
            ),
            "effective_depot_assignment_operator": (
                effective_depot_assignment_operator
            ),
            "requested_dynamic_insertion_operator": (
                args.dynamic_insertion_operator
            ),
            # 2026-09-08 尝试性开关。None = 算例自带的 60 kW，不执行任何覆盖。
            # 给值时全部 node_type=f 的公共站参考功率改为该值，曲线形状与
            # 曲线 id 不变（id 里的 60KW 指形状出处，不是生效功率）。
            "public_station_power_kw": args.public_station_power_kw,
        },
    )

    if args.ev_cap_override and args.fleet_mix_override:
        raise ValueError(
            "--ev-cap-override and --fleet-mix-override are mutually exclusive"
        )
    # 2026-09-08：--reload-gap-quantile 1.0 的对外承诺是"逐位复现 2026-09-05
    # 之前的第 1 轮"（预留＝见证解最大趟）；--proxy-estimate-source reference
    # 的对外承诺是"预留＝全批共用常数"。两句话互斥，静默让其中一句赢会让谁都
    # 读不出这一跑到底预留了多少，所以直接拦下来。
    if (
        args.ev_reload_gap_proxy
        and args.proxy_estimate_source == "reference"
        and float(args.reload_gap_quantile) >= 1.0
    ):
        raise ValueError(
            "--reload-gap-quantile 1.0 (the pre-2026-09-05 witness-max round "
            "one) and --proxy-estimate-source reference (the shared constant) "
            "are mutually exclusive; pass --proxy-estimate-source population "
            "to keep the quantile escape hatch"
        )
    ev_cap_override: dict[str, int | tuple[int, int]] | None = None
    if args.ev_cap_override:
        ev_cap_override = {}
        for pair in args.ev_cap_override.split(","):
            depot_id, _, count = pair.strip().partition("=")
            if not depot_id or not count:
                raise ValueError(
                    "--ev-cap-override expects comma-joined DEPOT_ID=NUM_EV pairs"
                )
            ev_cap_override[depot_id] = int(count)
    if args.fleet_mix_override:
        ev_cap_override = {}
        for pair in args.fleet_mix_override.split(","):
            depot_id, _, mix = pair.strip().partition("=")
            num_cv, _, num_ev = mix.partition("/")
            if not depot_id or not num_cv or not num_ev:
                raise ValueError(
                    "--fleet-mix-override expects comma-joined "
                    "DEPOT_ID=NUM_CV/NUM_EV pairs"
                )
            ev_cap_override[depot_id] = (int(num_cv), int(num_ev))
    bundle, initial, _neutral_profit, context = _build_context(
        data_repo,
        args.instance_id,
        fleet_parameters=FLEET_PARAMETER_CLASSES[
            args.fleet_parameter_class
        ],
        depot_charging_scenario_name=args.depot_charging_scenario,
        ev_cap_override=ev_cap_override,
        tariff_calendar_authority=args.tariff_calendar_authority,
        ev_daily_premium_cny=args.ev_daily_premium,
        carbon_quota_kg=args.carbon_quota_kg,
    )
    if args.carbon_price != CHINA81_CARBON_PRICE_CNY_PER_KG:
        bundle = replace(
            bundle,
            prices=replace(bundle.prices, carbon_price=args.carbon_price),
            carbon_price_cny_per_kg=args.carbon_price,
        )
        context = replace(context, bundle=bundle)
    if args.public_station_power_kw is not None:
        bundle = _with_public_station_power(
            bundle,
            args.public_station_power_kw,
        )
        context = replace(context, bundle=bundle)
    if args.recharge_mode != "on_demand":
        set_active_recharge_mode(args.recharge_mode)
    if args.depot_curve == "linear":
        bundle = replace(
            bundle,
            prices=replace(
                bundle.prices,
                depot_charging_curve_id="L100_control",
                depot_charging_soc_breakpoints=(0.0, 1.0),
                depot_charging_relative_powers=(1.0,),
            ),
        )
        context = replace(context, bundle=bundle)
    enterprise_slice: EnterpriseProblemSlice | None = None
    if args.enterprise_id is not None:
        if context.rebuilt_route_constraints is None:
            raise ValueError(
                "enterprise slicing requires the sealed rebuilt route contract"
            )
        enterprise_slice = slice_enterprise_problem(
            bundle,
            context.rebuilt_route_constraints,
            args.enterprise_id,
        )
        bundle = enterprise_slice.bundle
        initial = register_all_vehicle_slots(
            DutyIndividual(
                duties=(),
                unserved_customers=enterprise_slice.customer_ids,
                source=f"native-init-reference/{enterprise_slice.source_id}",
            ),
            bundle,
        )
        neutral = {enterprise_slice.depot_id: 1.0}
        context = replace(
            context,
            bundle=bundle,
            independent_profit=neutral,
            prior_profit={enterprise_slice.depot_id: 0.0},
            rebuilt_route_constraints=enterprise_slice.route_constraints,
            fairness_enabled=False,
            theta=0.0,
        )
    if args.initial_solution is not None:
        initial = _load_registered_initial_solution(args.initial_solution.resolve(), bundle)
    if effective_first_trip_prev_night:
        context = replace(
            context,
            depot_charge_window_mode="full_gap",
        )
    dynamic_revealed_customer = None
    if args.dynamic_insertion_operator:
        initial, context, dynamic_revealed_customer = (
            _dynamic_insertion_technical_cut(
                bundle,
                initial,
                context,
            )
        )
    if not mechanism_enabled["multi_trip"]:
        initial = _single_trip_initial(initial)
    mechanism_reference = initial
    if not mechanism_enabled["cross_depot"]:
        reference_depot, _reference_type = _customer_structure(
            mechanism_reference
        )
        context = replace(
            context,
            customer_depot_lock=MappingProxyType(reference_depot),
        )
    if args.fleet_mix_override:
        # Fleet-composition experiment: the rung is a fixed fleet, not an upper
        # bound (user, 2026-09-03: "固定配比不是上限配比"); every configured
        # vehicle must be dispatched and the plan-wide fixed cost is a constant.
        context = replace(context, fleet_exact_composition=True)
    evaluator = DutyFullEvaluator(context)
    policy = _policy(
        evaluator,
        first_trip_prev_night_enabled=effective_first_trip_prev_night,
        charge_timing_policy=effective_charge_timing_policy,
        frvcpy_enabled=args.frvcpy_charging,
        first_trip_window=effective_first_trip_window,
        public_station_candidate_mode=args.public_station_candidate_mode,
    )
    dynamic_insertion_diagnostic = None
    if args.dynamic_insertion_operator:
        inserted = DynamicInsertionOperator(
            enabled=True,
        ).apply(
            initial,
            evaluator=evaluator,
            charging_policy=policy,
            newly_revealed_customer_ids=(dynamic_revealed_customer,),
        )
        initial = inserted.individual
        dynamic_insertion_diagnostic = asdict(inserted.accounting)
    depotsearch_c1_requested = args.instance_id in DEPOT_SEARCH_INSTANCE_IDS
    route_engine_options: dict[str, object] = {}
    if depotsearch_c1_requested:
        route_engine_options.update(
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
        )
    if not mechanism_enabled["cross_depot"]:
        route_engine_options["cross_depot_enabled"] = False
    if not mechanism_enabled["multi_trip"]:
        route_engine_options["multi_trip_enabled"] = False
    if not mechanism_enabled["type_exchange"]:
        route_engine_options["type_exchange_enabled"] = False
    route_engine_options["ev_charge_time_proxy_enabled"] = (
        not args.no_ev_charge_time_proxy
    )
    # 2026-09-05 (A2): price the shift-aware EV proxy at what THIS arm's
    # charge-timing policy will actually pay, so the route search of the
    # timing-off arm (effective policy "asap") and the full-mechanism arm
    # (cost_plus_carbon) no longer face an identical EV price.
    route_engine_options["charge_timing_policy_for_proxy"] = (
        effective_charge_timing_policy
    )
    # The route proxy must price the same first-trip window the exact repair
    # will settle in, otherwise the search optimises against a window that no
    # longer exists.
    route_engine_options["first_trip_window"] = effective_first_trip_window
    route_engine_options["proxy_feasible_slots_only"] = bool(args.proxy_feasible_slots)
    route_engine_options["ev_departure_gap_proxy_enabled"] = (
        args.ev_departure_gap_proxy
    )
    if args.ev_departure_gap_proxy and not any(
        trip.customer_ids for duty in initial.duties for trip in duty.trips
    ):
        # Fleet overrides that cannot seat the all-CV witness start from idle
        # slots; the departure gap then takes its trip energy from the
        # unconstrained witness so the proxy stays the same along the axis.
        witness_bundle, witness_initial, _, _ = _build_context(
            data_repo,
            args.instance_id,
            fleet_parameters=FLEET_PARAMETER_CLASSES[args.fleet_parameter_class],
            depot_charging_scenario_name=args.depot_charging_scenario,
            tariff_calendar_authority=args.tariff_calendar_authority,
            ev_daily_premium_cny=args.ev_daily_premium,
        )
        route_engine_options["ev_departure_gap_reference_kwh"] = (
            reference_trip_energy_kwh(
                witness_bundle.instance,
                witness_bundle.prices,
                witness_initial.duties,
            )
        )
    if args.ev_reload_gap_proxy and args.ev_departure_gap_proxy:
        raise ValueError(
            "--ev-reload-gap-proxy and --ev-departure-gap-proxy are exclusive"
        )
    route_engine_options["ev_reload_gap_proxy_enabled"] = args.ev_reload_gap_proxy
    route_engine_options["max_reloads_per_vehicle"] = max_reloads_per_vehicle
    route_engine_options["vehicle_type_dedup_enabled"] = (
        args.kernel_vehicle_type_dedup == "on"
    )
    # Fixed composition: the kernel must not be rewarded for parking a vehicle.
    route_engine_options["vehicle_fixed_cost_in_proxy"] = not args.fleet_mix_override
    if args.ev_reload_gap_proxy:
        # Fallback round-one reload gap = charging time of the *largest* trip
        # of the unconstrained witness (the same value on every composition
        # rung).  It is what the engine built here reserves, and it stays the
        # reservation only when the initial population turns out to carry no
        # between-trip charging session at all (the idle start) or when
        # ``--reload-gap-quantile`` is exactly 1.0.  Otherwise the engine is
        # rebuilt after initialization from the population's own sessions --
        # see the ``round-one reload gap`` block below the population build.
        # Later rounds feed back the exact best's own sessions at the same
        # quantile (``runner.py``).
        witness_bundle, witness_initial, _, _ = _build_context(
            data_repo,
            args.instance_id,
            fleet_parameters=FLEET_PARAMETER_CLASSES[args.fleet_parameter_class],
            depot_charging_scenario_name=args.depot_charging_scenario,
            tariff_calendar_authority=args.tariff_calendar_authority,
            ev_daily_premium_cny=args.ev_daily_premium,
        )
        route_engine_options["ev_reload_gap_reference_kwh"] = (
            reference_trip_energy_kwh(
                witness_bundle.instance,
                witness_bundle.prices,
                witness_initial.duties,
                reference="max",
            )
        )
    def make_route_engine(**extra):
        return IndependentKernelDutyRouteProposalEngine(
            evaluator.context,
            initial,
            stream_role="main_route",
            depot_assignment_operator_enabled=(
                effective_depot_assignment_operator
            ),
            **route_engine_options,
            **extra,
        )

    route_engine = make_route_engine()
    route_contract = evaluator.context.rebuilt_route_constraints
    if depotsearch_c1_requested and route_contract is None:
        raise RuntimeError(
            "DEPOTSEARCH C1 wiring requires a registered route contract"
        )
    route_engine_wiring = {
        "scope": "DEPOTSEARCH instance with explicit route-kernel options",
        "requested": {
            "rebuilt_volume_capacity_enabled": depotsearch_c1_requested,
            "rebuilt_shift_neighbours_only": depotsearch_c1_requested,
        },
        "effective": {
            "rebuilt_volume_capacity_enabled": bool(
                route_engine.rebuilt_volume_capacity_enabled
            ),
            "rebuilt_shift_neighbours_only": bool(
                route_engine.rebuilt_shift_neighbours_only
            ),
        },
        "route_engine_source_id": route_engine.source_id,
        # What the kernel model actually compiled to, after the vehicle-type /
        # profile dedup.  Recorded because the dedup is data-driven: the same
        # switch gives 4 types on this static batch and 20 under a dynamic cut.
        "kernel_vehicle_type_dedup_enabled": bool(
            route_engine.vehicle_type_dedup_enabled
        ),
        "kernel_num_vehicle_types": int(route_engine.data.num_vehicle_types),
        "kernel_num_profiles": int(route_engine.data.num_profiles),
        "kernel_num_vehicles": int(route_engine.data.num_vehicles),
        "ev_charge_time_proxy": route_engine.ev_charge_time_proxy,
        # 2026-09-05 (A2): the per-shift EV prices the route search actually
        # used, and the policy that picked them.  Metadata only -- without it
        # the shift-aware proxy cannot be reconciled from the artefacts.
        "first_trip_window": route_engine.first_trip_window,
        "charge_timing_policy_for_proxy": (
            route_engine.charge_timing_policy_for_proxy
        ),
        "shift_aware_ev_proxy": route_engine.shift_aware_ev_proxy,
        "proxy_feasible_slots_only": route_engine.proxy_feasible_slots_only,
        "route_contract": (
            None
            if route_contract is None
            else {
                "source_id": route_contract.source_id,
                "customer_shift_count": len(
                    route_contract.customer_shift_by_id
                ),
                "customer_volume_count": len(
                    route_contract.customer_volume_m3_by_id
                ),
                "shift_ids": sorted(
                    {
                        str(shift_id)
                        for shift_id in route_contract.customer_shift_by_id.values()
                    }
                ),
                "vehicle_volume_capacity_m3": float(
                    route_contract.vehicle_volume_capacity_m3
                ),
            }
        ),
    }
    if depotsearch_c1_requested:
        if route_engine_wiring["effective"] != route_engine_wiring["requested"]:
            raise RuntimeError(
                "DEPOTSEARCH C1 requested/effective switch mismatch"
            )
        assert route_contract is not None
        if set(route_contract.customer_shift_by_id) != set(
            route_contract.customer_volume_m3_by_id
        ):
            raise RuntimeError(
                "DEPOTSEARCH C1 route contract shift/volume customer coverage mismatch"
            )
    initialization_started = perf_counter()
    initialization_full_calls_before = evaluator.full_calls
    # A fleet override that cannot seat the all-CV witness starts from idle
    # slots with every customer unserved; that plan is not a reference
    # candidate and its infeasibility is not a run failure.
    reference_candidate_included = (
        enterprise_slice is None and not initial.unserved_customers
    )
    if args.population_mode == "technical_two_parent":
        (
            candidates,
            initial_evaluation,
            initial_evaluations,
        ) = _prepare_population(
            initial,
            evaluator,
            policy,
            mechanism_enabled=(
                mechanism_enabled if mechanism_off else None
            ),
        )
        initialization_summary = {
            "requested_size": 4,
            "actual_size": len(candidates),
            "attempts_exhausted": False,
        }
    elif args.search_mode == "kernel_native" and initial.unserved_customers:
        # Idle start (a written-down fleet the witness cannot seat): the
        # kernel-native search seeds its own population, so no native
        # construction here.  Rejection-sampling charge-repairable random
        # draws needed 24,244 draws / 492 s on a six-vehicle fleet
        # (2026-09-03), and the exact evaluator cannot score time-infeasible
        # skeletons at all; the idle reference only anchors the registry.
        # Four copies: the self-adaptive exact penalty manager wants four
        # initial evaluations; the runner dedupes seeds by fingerprint.
        candidates = (initial,) * 4
        initial_evaluation = evaluator.evaluate(initial)
        initial_evaluations = (initial_evaluation,) * 4
        initialization_summary = {
            "requested_size": 4,
            "actual_size": 4,
            "attempts_exhausted": False,
            "reference_candidate_included": reference_candidate_included,
            "mode": "idle_reference_only",
        }
    else:
        built = build_initial_population(
            initial,
            evaluator=evaluator,
            charging_policy=policy,
            route_engine=route_engine,
            requested_size=parameters.population.min_pop_size,
            max_random_attempts=None,
            initialization_method=(
                args.enterprise_init_constructor
                if enterprise_slice is not None
                else "random"
            ),
            include_reference_candidate=reference_candidate_included,
            require_complete_feasible=False,
            stop_requested=lambda: False,
            # 2026-08-30: default initialization is the reference candidate
            # plus native random construction (the witness-perturbation path
            # filled every slot with one-step neighbours of one solution,
            # evidence: solver/reports/design_debate_20260821 A.6).  The
            # --init-witness flag restores the witness path for paired
            # comparison runs.
            witness_seed=(
                initial
                if (
                    args.init_witness
                    and args.instance_id in DEPOT_SEARCH_INSTANCE_IDS
                    and enterprise_slice is None
                    and not initial.unserved_customers
                )
                else None
            ),
            mechanism_enabled=(
                None if enterprise_slice is not None else mechanism_enabled
            ),
        )
        if built.actual_size < 4:
            raise RuntimeError(
                "HALT_B_NATIVE_MATERIALIZATION: fewer than four native "
                f"{args.enterprise_init_constructor} solutions were retained "
                "before population entry"
            )
        else:
            candidates = built.candidates
            initial_evaluations = built.evaluations
        initial_evaluation = built.evaluations[0]
        initialization_summary = {
            "requested_size": built.requested_size,
            "actual_size": len(candidates),
            "attempts_exhausted": built.attempts_exhausted,
            "reference_candidate_included": reference_candidate_included,
            "attempts": len(built.attempts),
        }
    initialization_wall_seconds = perf_counter() - initialization_started
    initialization_full_evaluations = (
        evaluator.full_calls - initialization_full_calls_before
    )
    # Round-one reload gap, take two (2026-09-05, task A).  Until today round
    # one converted the *largest trip energy* of the unconstrained witness and
    # booked 2031.67 s on the P=0.2 midday-valley batch, where the batch's 101
    # real between-trip sessions have a 1348 s median: an over-reservation of
    # 51% on every EV return to depot, in a term that costs nothing in the
    # kernel objective (``unit_duration_cost`` is 0) and only decides
    # feasibility, so it prices EV-dense structures out of
    # ``GeneticAlgorithm._best`` without buying any search direction
    # (docs/handoff/second_root_cause_reload_gap_20260905.md section 3).
    # The initial population is 25 plans that have already been charge-
    # repaired and exactly evaluated, so their own between-trip sessions are
    # available here -- 38 to 66 of them, against the witness's 16 trip
    # energies -- and the same order statistic later rounds use now has a
    # distribution fine enough to land in the admissible window.  The engine
    # is rebuilt because the population could not exist before the engine
    # that constructed it.
    reload_gap_round1_seconds: float | None = None
    reload_gap_round1_source = "witness_max"
    if args.ev_reload_gap_proxy and args.proxy_estimate_source == "reference":
        # 2026-09-08：全批共用常数，不看本跑的初始种群。见
        # PROXY_REFERENCE_RELOAD_GAP_SECONDS 的推导与"不缩小可行域"的证明。
        reload_gap_round1_seconds = float(PROXY_REFERENCE_RELOAD_GAP_SECONDS)
        reload_gap_round1_source = "shared_constant_p50_of_40_runs"
        route_engine = make_route_engine(
            ev_reload_gap_seconds=reload_gap_round1_seconds
        )
        route_engine_wiring["route_engine_source_id"] = route_engine.source_id
        route_engine_wiring["ev_charge_time_proxy"] = (
            route_engine.ev_charge_time_proxy
        )
    elif args.ev_reload_gap_proxy and float(args.reload_gap_quantile) < 1.0:
        # Exactly 1.0 keeps the pre-2026-09-05 round one bit for bit; see the
        # --reload-gap-quantile help text.
        measured_round1 = population_inter_trip_reload_seconds(
            candidates, quantile=float(args.reload_gap_quantile)
        )
        if measured_round1 is not None:
            reload_gap_round1_seconds = float(measured_round1)
            reload_gap_round1_source = (
                f"population_sessions_p{round(float(args.reload_gap_quantile) * 100)}"
                f"_floor{RELOAD_GAP_FLOOR_SECONDS:g}"
            )
            route_engine = make_route_engine(
                ev_reload_gap_seconds=reload_gap_round1_seconds
            )
            route_engine_wiring["route_engine_source_id"] = route_engine.source_id
            route_engine_wiring["ev_charge_time_proxy"] = (
                route_engine.ev_charge_time_proxy
            )
    # Round-one first-trip window opening (2026-09-06).  The shift-aware EV
    # route proxy prices the FIRST shift's causal charging window, which under
    # ``prev_return`` opens at the vehicle's own return the preceding evening.
    # No route exists when the proxy is built, so round one used the
    # contract's last shift end (19:00) -- and the exact settlement then
    # actually charged at 15:30-16:30, where this calendar is far cleaner and
    # cheaper, so the proxy told the route search that evening charging was
    # expensive while the settlement found it cheap (measured on the
    # 2026-09-06 projection: proxy 1.243 vs exact ~0.873 CNY/kWh at carbon
    # price 0.2).  The initial population has been exactly evaluated, so its
    # certificates carry every trip's return instant; the median of the
    # duties' last returns is the route-independent anchor.  Computed for
    # every ``prev_return`` run -- it is NOT tied to the reload-gap proxy.
    first_trip_window_open_second: float | None = None
    first_trip_window_open_source = "last_shift_end_fallback"
    if not route_engine.shift_aware_ev_unit_cost_enabled:
        # The opening is read by the shift-aware proxy's first window and by
        # nothing else, so without that proxy there is nothing to rebuild.
        first_trip_window_open_source = "not_applicable_no_shift_aware_proxy"
    elif effective_first_trip_window == FIRST_TRIP_WINDOW_PREV_RETURN:
        if args.proxy_estimate_source == "reference":
            # 2026-09-08：全批共用常数，不看本跑的初始种群。
            measured_open: float | None = float(
                PROXY_REFERENCE_FIRST_TRIP_WINDOW_OPEN_SECOND
            )
            measured_open_source = "shared_constant_p50_of_40_runs"
        else:
            measured_open = population_first_trip_window_open_second(
                initial_evaluations
            )
            measured_open_source = "population_last_returns_p50"
        if measured_open is not None:
            first_trip_window_open_second = float(measured_open)
            first_trip_window_open_source = measured_open_source
            route_engine = make_route_engine(
                first_trip_window_open_second=first_trip_window_open_second,
                **(
                    {}
                    if reload_gap_round1_seconds is None
                    else {"ev_reload_gap_seconds": reload_gap_round1_seconds}
                ),
            )
            route_engine_wiring["route_engine_source_id"] = (
                route_engine.source_id
            )
            route_engine_wiring["ev_charge_time_proxy"] = (
                route_engine.ev_charge_time_proxy
            )
            route_engine_wiring["shift_aware_ev_proxy"] = (
                route_engine.shift_aware_ev_proxy
            )
    # 2026-09-08：两个路线无关锚点是"每跑各估各的"还是"全批共用常数"，以及
    # 常数本身。冻结时这两个数在整次运算的每一轮、以及同一批的每一次运算之间
    # 都逐位相同——这正是本批要检的那一条。
    route_engine_wiring["proxy_estimate_source"] = str(
        args.proxy_estimate_source
    )
    route_engine_wiring["proxy_reference_constants"] = {
        "reload_gap_seconds": float(PROXY_REFERENCE_RELOAD_GAP_SECONDS),
        "first_trip_window_open_second": float(
            PROXY_REFERENCE_FIRST_TRIP_WINDOW_OPEN_SECOND
        ),
        "derivation": (
            "median of the same estimator over the 40 runs of the four "
            "charging-arrangement arms (2026-09-06 batches); NOT a statistic "
            "of the reference solution, which is all-fuel and has neither"
        ),
        "applied": args.proxy_estimate_source == "reference",
    }
    route_engine_wiring["first_trip_window_open_round1"] = {
        "second": (
            None
            if first_trip_window_open_second is None
            else float(first_trip_window_open_second)
        ),
        "source": first_trip_window_open_source,
        "quantile": float(FIRST_TRIP_WINDOW_OPEN_QUANTILE),
        "population_size": len(candidates),
        "first_trip_window": effective_first_trip_window,
    }
    route_engine_wiring["reload_gap_round1"] = {
        "seconds": (
            None
            if reload_gap_round1_seconds is None
            else float(reload_gap_round1_seconds)
        ),
        "source": reload_gap_round1_source,
        "floor_seconds": float(RELOAD_GAP_FLOOR_SECONDS),
        "quantile": float(args.reload_gap_quantile),
        "population_size": len(candidates),
    }
    convergence_path = (
        args.convergence_csv.resolve()
        if args.convergence_csv is not None
        else output / "convergence.csv"
    )
    convergence_path.parent.mkdir(parents=True, exist_ok=True)
    convergence_diagnostics_path = convergence_path.with_name(
        f"{convergence_path.stem}_diagnostics.csv"
    )
    convergence_handle = convergence_path.open(
        "x", encoding="utf-8", newline=""
    )
    convergence_diagnostics_handle = convergence_diagnostics_path.open(
        "x", encoding="utf-8", newline=""
    )
    convergence_fields = (
        "cycle",
        "wall_seconds",
        "full_evaluations",
        "has_feasible",
        "best_feasible_raw_cost",
    )
    diagnostics_fields = (
        "cycle",
        "wall_seconds",
        "full_evaluations",
        "current_solution_raw_cost",
        "current_solution_penalized_cost",
        "physical_feasible",
        "fairness_feasible",
        "violation_counts_json",
        "violation_magnitudes_json",
        "outer_repair_calls",
        "outer_refinement_calls",
    )
    convergence_writer = csv.DictWriter(
        convergence_handle,
        fieldnames=convergence_fields,
        lineterminator="\n",
    )
    convergence_diagnostics_writer = csv.DictWriter(
        convergence_diagnostics_handle,
        fieldnames=diagnostics_fields,
        lineterminator="\n",
    )
    convergence_writer.writeheader()
    convergence_diagnostics_writer.writeheader()
    convergence_handle.flush()
    convergence_diagnostics_handle.flush()
    last_logged_best: float | None = None
    last_diagnostic_cycle: int | None = None

    def stop_and_record(state) -> bool:
        nonlocal last_diagnostic_cycle, last_logged_best
        if state.best_feasible_raw_cost is not None and (
            last_logged_best is None
            or float(state.best_feasible_raw_cost) < last_logged_best
        ):
            last_logged_best = float(state.best_feasible_raw_cost)
            convergence_writer.writerow(
                {
                    "cycle": int(state.iterations),
                    "wall_seconds": f"{float(state.elapsed_seconds):.9f}",
                    "full_evaluations": evaluator.full_calls,
                    "has_feasible": True,
                    "best_feasible_raw_cost": f"{last_logged_best:.12f}",
                }
            )
            convergence_handle.flush()
        if last_diagnostic_cycle != int(state.iterations):
            last_diagnostic_cycle = int(state.iterations)
            convergence_diagnostics_writer.writerow(
                {
                    "cycle": int(state.iterations),
                    "wall_seconds": f"{float(state.elapsed_seconds):.9f}",
                    "full_evaluations": evaluator.full_calls,
                    "current_solution_raw_cost": (
                        state.current_solution_raw_cost
                    ),
                    "current_solution_penalized_cost": (
                        state.current_solution_penalized_cost
                    ),
                    "physical_feasible": state.physical_feasible,
                    "fairness_feasible": state.fairness_feasible,
                    "violation_counts_json": json.dumps(
                        dict(state.violation_counts), sort_keys=True
                    ),
                    "violation_magnitudes_json": json.dumps(
                        dict(state.violation_magnitudes), sort_keys=True
                    ),
                    "outer_repair_calls": state.outer_repair_calls,
                    "outer_refinement_calls": state.outer_refinement_calls,
                }
            )
            convergence_diagnostics_handle.flush()
        # 2026-09-05 注：kernel_native 路径下 runner 丢弃这个返回值——每轮的
        # 结束由内核自己的 NoImprovement 规则决定，外层循环靠轮次记账 break，
        # 从不看这里返回什么（accounting.outer_stop_callback_effective=False）。
        # 现在 state.iterations_without_improvement 已是真实值，因此这条判据在
        # 未改善圈数累计到 NO_IMPROVEMENT_LIMIT 的那一轮会返回 True，但仍然
        # 无人采纳。此处不改行为，只把这层落差写明。
        return (
            state.iterations_without_improvement
            >= NO_IMPROVEMENT_LIMIT
        )

    station_pruning_before_search = charging_repair_runtime_diagnostics()
    try:
        if args.search_mode == "kernel_native":
            result = run_kernel_native_problem_hgs(
                candidates,
                evaluator=evaluator,
                charging_policy=policy,
                parameters=parameters,
                stop=stop_and_record,
                arm=args.arm,
                route_engine=route_engine,
                route_engine_factory=make_route_engine,
                initial_evaluations=initial_evaluations,
                initialization_full_evaluation_count=(
                    initialization_full_evaluations
                ),
                initialization_wall_seconds=initialization_wall_seconds,
                charging_prescreen_enabled=charging_prescreen_enabled,
                cross_depot_enabled=mechanism_enabled["cross_depot"],
                multi_trip_enabled=mechanism_enabled["multi_trip"],
                type_exchange_enabled=mechanism_enabled["type_exchange"],
                include_mechanism_refinement=True,
                include_charging_candidates=(
                    args.include_charging_candidates
                    and mechanism_enabled["charge_timing"]
                ),
                confirming_round=args.confirming_round,
                confirming_round_patience_mode=(
                    args.confirming_round_patience_mode
                ),
                confirming_patience_floor=args.confirming_patience_floor,
                stop_after_nonimproving_rounds=(
                    args.stop_after_nonimproving_rounds
                ),
                max_outer_rounds=args.max_outer_rounds,
                reload_gap_quantile=args.reload_gap_quantile,
                round_one_starts=args.round_one_starts,
                # 2026-09-08：冻结只在 reference 下生效，population 下两个参数
                # 都传 None，轮循环因而逐位走改动前的老路。
                frozen_reload_gap_seconds=(
                    reload_gap_round1_seconds
                    if args.proxy_estimate_source == "reference"
                    else None
                ),
                frozen_first_trip_window_open_second=(
                    first_trip_window_open_second
                    if args.proxy_estimate_source == "reference"
                    else None
                ),
            )
        else:
            result = run_integrated_problem_hgs(
                candidates,
                evaluator=evaluator,
                charging_policy=policy,
                parameters=parameters,
                stop=stop_and_record,
                arm=args.arm,
                route_engine=route_engine,
                retain_trajectory=False,
                initial_evaluations=initial_evaluations,
                initialization_full_evaluation_count=(
                    initialization_full_evaluations
                ),
                initialization_wall_seconds=initialization_wall_seconds,
                charging_prescreen_enabled=charging_prescreen_enabled,
                cross_depot_enabled=mechanism_enabled["cross_depot"],
                multi_trip_enabled=mechanism_enabled["multi_trip"],
                type_exchange_enabled=mechanism_enabled["type_exchange"],
                include_mechanism_refinement=True,
                # 2026-08-31: the pre-built charging-schedule candidate channel
                # consumed 85% of all incremental evaluations for 1 accept in the
                # formal MTC sample (72,880 evaluated / 1 accepted; evidence:
                # ablation_formal_20260830/MTC-HGS/run_3 accounting).  The carbon
                # mechanism itself acts through the charge-timing policy, so the
                # channel is off in formal runs; --include-charging-candidates
                # restores it for dedicated studies.
                include_charging_candidates=(
                    args.include_charging_candidates
                    and mechanism_enabled["charge_timing"]
                ),
                lazy_exact_evaluation=args.lazy_exact,
                )
    finally:
        convergence_handle.close()
        convergence_diagnostics_handle.close()

    station_pruning_after_search = charging_repair_runtime_diagnostics()
    station_pruning_search = {
        name: (
            station_pruning_after_search["station_pruning"][name]
            - station_pruning_before_search["station_pruning"][name]
        )
        for name in station_pruning_after_search["station_pruning"]
    }
    # 充电修复的缓存命中与耗时一直在运行时统计，却从未写进产物，
    # 导致"每圈时间花在哪"只能靠猜（2026-09-02 查表8 时发现）。
    # 这里把同一份诊断里的扁平计数与秒数一并做差后落盘；纯遥测，不改搜索行为。
    charging_repair_cost = {
        name: (
            station_pruning_after_search[name]
            - station_pruning_before_search[name]
        )
        for name, value in station_pruning_after_search.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }

    terminal_wall_seconds = (
        result.accounting.initialization_wall_seconds
        + result.accounting.run_wall_seconds
    )
    with convergence_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=convergence_fields,
            lineterminator="\n",
        )
        writer.writerow(
            {
                "cycle": int(result.iterations),
                "wall_seconds": f"{terminal_wall_seconds:.9f}",
                "full_evaluations": evaluator.full_calls,
                "has_feasible": bool(result.best_evaluation.feasible),
                "best_feasible_raw_cost": (
                    f"{float(result.best_evaluation.total_cost):.12f}"
                    if result.best_evaluation.feasible
                    else ""
                ),
            }
        )
        handle.flush()
    terminal_violation_counts = Counter(
        item.type for item in result.best_evaluation.violations
    )
    terminal_violation_magnitudes: Counter[str] = Counter()
    for magnitude, axis in zip(
        result.best_evaluation.violation_magnitudes,
        result.best_evaluation.violation_axes,
        strict=True,
    ):
        terminal_violation_magnitudes[axis] += float(magnitude)
    with convergence_diagnostics_path.open(
        "a", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=diagnostics_fields,
            lineterminator="\n",
        )
        writer.writerow(
            {
                "cycle": int(result.iterations),
                "wall_seconds": f"{terminal_wall_seconds:.9f}",
                "full_evaluations": evaluator.full_calls,
                "current_solution_raw_cost": float(
                    result.best_evaluation.total_cost
                ),
                "current_solution_penalized_cost": float(
                    result.accounting.penalty_manager.cost(
                        result.best_evaluation
                    )
                ),
                "physical_feasible": result.best_evaluation.feasible,
                "fairness_feasible": True,
                "violation_counts_json": json.dumps(
                    dict(sorted(terminal_violation_counts.items())),
                    sort_keys=True,
                ),
                "violation_magnitudes_json": json.dumps(
                    dict(sorted(terminal_violation_magnitudes.items())),
                    sort_keys=True,
                ),
                "outer_repair_calls": int(
                    result.accounting.repair_calls
                ),
                "outer_refinement_calls": int(
                    result.accounting.outer_refinement_calls
                ),
            }
        )
        handle.flush()
    customer_nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    if args.dynamic_insertion_operator:
        served = {
            node_id
            for route in result.best_evaluation.prepared_solution.routes
            for node_id in route.node_sequence[1:-1]
            if node_id in customer_nodes
        }
    else:
        served = {
            customer
            for duty in result.best.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
    served_demand = sum(float(customer_nodes[item].demand) for item in served)
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    charging_actions = tuple(
        result.best_evaluation.prepared_solution.charging_actions
    )
    ev_observation = {
        "ev_customers": sum(
            len(trip.customer_ids)
            for duty in result.best.duties
            if duty.vehicle_type == "ev"
            for trip in duty.trips
        ),
        "used_ev_duties": sum(
            1
            for duty in result.best.duties
            if duty.vehicle_type == "ev" and duty.trips
        ),
        "charging_actions": len(charging_actions),
        "charging_energy_kwh": sum(
            float(action.energy_kwh) for action in charging_actions
        ),
        "electricity_kwh": float(
            result.best_evaluation.breakdown.get("electricity_kwh", 0.0)
        ),
        "depot_charging_kwh": float(
            result.best_evaluation.breakdown.get("depot_charging_kwh", 0.0)
        ),
        "station_charging_kwh": float(
            result.best_evaluation.breakdown.get("station_charging_kwh", 0.0)
        ),
        "ev_drive_kwh": float(
            result.best_evaluation.breakdown.get("ev_drive_kwh", 0.0)
        ),
    }
    enterprise_ledger = build_enterprise_ledger(
        instance_id=args.instance_id,
        solution=result.best_evaluation.prepared_solution,
        bundle=bundle,
        prior_profit=evaluator.context.prior_profit,
        carbon_quota_kg=evaluator.context.carbon_quota_kg,
        expected_total_cost=result.best_evaluation.total_cost,
    )
    enterprise_ledger_path = output / "enterprise_ledger.json"
    _json(enterprise_ledger_path, enterprise_ledger)
    closure_violations = _mechanism_closure_violations(
        mechanism_reference,
        result.best,
        mechanism_enabled,
    )
    forbidden_channels_by_mechanism = {
        "cross_depot": ("depot_collaboration", "fairness_cross_depot"),
        "multi_trip": ("multi_trip",),
        "type_exchange": ("whole_duty_type_exchange",),
        "charge_timing": ("time_varying_carbon_charge",),
    }
    forbidden_proposed_actions = {
        mechanism: {
            channel: int(result.accounting.proposed_actions.get(channel, 0))
            for channel in forbidden_channels_by_mechanism[mechanism]
        }
        for mechanism in sorted(mechanism_off)
    }
    forbidden_proposed_nonzero = {
        mechanism: counts
        for mechanism, counts in forbidden_proposed_actions.items()
        if any(counts.values())
    }
    failure_reasons = []
    enterprise_expectation = (
        None
        if enterprise_slice is None
        else ENTERPRISE_NATIVE_EXPECTATIONS.get(
            enterprise_slice.enterprise_id
        )
    )
    enterprise_customer_scope_ok = True
    enterprise_demand_scope_ok = True
    if enterprise_expectation is not None:
        expected_customers, expected_demand = enterprise_expectation
        enterprise_customer_scope_ok = len(customer_nodes) == expected_customers
        enterprise_demand_scope_ok = total_demand == expected_demand
        if not enterprise_customer_scope_ok:
            failure_reasons.append(
                "enterprise slice customer total differs from the registered contract"
            )
        if not enterprise_demand_scope_ok:
            failure_reasons.append(
                "enterprise slice demand total differs from the registered contract"
            )
    if reference_candidate_included and not initial_evaluation.feasible:
        failure_reasons.append("initial solution is infeasible")
    expected_termination_statuses = {"STOPPED_BY_CALLER"}
    if result.termination_status not in expected_termination_statuses:
        failure_reasons.append(f"unexpected termination: {result.termination_status}")
    if not result.best_evaluation.feasible:
        failure_reasons.append("best solution is infeasible")
    if served != set(customer_nodes):
        failure_reasons.append("not all customers are served")
    if closure_violations:
        failure_reasons.append(
            "disabled mechanism structural closure failed: "
            + "; ".join(closure_violations)
        )
    if forbidden_proposed_nonzero:
        failure_reasons.append(
            "disabled mechanism emitted named actions: "
            + repr(forbidden_proposed_nonzero)
        )
    if (
        not mechanism_enabled["charge_timing"]
        and policy.charge_timing_policy != "asap"
    ):
        failure_reasons.append("disabled charge timing did not force asap")
    acceptance = assess_run(
        termination_ok=result.termination_status in expected_termination_statuses,
        feasible_ok=bool(
            result.best_evaluation.feasible
            and (not reference_candidate_included or initial_evaluation.feasible)
        ),
        customers_complete=(
            served == set(customer_nodes) and enterprise_customer_scope_ok
        ),
        demand_complete=(
            served_demand == total_demand and enterprise_demand_scope_ok
        ),
        extra_failure_reasons=failure_reasons,
        success_verdict=SUCCESS_VERDICT,
        failure_verdict=FAILURE_VERDICT,
    )
    failure_reasons = list(acceptance.failure_reasons)
    verdict = acceptance.verdict

    # 内核轮内改善轨迹与每轮小结（2026-09-05）：runner 负责记录，这里落盘。
    # 放在搜索结束之后写，是为了避免中途崩溃留下空文件。
    improvement_trace_path, kernel_rounds_path = _write_kernel_trace_csvs(
        output, result.accounting
    )

    metadata = {
        "status": "COMPLETE" if acceptance.accepted else "FAILED",
        "purpose": purpose,
        "instance_id": args.instance_id,
        "requested_initial_solution": (
            None
            if args.initial_solution is None
            else str(args.initial_solution.resolve())
        ),
        "enterprise_slice": (
            None
            if enterprise_slice is None
            else {
                "enterprise_id": enterprise_slice.enterprise_id,
                "depot_id": enterprise_slice.depot_id,
                "customer_count": len(enterprise_slice.customer_ids),
                "customer_ids": list(enterprise_slice.customer_ids),
                "source_id": enterprise_slice.source_id,
                "shared_public_station_ids": [
                    node.node_id
                    for node in enterprise_slice.bundle.instance.nodes
                    if node.node_type.lower() == "f"
                ],
            }
        ),
        "bundle_source_paths": dict(bundle.source_paths),
        "carbon_price_cny_per_kg": float(bundle.prices.carbon_price),
        "requested_ev_daily_premium_cny": args.ev_daily_premium,
        "effective_ev_daily_premium_cny": float(
            context.ev_daily_fixed_premium_cny
        ),
        "requested_carbon_quota_kg": args.carbon_quota_kg,
        # 生效值从评价上下文取，不从命令行回抄，这样落盘的是求解器真正用的那个数。
        "effective_carbon_quota_kg": float(context.carbon_quota_kg),
        "recharge_mode": args.recharge_mode,
        # 生效值从策略取，这样落盘的是修复层真正用的候选口径。
        "public_station_candidate_mode": policy.public_station_candidate_mode,
        # 2026-09-08 尝试性开关。命令行请求值与实际落到节点上的生效值分开落盘：
        # 生效值从 bundle 的公共站节点回读，不从命令行回抄，这样"这份产物到底
        # 是几千瓦跑的"有出处，不必回头翻命令行。None/60 kW = 算例自带口径。
        "public_station_power_kw": args.public_station_power_kw,
        "effective_public_station_power_kw": sorted(
            {
                float(node.charge_power_kw)
                for node in bundle.instance.nodes
                if node.node_type == "f" and node.charge_power_kw is not None
            }
        ),
        "depot_curve": args.depot_curve,
        "depot_charging_curve_id": bundle.prices.depot_charging_curve_id,
        "enterprise_init_constructor": args.enterprise_init_constructor,
        "iterations": result.iterations,
        # 2026-09-05：这行原本写死"20,000 圈无改善且不重启"，与实跑不符。
        # kernel_native 路径的真实规则是"每个外层轮内核跑 NoImprovement(patience)，
        # 外层再跑若干轮"，故由 parameters.stagnation_patience 与
        # result.accounting.rounds 拼出。非 kernel_native 路径不给 rounds 赋值
        # （恒为 0），所以那条分支不引用它。
        # 2026-09-05 二改：adaptive 模式下第 2 轮起的耐心值不再等于
        # stagnation_patience，故这句必须分模式写；每轮实际用的耐心值另见
        # accounting.round_patience_by_round，标定量见
        # accounting.round1_max_improvement_gap。
        "stop_semantics": (
            (
                f"round 1: NoImprovement({int(parameters.stagnation_patience)});"
                " confirming rounds: adaptive patience = max improvement gap"
                f" of round 1, floor {int(args.confirming_patience_floor)},"
                f" cap {int(parameters.stagnation_patience)}"
                f" x {int(result.accounting.rounds)} outer rounds"
                if args.confirming_round_patience_mode == "adaptive"
                else (
                    f"per-round NoImprovement("
                    f"{int(parameters.stagnation_patience)})"
                    f" x {int(result.accounting.rounds)} outer rounds"
                )
            )
            + (
                # 2026-09-05 三改：确认轮由"任一轮无改善即停"改为"连续 N 轮无
                # 改善才停"，并第一次给轮次循环加了硬上限。每轮有没有改善另见
                # accounting.round_improved_by_round。
                f"; stop after"
                f" {int(args.stop_after_nonimproving_rounds)} consecutive"
                " non-improving rounds, at most"
                f" {int(args.max_outer_rounds)} rounds"
                if args.confirming_round
                else ""
            )
            if args.search_mode == "kernel_native"
            else f"{int(parameters.stagnation_patience)} consecutive"
            " non-improving iterations; no restart"
        ),
        # runner 自报的停止语义；None＝该搜索路径没有记录。
        "stop_semantics_actual": result.accounting.stop_semantics_actual,
        "stagnation_patience": parameters.stagnation_patience,
        "education_depth_limit": parameters.education_depth_limit,
        "objective_mode": result.objective_mode,
        "convergence_csv": str(convergence_path),
        "convergence_diagnostics_csv": str(
            convergence_diagnostics_path
        ),
        "improvement_trace_csv": str(improvement_trace_path),
        "kernel_rounds_csv": str(kernel_rounds_path),
        "charging_prescreen": (
            result.charging_prescreen_accounting
            if result.charging_prescreen_accounting is not None
            else {"enabled": False}
        ),
        "charging_repair_cost": {
            "scope": "search_only",
            "completed_cycles": int(result.iterations),
            "totals": charging_repair_cost,
            "per_cycle": {
                name: (
                    float(value) / float(result.iterations)
                    if result.iterations
                    else None
                )
                for name, value in charging_repair_cost.items()
            },
        },
        "charging_station_pruning": {
            "scope": "search_only",
            "completed_cycles": int(result.iterations),
            "totals": station_pruning_search,
            "per_cycle": {
                name: (
                    float(value) / float(result.iterations)
                    if result.iterations
                    else None
                )
                for name, value in station_pruning_search.items()
            },
        },
        "frvcpy_route_clock_prescreen": {
            "frvcpy_enabled": bool(
                result.effective_execution.frvcpy_enabled
            ),
        },
        "best_evaluation_source": result.best_evaluation.source,
        "population_mode": args.population_mode,
        "effective_population": effective_population,
        "initial_population": initialization_summary,
        "initialization_wall_seconds": initialization_wall_seconds,
        "initialization_full_evaluations": initialization_full_evaluations,
        "accounting": result.accounting.to_dict(),
        "route_engine_wiring": route_engine_wiring,
        "ev_observation": ev_observation,
        "mechanism_off": sorted(mechanism_off),
        "mechanism_enabled": {
            **mechanism_enabled,
            "charge_timing": bool(
                result.effective_execution.include_charging_candidates
            ),
        },
        "mechanism_closure": {
            "violations": list(closure_violations),
            "forbidden_named_proposed_actions": forbidden_proposed_actions,
            "reference_max_trips_per_duty": max(
                (len(duty.trips) for duty in mechanism_reference.duties),
                default=0,
            ),
            "final_max_trips_per_duty": max(
                (len(duty.trips) for duty in result.best.duties),
                default=0,
            ),
            "effective_charge_timing_policy": (
                result.effective_execution.charge_timing_policy
            ),
        },
        "depot_assignment_operator": (
            route_engine.depot_assignment_statistics
        ),
        "dynamic_insertion_operator": {
            "enabled": bool(args.dynamic_insertion_operator),
            "revealed_customer_id": dynamic_revealed_customer,
            "trigger_second": (
                46_800.0 if args.dynamic_insertion_operator else None
            ),
            "accounting": dynamic_insertion_diagnostic,
        },
        "fleet_parameter_class": args.fleet_parameter_class,
        "fleet_parameter_class_id": bundle.fleet_parameter_class_id,
        "has_additional_total_fleet_cap": (
            bundle.has_additional_total_fleet_cap
        ),
        "fleet_caps_by_depot": {
            depot_id: dict(caps)
            for depot_id, caps in bundle.fleet_caps_by_depot.items()
        },
        "enterprise_ledger": {
            "schema": enterprise_ledger["schema"],
            "path": enterprise_ledger_path.name,
        },
    }
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "instance_id", "enterprise_id", "iterations",
            "termination_status",
            "initial_feasible", "initial_violations", "initial_cost",
            "best_feasible", "best_violations", "best_cost", "cost_delta",
            "customers_served", "customers_total", "demand_served",
            "demand_total", "crossover_calls",
            "full_evaluations",
            "best_evaluation_source", "run_wall_seconds",
            # 2026-09-02：表8 曾把九个"喂了已知解再跑"的验证跑当成搜索结果报进
            # Best/Avg/Gap。注入解此前只记在 metadata 深处，逐跑表里看不见，
            # 于是冷启动跑与热启动跑在同一张表里无法分辨。此列把它摆到明面上。
            "warm_started_from_solution",
            "verdict",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "instance_id": args.instance_id,
                "enterprise_id": (
                    None
                    if enterprise_slice is None
                    else enterprise_slice.enterprise_id
                ),
                "iterations": result.iterations,
                "termination_status": result.termination_status,
                "initial_feasible": initial_evaluation.feasible,
                "initial_violations": len(initial_evaluation.violations),
                "initial_cost": initial_evaluation.total_cost,
                "best_feasible": result.best_evaluation.feasible,
                "best_violations": len(result.best_evaluation.violations),
                "best_cost": result.best_evaluation.total_cost,
                "cost_delta": result.best_evaluation.total_cost - initial_evaluation.total_cost,
                "customers_served": len(served),
                "customers_total": len(customer_nodes),
                "demand_served": served_demand,
                "demand_total": total_demand,
                "crossover_calls": result.accounting.crossover_calls,
                "full_evaluations": result.accounting.full_evaluations,
                "best_evaluation_source": result.best_evaluation.source,
                "run_wall_seconds": result.accounting.run_wall_seconds,
                "warm_started_from_solution": (
                    "" if args.initial_solution is None
                    else str(args.initial_solution)
                ),
                "verdict": verdict,
            }
        )
    decision = {
        "verdict": verdict,
        "failure_reasons": failure_reasons,
    }
    _json(
        output / "best_solution.json",
        {
            "individual": asdict(result.best),
            "trip_clock": _trip_clock_rows(result.best_evaluation),
            "evaluation": {
                "total_cost": result.best_evaluation.total_cost,
                "breakdown": dict(result.best_evaluation.breakdown),
                "feasible": result.best_evaluation.feasible,
                "violations": [asdict(item) for item in result.best_evaluation.violations],
                "source": result.best_evaluation.source,
                "prepared_solution": solution_to_dict(
                    result.best_evaluation.prepared_solution
                ),
            },
            "accounting": result.accounting.to_dict(),
            "charging_prescreen": result.charging_prescreen_accounting,
        },
    )
    full_evaluation_result = _format_full_evaluation_result(
        feasible=result.best_evaluation.feasible,
        violation_count=len(result.best_evaluation.violations),
    )
    enterprise_report_ending = ""
    if enterprise_slice is not None:
        enterprise_report_ending = f"""
{enterprise_slice.enterprise_id} 最终服务 {len(served)}/{len(customer_nodes)} 个客户、{served_demand:.6f}/{total_demand:.6f} kg。
"""
    report = f"""# Problem-HGS 真实输入运行报告

## 结论

本轮判定：`{verdict}`。

真实输入 `{args.instance_id}` 完成了 {result.iterations} 个搜索循环，结束状态为 `{result.termination_status}`。最终服务 {len(served)}/{len(customer_nodes)} 个客户，完成需求量 {served_demand:.6f}/{total_demand:.6f}；{full_evaluation_result}。

初始成本为 {initial_evaluation.total_cost:.12f}，保存解成本为 {result.best_evaluation.total_cost:.12f}。
{enterprise_report_ending}
"""
    finalize_run_output(
        output,
        acceptance=acceptance,
        metadata=metadata,
        decision=decision,
        report_text=report,
    )
    print(json.dumps({"output": str(output), "verdict": verdict}, ensure_ascii=False))
    return result_exit_code(acceptance)


if __name__ == "__main__":
    requested_output = (
        None
        if len(sys.argv) < 2 or sys.argv[1].startswith("-")
        else Path(sys.argv[1]).resolve()
    )
    try:
        raise SystemExit(main())
    except Exception as exc:
        if requested_output is not None:
            _write_failure_package(requested_output, exc)
        raise
