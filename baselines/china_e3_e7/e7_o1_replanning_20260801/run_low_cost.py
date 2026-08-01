#!/usr/bin/env python3
"""Run the approved low-cost O1 comparison on H0/G2 streams."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
import statistics
import time
from typing import Any, Mapping, Sequence

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import (
    load_bundle,
)
from baselines.china_e3_e7.e7_o1_replanning_20260801.policy import (
    COUNT_POLICIES,
    FIXED_30_MINUTES,
    HYBRID_COUNT_10_PERCENT_OR_30_MINUTES,
    HYBRID_COUNT_20_PERCENT_OR_30_MINUTES,
    HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES,
    MASS_POLICIES,
    PER_ORDER,
    POLICIES,
    build_o1_batches,
    build_o1_stream,
    demand_threshold_kg,
    order_count_threshold,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801 import (
    run_qiu_accept_all_diagnostic as engine,
)
from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as probe
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.evaluation import score_reference
from setp_solver.solution import Solution

HERE = Path(__file__).resolve().parent
INSTANCES = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
    "cn-prd-150c-01-V2-LOCATIONS",
)
DEFAULT_SEEDS = (1, 2, 3)
OUTPUT_NAME = "probe_three_sizes_seeds1to3_eval8_v2_20260801"
COUNT_OUTPUT_NAME = "probe_three_sizes_seeds1to3_eval8_count_20260801"
PAIRINGS = (
    (PER_ORDER, FIXED_30_MINUTES),
    (HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES, FIXED_30_MINUTES),
    (PER_ORDER, HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES),
)
COUNT_PAIRINGS = tuple(combinations(COUNT_POLICIES, 2))
LABELS = {
    PER_ORDER: "逐单立即重算",
    FIXED_30_MINUTES: "固定30分钟重算",
    HYBRID_TWO_MEAN_ORDERS_OR_30_MINUTES: "累计约两单或最多30分钟重算",
    HYBRID_COUNT_10_PERCENT_OR_30_MINUTES: "累计10%订单或最多30分钟重算",
    HYBRID_COUNT_20_PERCENT_OR_30_MINUTES: "累计20%订单或最多30分钟重算",
}


def run_configuration(
    policy_set: str,
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...], str]:
    if policy_set == "mass":
        return MASS_POLICIES, PAIRINGS, OUTPUT_NAME
    if policy_set == "count":
        return COUNT_POLICIES, COUNT_PAIRINGS, COUNT_OUTPUT_NAME
    raise ValueError(f"unknown policy set {policy_set!r}")


def _pct(left: float, right: float) -> float:
    return 100.0 * (left - right) / right if right else 0.0


def paired_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    policies: Sequence[str] = POLICIES,
    pairings: Sequence[tuple[str, str]] = PAIRINGS,
    retain_failures: bool = False,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        key = (str(row["instance_id"]), int(row["stream_seed"]))
        groups.setdefault(key, {})[str(row["policy"])] = row
    result: list[dict[str, Any]] = []
    for (instance_id, seed), group in sorted(groups.items()):
        if set(group) != set(policies):
            continue
        if not retain_failures and any(
            row["status"] != "PASS_ACCEPT_ALL" for row in group.values()
        ):
            continue
        for left_policy, right_policy in pairings:
            left = group[left_policy]
            right = group[right_policy]
            both_legal = all(
                row["status"] == "PASS_ACCEPT_ALL" for row in (left, right)
            )
            common = {
                "instance_id": instance_id,
                "stream_seed": seed,
                "left_policy": left_policy,
                "right_policy": right_policy,
            }
            if retain_failures:
                common.update(
                    {
                        "pair_status": (
                            "PASS_PAIRED"
                            if both_legal
                            else "NOT_COMPARABLE_FAILURE_RETAINED"
                        ),
                        "left_status": left["status"],
                        "right_status": right["status"],
                        "left_failure_reason": left.get("failure_reason", ""),
                        "right_failure_reason": right.get("failure_reason", ""),
                    }
                )
            if not both_legal:
                if retain_failures:
                    result.append(
                        {
                            **common,
                            "cost_delta_cny": None,
                            "cost_delta_pct": None,
                            "distance_delta_pct": None,
                            "emissions_delta_pct": None,
                            "vehicle_count_delta": None,
                            "route_adjustment_count_delta": None,
                            "trigger_count_delta": None,
                            "mean_information_wait_minutes_delta": None,
                        }
                    )
                continue
            result.append(
                {
                    **common,
                    "cost_delta_cny": float(left["final_delivery_cost_cny"])
                    - float(right["final_delivery_cost_cny"]),
                    "cost_delta_pct": _pct(
                        float(left["final_delivery_cost_cny"]),
                        float(right["final_delivery_cost_cny"]),
                    ),
                    "distance_delta_pct": _pct(
                        float(left["distance_total_m"]),
                        float(right["distance_total_m"]),
                    ),
                    "emissions_delta_pct": _pct(
                        float(left["total_emissions_kg"]),
                        float(right["total_emissions_kg"]),
                    ),
                    "vehicle_count_delta": int(left["actual_vehicle_count"])
                    - int(right["actual_vehicle_count"]),
                    "route_adjustment_count_delta": int(
                        left["actual_route_adjustment_count"]
                    )
                    - int(right["actual_route_adjustment_count"]),
                    "trigger_count_delta": int(left["scheduled_trigger_count"])
                    - int(right["scheduled_trigger_count"]),
                    "mean_information_wait_minutes_delta": float(
                        left["mean_information_wait_minutes"]
                    )
                    - float(right["mean_information_wait_minutes"]),
                }
            )
    return result


def _report(
    rows: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    *,
    policies: Sequence[str] = POLICIES,
    pairings: Sequence[tuple[str, str]] = PAIRINGS,
    policy_set: str = "mass",
) -> str:
    stream_description = (
        "订单采用 H0/G2 的06:00--22:00独立出现流；累计门槛等于各算例完整客户平均货量的两倍。"
        if policy_set == "mass"
        else "订单采用 H0/G2 的06:00--22:00独立出现流；累计订单数门槛采用 "
        "Ninikas & Minis（2020，第14页）的10%与20%作低成本O1试验；33%经零算力检查"
        "无法早于30分钟上限触发，本轮不运行。"
    )
    trigger_header = "数量/到时触发" if policy_set == "mass" else "门槛/到时触发"
    lines = [
        "# E7-O1 重算路线低成本试验",
        "",
        "本试验只比较何时重新计算剩余路线，不把触发解释为车辆立即发车。",
        stream_description,
        "每阶段8次完整评价只用于低成本探路，不是正式预算。",
        "",
        f"| 算例 | 规则 | 合法 | 平均成本(元) | 平均里程(km) | 平均用车 | 平均触发/实际改路线 | {trigger_header} | 平均等待(min) | 平均排放(kg) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for instance_id in INSTANCES:
        for policy in policies:
            group = [
                row
                for row in rows
                if row["instance_id"] == instance_id and row["policy"] == policy
            ]
            legal = [row for row in group if row["status"] == "PASS_ACCEPT_ALL"]
            if not legal:
                lines.append(f"| {instance_id} | {LABELS[policy]} | 0/{len(group)} | NA | NA | NA | NA | NA | NA | NA |")
                continue
            avg = lambda key: statistics.fmean(float(row[key]) for row in legal)
            threshold_key = (
                "demand_trigger_count"
                if policy_set == "mass"
                else "threshold_trigger_count"
            )
            lines.append(
                f"| {instance_id} | {LABELS[policy]} | {len(legal)}/{len(group)} | "
                f"{avg('final_delivery_cost_cny'):.2f} | {avg('distance_total_m') / 1000:.2f} | "
                f"{avg('actual_vehicle_count'):.2f} | {avg('scheduled_trigger_count'):.2f}/"
                f"{avg('actual_route_adjustment_count'):.2f} | {avg(threshold_key):.2f}/"
                f"{avg('time_trigger_count'):.2f} | {avg('mean_information_wait_minutes'):.2f} | "
                f"{avg('total_emissions_kg'):.2f} |"
            )
    lines.extend(
        [
            "",
            "配对差值均为左方案减右方案；全部逐行结果保存在CSV，不根据方向删行。",
            "",
            "| 算例 | 左方案 vs 右方案 | 平均成本差 | 平均里程差 | 平均用车差 | 平均实际改路线差 | 平均等待差 | 平均排放差 |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for instance_id in INSTANCES:
        for left, right in pairings:
            group = [
                row
                for row in pairs
                if row["instance_id"] == instance_id
                and row["left_policy"] == left
                and row["right_policy"] == right
                and row.get("pair_status", "PASS_PAIRED") == "PASS_PAIRED"
            ]
            if not group:
                continue
            avg = lambda key: statistics.fmean(float(row[key]) for row in group)
            lines.append(
                f"| {instance_id} | {LABELS[left]} vs {LABELS[right]} | "
                f"{avg('cost_delta_pct'):+.2f}% | {avg('distance_delta_pct'):+.2f}% | "
                f"{avg('vehicle_count_delta'):+.2f} | {avg('route_adjustment_count_delta'):+.2f} | "
                f"{avg('mean_information_wait_minutes_delta'):+.2f} | "
                f"{avg('emissions_delta_pct'):+.2f}% |"
            )
    if policy_set == "count":
        lines.extend(
            [
                "",
                "逐单元完整结果（失败单元不删除）：",
                "",
                "| 算例 | seed | 规则 | 状态 | 成本(元) | 里程(km) | 用车 | 实际改路线 | 平均等待(min) | 排放(kg) | 失败原文 |",
                "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        order = {policy: index for index, policy in enumerate(policies)}

        def shown(row: Mapping[str, Any], key: str, scale: float = 1.0) -> str:
            value = row.get(key)
            return "NA" if value in (None, "", "NA") else f"{float(value) / scale:.2f}"

        for row in sorted(
            rows,
            key=lambda item: (
                str(item["instance_id"]),
                int(item["stream_seed"]),
                order[str(item["policy"])],
            ),
        ):
            failure = (
                str(row.get("failure_reason") or "")
                .replace("|", "\\|")
                .replace("\n", " ")
            )
            lines.append(
                f"| {row['instance_id']} | {row['stream_seed']} | {LABELS[str(row['policy'])]} | "
                f"{row['status']} | {shown(row, 'final_delivery_cost_cny')} | "
                f"{shown(row, 'distance_total_m', 1000.0)} | {shown(row, 'actual_vehicle_count')} | "
                f"{shown(row, 'actual_route_adjustment_count')} | "
                f"{shown(row, 'mean_information_wait_minutes')} | "
                f"{shown(row, 'total_emissions_kg')} | {failure} |"
            )
    failures = [row for row in rows if row["status"] != "PASS_ACCEPT_ALL"]
    if failures:
        lines.extend(["", "未跑通单元的原始停止信息：", ""])
        for row in failures:
            lines.append(
                f"- {row['instance_id']}，seed {row['stream_seed']}，{LABELS[str(row['policy'])]}，"
                f"第{row['failure_stage']}次重算：{row['failure_reason']}"
            )
    lines.extend(
        [
            "",
            "本报告只交付完整低成本结果。是否形成论文效应、继续扩大O1或转入O2，依据全部结果另行判断。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(out: Path, seeds: Sequence[int], *, policy_set: str = "mass") -> None:
    policies, pairings, _ = run_configuration(policy_set)
    if not seeds:
        raise ValueError("at least one stream seed is required")
    if out.exists():
        raise RuntimeError(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    thresholds: dict[str, float] = {}
    count_thresholds: dict[str, dict[str, int]] = {}

    original_stream_builder = engine.build_qiu_scaled_stream
    original_batch_builder = engine.build_trigger_batches
    original_instance_id = engine.pilot.INSTANCE_ID
    original_full_instance = engine.pilot._FULL_INSTANCE
    original_applier = probe.base.gate._instance_after_events
    original_action = probe.base.apply_winner_action

    def compatible_action(
        solution: Solution, action: Any, context: Any, **kwargs: Any
    ) -> Any:
        if kwargs.get("current_obj") is None:
            kwargs["current_obj"] = score_reference(solution, context)
        return original_action(solution, action, context, **kwargs)

    try:
        probe.base.gate._instance_after_events = engine.pilot._exact_instance_after_events
        probe.base.apply_winner_action = compatible_action
        for instance_id in INSTANCES:
            bundle = load_bundle(instance_id)
            threshold = demand_threshold_kg(bundle.instance)
            thresholds[instance_id] = threshold
            if policy_set == "count":
                dynamic_order_count = len(
                    build_o1_stream(
                        bundle.instance,
                        instance_id=instance_id,
                        stream_seed=int(seeds[0]),
                    ).events
                )
                count_thresholds[instance_id] = {
                    policy: order_count_threshold(dynamic_order_count, policy)
                    for policy in (
                        HYBRID_COUNT_10_PERCENT_OR_30_MINUTES,
                        HYBRID_COUNT_20_PERCENT_OR_30_MINUTES,
                    )
                }
            engine.pilot.INSTANCE_ID = instance_id
            engine.pilot._FULL_INSTANCE = bundle.instance
            engine.build_qiu_scaled_stream = build_o1_stream
            engine.build_trigger_batches = (
                lambda stream_events, policy, threshold=threshold: build_o1_batches(
                    stream_events, policy, threshold_kg=threshold
                )
            )
            sources = {
                "bundle": SearchBundle(
                    bundle_dir=out,
                    instance=bundle.instance,
                    carbon_profile=list(bundle.time_profile),
                ),
                "prices": bundle.prices,
            }
            for seed in seeds:
                for policy in policies:
                    summary, stage_rows, event_rows = engine._run_seed(
                        bundle, sources, int(seed), policy
                    )
                    waits = [
                        (float(row["trigger_second"]) - float(row["t_appear"])) / 60.0
                        for row in event_rows
                    ]
                    summary.update(
                        {
                            "mean_information_wait_minutes": statistics.fmean(waits),
                            "max_information_wait_minutes": max(waits),
                            "demand_trigger_count": sum(
                                row["trigger_cause"] == "demand_threshold"
                                for row in stage_rows
                            ),
                            "time_trigger_count": sum(
                                row["trigger_cause"] in {"fixed_interval", "maximum_wait", "window_end"}
                                for row in stage_rows
                                if not str(row["status"]).startswith("NOT_ATTEMPTED")
                            ),
                        }
                    )
                    if policy_set == "count":
                        summary.update(
                            {
                                "order_count_trigger_count": sum(
                                    row["trigger_cause"] == "order_count_threshold"
                                    for row in stage_rows
                                ),
                                "threshold_trigger_count": sum(
                                    row["trigger_cause"]
                                    in {"demand_threshold", "order_count_threshold"}
                                    for row in stage_rows
                                ),
                            }
                        )
                    common = {
                        "instance_id": instance_id,
                        "demand_threshold_kg": (
                            threshold if policy_set == "mass" else None
                        ),
                    }
                    rows.append({**common, **summary})
                    stages.extend({**common, **row} for row in stage_rows)
                    events.extend({**common, **row} for row in event_rows)
    finally:
        engine.build_qiu_scaled_stream = original_stream_builder
        engine.build_trigger_batches = original_batch_builder
        engine.pilot.INSTANCE_ID = original_instance_id
        engine.pilot._FULL_INSTANCE = original_full_instance
        probe.base.gate._instance_after_events = original_applier
        probe.base.apply_winner_action = original_action

    pairs = paired_rows(
        rows,
        policies=policies,
        pairings=pairings,
        retain_failures=policy_set == "count",
    )
    expected = len(INSTANCES) * len(seeds) * len(policies)
    all_legal = len(rows) == expected and all(
        row["status"] == "PASS_ACCEPT_ALL" for row in rows
    )
    metadata = {
        "schema": (
            "resetp.e7-o1-low-cost.v1"
            if policy_set == "mass"
            else "resetp.e7-o1-low-cost.v2"
        ),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "instances": list(INSTANCES),
        "stream_seeds": [int(seed) for seed in seeds],
        "policies": list(policies),
        "horizon": "06:00--22:00",
        "dynamic_order_share": 0.20,
        "maximum_wait_minutes": 30,
        "stage_evaluations": engine.pilot.STAGE_EVALUATIONS,
        "stage_budget_role": "diagnostic_only_not_formal",
        "route_search_executed": True,
        "wall_seconds": time.perf_counter() - started,
        "source_sha256": {
            path.name: engine.pilot._sha256(path)
            for path in (
                Path(__file__),
                HERE / "policy.py",
                Path(engine.__file__),
            )
        },
    }
    if policy_set == "mass":
        metadata.update(
            {
                "threshold_formula": "2 * mean demand of all customers in the instance",
                "threshold_kg_by_instance": thresholds,
            }
        )
    else:
        metadata.update(
            {
                "policy_set": "count",
                "threshold_formula": "ceil(share * dynamic order count)",
                "threshold_order_count_by_instance": count_thresholds,
                "literature_basis": (
                    "Ninikas & Minis (2020), p.14: 10% and 20% are used only "
                    "as low-cost E7-O1 tests in this run"
                ),
                "excluded_33_percent": (
                    "zero-compute check found that 33% cannot trigger before the "
                    "30-minute maximum wait on the approved H0/G2 streams; not run"
                ),
            }
        )
    decision = {
        "status": (
            "PASS_E7_O1_LOW_COST_COMPLETE"
            if all_legal
            else "HALT_E7_O1_LOW_COST_FAILURES_RETAINED"
        ),
        "formal_result": False,
        "effect_review_pending": True,
        "all_cells_legal": all_legal,
        "passed_cell_count": sum(row["status"] == "PASS_ACCEPT_ALL" for row in rows),
        "cell_count": len(rows),
        "all_results_retained": True,
        "paper_lead_selected": False,
        "o2_started": False,
        "o3_started": False,
    }
    if policy_set == "count":
        decision["policy_set"] = "count"
        decision["research_effect_judged"] = False
    engine.pilot._write_json(out / "metadata.json", metadata)
    engine.pilot._write_csv(out / "raw_runs.csv", rows)
    engine.pilot._write_csv(out / "stage_runs.csv", stages)
    engine.pilot._write_csv(out / "event_stream.csv", events)
    engine.pilot._write_csv(out / "paired_results.csv", pairs)
    engine.pilot._write_json(out / "decision.json", decision)
    (out / "report.md").write_text(
        _report(
            rows,
            pairs,
            policies=policies,
            pairings=pairings,
            policy_set=policy_set,
        ),
        encoding="utf-8",
    )
    artifacts = {
        path.name: engine.pilot._sha256(path)
        for path in sorted(out.iterdir())
        if path.is_file()
        and not path.name.startswith("._")
        and path.name != "artifact_hashes.json"
    }
    engine.pilot._write_json(out / "artifact_hashes.json", artifacts)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy-set", choices=("mass", "count"), default="mass")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    _, _, output_name = run_configuration(args.policy_set)
    output = args.output or HERE / output_name
    run(output.resolve(), tuple(args.seeds), policy_set=args.policy_set)


if __name__ == "__main__":
    main()
