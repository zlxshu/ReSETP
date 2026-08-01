#!/usr/bin/env python3
"""Compare three trigger rules under Qiu-style accept-all semantics."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import statistics
import time
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import (
    load_bundle,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801 import (
    run_qiu_accept_all_diagnostic as q1,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    FIXED_30_MINUTES,
    HYBRID_500KG_OR_30_MINUTES,
    PER_ORDER,
)
from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as probe
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.evaluation import score_reference
from setp_solver.solution import Solution


POLICIES = (PER_ORDER, FIXED_30_MINUTES, HYBRID_500KG_OR_30_MINUTES)
PAIRINGS = (
    (PER_ORDER, FIXED_30_MINUTES),
    (HYBRID_500KG_OR_30_MINUTES, FIXED_30_MINUTES),
    (PER_ORDER, HYBRID_500KG_OR_30_MINUTES),
)
LABELS = {
    PER_ORDER: "逐单立即重排",
    FIXED_30_MINUTES: "固定30分钟",
    HYBRID_500KG_OR_30_MINUTES: "500kg或最多30分钟",
}
OUTPUT_NAME = "qiu_accept_all_three_triggers_50c_seeds1to10_eval8_comparison_20260801"


def _outcome(delta: float) -> str:
    if delta < -1.0e-9:
        return "win"
    if delta > 1.0e-9:
        return "loss"
    return "tie"


def _pct(left: float, right: float) -> float:
    return 100.0 * (left - right) / right if right else 0.0


def comparison_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return signed left-minus-right results only for a complete legal panel."""

    by_seed: dict[int, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        by_seed.setdefault(int(row["stream_seed"]), {})[str(row["policy"])] = row
    expected = set(POLICIES)
    if not by_seed or any(
        set(group) != expected
        or any(item["status"] != "PASS_ACCEPT_ALL" for item in group.values())
        for group in by_seed.values()
    ):
        return []

    result = []
    for seed, group in sorted(by_seed.items()):
        for left_policy, right_policy in PAIRINGS:
            left = group[left_policy]
            right = group[right_policy]
            left_cost = float(left["final_delivery_cost_cny"])
            right_cost = float(right["final_delivery_cost_cny"])
            cost_delta = left_cost - right_cost
            left_distance = float(left["distance_total_m"])
            right_distance = float(right["distance_total_m"])
            left_emissions = float(left["total_emissions_kg"])
            right_emissions = float(right["total_emissions_kg"])
            result.append(
                {
                    "stream_seed": seed,
                    "left_policy": left_policy,
                    "right_policy": right_policy,
                    "left_cost_cny": left_cost,
                    "right_cost_cny": right_cost,
                    "cost_delta_cny": cost_delta,
                    "cost_delta_pct": _pct(left_cost, right_cost),
                    "left_cost_outcome": _outcome(cost_delta),
                    "distance_delta_m": left_distance - right_distance,
                    "distance_delta_pct": _pct(left_distance, right_distance),
                    "vehicle_count_delta": int(left["actual_vehicle_count"])
                    - int(right["actual_vehicle_count"]),
                    "new_vehicle_count_delta": int(left["newly_used_vehicle_count"])
                    - int(right["newly_used_vehicle_count"]),
                    "trigger_count_delta": int(left["scheduled_trigger_count"])
                    - int(right["scheduled_trigger_count"]),
                    "actual_route_adjustment_count_delta": int(
                        left["actual_route_adjustment_count"]
                    )
                    - int(right["actual_route_adjustment_count"]),
                    "emissions_delta_kg": left_emissions - right_emissions,
                    "emissions_delta_pct": _pct(left_emissions, right_emissions),
                    "wall_seconds_delta": float(left["wall_seconds"])
                    - float(right["wall_seconds"]),
                }
            )
    return result


def _pair_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for left_policy, right_policy in PAIRINGS:
        pair = [
            row
            for row in rows
            if row["left_policy"] == left_policy
            and row["right_policy"] == right_policy
        ]
        if not pair:
            continue
        outcomes = [str(row["left_cost_outcome"]) for row in pair]
        summaries.append(
            {
                "left_policy": left_policy,
                "right_policy": right_policy,
                "seed_count": len(pair),
                "left_cost_wins": outcomes.count("win"),
                "cost_ties": outcomes.count("tie"),
                "left_cost_losses": outcomes.count("loss"),
                "mean_cost_delta_cny": statistics.fmean(
                    float(row["cost_delta_cny"]) for row in pair
                ),
                "mean_cost_delta_pct": statistics.fmean(
                    float(row["cost_delta_pct"]) for row in pair
                ),
                "mean_distance_delta_pct": statistics.fmean(
                    float(row["distance_delta_pct"]) for row in pair
                ),
                "mean_vehicle_count_delta": statistics.fmean(
                    float(row["vehicle_count_delta"]) for row in pair
                ),
                "mean_new_vehicle_count_delta": statistics.fmean(
                    float(row["new_vehicle_count_delta"]) for row in pair
                ),
                "mean_trigger_count_delta": statistics.fmean(
                    float(row["trigger_count_delta"]) for row in pair
                ),
                "mean_actual_route_adjustment_count_delta": statistics.fmean(
                    float(row["actual_route_adjustment_count_delta"]) for row in pair
                ),
                "mean_emissions_delta_pct": statistics.fmean(
                    float(row["emissions_delta_pct"]) for row in pair
                ),
                "mean_wall_seconds_delta": statistics.fmean(
                    float(row["wall_seconds_delta"]) for row in pair
                ),
            }
        )
    return summaries


def _report(
    rows: Sequence[Mapping[str, Any]],
    pair_summaries: Sequence[Mapping[str, Any]],
) -> str:
    passed = sum(row["status"] == "PASS_ACCEPT_ALL" for row in rows)
    lines = [
        "# E7 三种触发规则整批接收低成本比较",
        "",
        f"结果：{passed}/{len(rows)} 个“事件流×触发规则”单元合法完成。",
        "三种规则使用同一50客户算例、同一10个固定事件流和同一8次排障预算；",
        "每批新增订单全部接收，不经济拒单、不枚举子集、不顺延。",
        "",
        "完成率只计算动态新增订单；实际改路线次数使用Q1已封存的实体车辆与有序客户序列口径。",
        "成本是系统总配送成本，里程是总行驶里程，排放是油车直接排放与电车间接排放之和。",
        "",
        "| 触发规则 | 合法流 | 新单完成率 | 平均成本(元) | 平均里程(km) | 平均用车 | 平均新增车辆 | 平均触发/实际改路线 | 平均排放(kg) | 平均运行(s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for policy in POLICIES:
        group = [row for row in rows if row["policy"] == policy]
        legal = [row for row in group if row["status"] == "PASS_ACCEPT_ALL"]
        if not legal:
            lines.append(f"| {LABELS[policy]} | 0/{len(group)} | NA | NA | NA | NA | NA | NA | NA | NA |")
            continue
        mean = lambda key: statistics.fmean(float(row[key]) for row in legal)
        lines.append(
            f"| {LABELS[policy]} | {len(legal)}/{len(group)} | "
            f"{mean('dynamic_addition_completion_rate_pct'):.2f}% | "
            f"{mean('final_delivery_cost_cny'):.2f} | {mean('distance_total_m') / 1000.0:.2f} | "
            f"{mean('actual_vehicle_count'):.2f} | {mean('newly_used_vehicle_count'):.2f} | "
            f"{mean('scheduled_trigger_count'):.2f}/{mean('actual_route_adjustment_count'):.2f} | "
            f"{mean('total_emissions_kg'):.2f} | {mean('wall_seconds'):.3f} |"
        )
    lines.extend(
        [
            "",
            "配对表中的差值均为“左方案减右方案”；成本胜/平/负按每个固定事件流判定。",
            "",
            "| 左方案 vs 右方案 | 成本胜/平/负 | 平均成本差 | 平均里程差 | 平均用车差 | 平均触发差 | 平均实际改路线差 | 平均排放差 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    if pair_summaries:
        for row in pair_summaries:
            lines.append(
                f"| {LABELS[str(row['left_policy'])]} vs {LABELS[str(row['right_policy'])]} | "
                f"{row['left_cost_wins']}/{row['cost_ties']}/{row['left_cost_losses']} | "
                f"{float(row['mean_cost_delta_pct']):+.2f}% | "
                f"{float(row['mean_distance_delta_pct']):+.2f}% | "
                f"{float(row['mean_vehicle_count_delta']):+.2f} | "
                f"{float(row['mean_trigger_count_delta']):+.2f} | "
                f"{float(row['mean_actual_route_adjustment_count_delta']):+.2f} | "
                f"{float(row['mean_emissions_delta_pct']):+.2f}% |"
            )
    else:
        lines.append("| 未生成：至少一个比较单元不合法 | NA | NA | NA | NA | NA | NA | NA |")
    failures = [row for row in rows if row["status"] != "PASS_ACCEPT_ALL"]
    if failures:
        lines.extend(["", "失败原文："])
        for row in failures:
            lines.append(
                f"- seed {row['stream_seed']}，{LABELS[str(row['policy'])]}，"
                f"stage {row['failure_stage']}：{row['failure_reason']}"
            )
    lines.extend(
        [
            "",
            "这是低成本技术比较，不是正式实验。8次评价不是正式预算；",
            "本报告保留三种规则的全部结果，不选择正文主角。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(out: Path) -> None:
    if out.exists():
        raise RuntimeError(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    started = time.perf_counter()
    bundle = load_bundle(q1.pilot.INSTANCE_ID)
    q1.pilot._FULL_INSTANCE = bundle.instance
    sources = {
        "bundle": SearchBundle(
            bundle_dir=out,
            instance=bundle.instance,
            carbon_profile=list(bundle.time_profile),
        ),
        "prices": bundle.prices,
    }
    original_applier = probe.base.gate._instance_after_events
    original_action = probe.base.apply_winner_action

    def compatible_action(solution: Solution, action: Any, context: Any, **kwargs: Any) -> Any:
        if kwargs.get("current_obj") is None:
            kwargs["current_obj"] = score_reference(solution, context)
        return original_action(solution, action, context, **kwargs)

    summaries: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    try:
        probe.base.gate._instance_after_events = q1.pilot._exact_instance_after_events
        probe.base.apply_winner_action = compatible_action
        for stream_seed in q1.SEEDS:
            for policy in POLICIES:
                summary, stage_rows, event_rows = q1._run_seed(
                    bundle, sources, stream_seed, policy
                )
                summaries.append(summary)
                stages.extend(stage_rows)
                events.extend(event_rows)
    finally:
        probe.base.gate._instance_after_events = original_applier
        probe.base.apply_winner_action = original_action

    pairs = comparison_rows(summaries)
    pair_summaries = _pair_summary(pairs)
    all_legal = len(summaries) == len(q1.SEEDS) * len(POLICIES) and all(
        row["status"] == "PASS_ACCEPT_ALL" for row in summaries
    )
    verdict = (
        "PASS_E7_QIU_ACCEPT_ALL_THREE_TRIGGER_DIAGNOSTIC"
        if all_legal
        else "HALT_E7_QIU_ACCEPT_ALL_TRIGGER_FAILURES_RETAINED"
    )
    metadata = {
        "schema": "resetp.e7.qiu-accept-all-three-trigger-comparison.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": q1.pilot.INSTANCE_ID,
        "stream_seeds": list(q1.SEEDS),
        "policies": list(POLICIES),
        "admission_rule": "accept_every_addition_in_each_trigger_batch",
        "stage_evaluations": q1.pilot.STAGE_EVALUATIONS,
        "stage_budget_role": "diagnostic_only_not_formal",
        "completion_rate_definition": "accepted dynamic additions divided by 10; initial customers excluded",
        "actual_route_adjustment_definition": (
            "one per stage only when physical vehicle id plus ordered customer visits "
            "changes; depots, stations, and trip ids ignored"
        ),
        "metric_scopes": {
            "cost": "evaluate.total_cost",
            "distance": "evaluate.distance_total in metres",
            "emissions": "evaluate.E_total = CV direct plus EV indirect kilograms",
            "vehicle_count": "distinct physical vehicle ids in final execution plan",
            "runtime": "whole seed-policy cell wall seconds",
        },
        "comparison_delta_definition": "left policy minus right policy",
        "stream_sha256_by_seed": {
            str(row["stream_seed"]): row["stream_sha256"]
            for row in summaries
            if row["policy"] == HYBRID_500KG_OR_30_MINUTES
        },
        "source_sha256": {
            path.name: q1.pilot._sha256(path)
            for path in (
                Path(__file__),
                HERE / "run_qiu_accept_all_diagnostic.py",
                HERE / "dynamic_adapter.py",
                HERE / "trigger_policies.py",
            )
        },
        "wall_seconds": time.perf_counter() - started,
    }
    decision = {
        "verdict": verdict,
        "formal_result": False,
        "effect_comparison": True,
        "all_failures_retained": True,
        "same_event_stream_within_seed": True,
        "no_seed_or_parameter_change": True,
        "no_fleet_expansion": True,
        "no_subset_enumeration": True,
        "no_economic_rejection": True,
        "no_deferral": True,
        "full_information_static_reference_run": False,
        "all_cells_legal": all_legal,
        "paired_results_released": all_legal,
        "paper_lead_selected": False,
        "passed_cell_count": sum(
            row["status"] == "PASS_ACCEPT_ALL" for row in summaries
        ),
        "cell_count": len(summaries),
    }
    q1.pilot._write_json(out / "metadata.json", metadata)
    q1.pilot._write_csv(out / "raw_runs.csv", summaries)
    q1.pilot._write_csv(out / "stage_runs.csv", stages)
    q1.pilot._write_csv(out / "event_stream.csv", events)
    q1.pilot._write_csv(out / "paired_results.csv", pairs)
    q1.pilot._write_csv(out / "paired_summary.csv", pair_summaries)
    q1.pilot._write_json(out / "decision.json", decision)
    (out / "report.md").write_text(
        _report(summaries, pair_summaries), encoding="utf-8"
    )
    artifacts = {
        path.name: q1.pilot._sha256(path)
        for path in sorted(out.iterdir())
        if path.is_file()
        and not path.name.startswith("._")
        and path.name != "artifact_hashes.json"
    }
    q1.pilot._write_json(out / "artifact_hashes.json", artifacts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / OUTPUT_NAME)
    args = parser.parse_args()
    run(args.output.resolve())


if __name__ == "__main__":
    main()
