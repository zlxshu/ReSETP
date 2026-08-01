#!/usr/bin/env python3
"""Reproduce and explain the two retained E7-O1 stage-18 failures."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for entry in (ROOT, ROOT / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import load_bundle
from baselines.china_e3_e7.e7_o1_replanning_20260801.policy import (
    FIXED_30_MINUTES,
    HYBRID_COUNT_20_PERCENT_OR_30_MINUTES,
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
from setp_solver.solution import Route, Solution


INSTANCE = "cn-prd-150c-01-V2-LOCATIONS"
SEED = 3
CUSTOMER = "C135"
TRIGGER = 57_600.0
POLICIES = (FIXED_30_MINUTES, HYBRID_COUNT_20_PERCENT_OR_30_MINUTES)
SOURCE_RESULT = HERE / "probe_three_sizes_seeds1to3_eval8_count_20260801"
DEFAULT_OUTPUT = HERE / "failure_diagnosis_20260801"
HASHED_FILES = ("metadata.json", "raw_runs.csv", "decision.json", "report.md")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def source_hashes() -> dict[str, str]:
    return {
        path.name: sha256(path)
        for path in sorted(SOURCE_RESULT.iterdir())
        if path.is_file() and not path.name.startswith("._")
    }


def batch_core(batch: Any) -> tuple[Any, ...]:
    return (
        int(batch.batch_index),
        float(batch.trigger_second),
        tuple(batch.event_ids),
        tuple(batch.customer_ids),
        float(batch.demand_kg),
    )


def route_clock(route: Route, instance: Any, prices: Any) -> tuple[float, float]:
    """Mirror the exact scheduler's preferred/latest-departure calculation."""

    nodes = {node.node_id: node for node in instance.nodes}
    origin = nodes[route.home_depot_id]
    speed = float(prices.v_speed_ms)
    elapsed = float(origin.service_time)
    preferred = [float(origin.ready_time) + float(origin.service_time)]
    for left, right in zip(route.node_sequence, route.node_sequence[1:]):
        _, travel, _ = instance.arc_metrics(left, right, route.vehicle_type, fallback_speed_mps=speed)
        elapsed += float(travel)
        preferred.append(float(nodes[right].ready_time) - elapsed)
        elapsed += float(nodes[right].service_time)
    latest = float(nodes[route.node_sequence[-1]].due_time)
    for index in range(len(route.node_sequence) - 2, -1, -1):
        node = nodes[route.node_sequence[index]]
        right = route.node_sequence[index + 1]
        _, travel, _ = instance.arc_metrics(
            route.node_sequence[index], right, route.vehicle_type, fallback_speed_mps=speed
        )
        latest = min(float(node.due_time), latest - float(node.service_time) - float(travel))
    latest += float(origin.service_time)
    return min(max(preferred), latest), latest


def replay() -> dict[str, Any]:
    bundle = load_bundle(INSTANCE)
    threshold = demand_threshold_kg(bundle.instance)
    stream = build_o1_stream(bundle.instance, instance_id=INSTANCE, stream_seed=SEED)
    batches = {
        policy: build_o1_batches(stream.events, policy, threshold_kg=threshold)
        for policy in POLICIES
    }
    captures: dict[str, tuple[Any, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    active = {"policy": ""}
    sources = {
        "bundle": SearchBundle(
            bundle_dir=SOURCE_RESULT,
            instance=bundle.instance,
            carbon_profile=list(bundle.time_profile),
        ),
        "prices": bundle.prices,
    }
    originals = (
        engine.build_qiu_scaled_stream,
        engine.build_trigger_batches,
        engine.pilot.INSTANCE_ID,
        engine.pilot._FULL_INSTANCE,
        probe.base.gate._instance_after_events,
        probe.base.apply_winner_action,
        probe.base.search_stage,
    )
    original_action, original_search = originals[5], originals[6]

    def compatible_action(solution: Solution, action: Any, context: Any, **kwargs: Any) -> Any:
        if kwargs.get("current_obj") is None:
            kwargs["current_obj"] = score_reference(solution, context)
        return original_action(solution, action, context, **kwargs)

    def capture_search(
        construction: Any,
        sources_: Mapping[str, Any],
        cut: Any,
        owners: dict[str, str],
        committed: set[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if abs(float(kwargs["trigger"]) - TRIGGER) < 1e-9:
            captures[active["policy"]] = (construction, cut)
        return original_search(construction, sources_, cut, owners, committed, **kwargs)

    try:
        engine.pilot.INSTANCE_ID = INSTANCE
        engine.pilot._FULL_INSTANCE = bundle.instance
        engine.build_qiu_scaled_stream = build_o1_stream
        engine.build_trigger_batches = lambda events, policy: build_o1_batches(
            events, policy, threshold_kg=threshold
        )
        probe.base.gate._instance_after_events = engine.pilot._exact_instance_after_events
        probe.base.apply_winner_action = compatible_action
        probe.base.search_stage = capture_search
        for policy in POLICIES:
            active["policy"] = policy
            summaries[policy], _, _ = engine._run_seed(bundle, sources, SEED, policy)
    finally:
        (
            engine.build_qiu_scaled_stream,
            engine.build_trigger_batches,
            engine.pilot.INSTANCE_ID,
            engine.pilot._FULL_INSTANCE,
            probe.base.gate._instance_after_events,
            probe.base.apply_winner_action,
            probe.base.search_stage,
        ) = originals
    if set(captures) != set(POLICIES):
        raise RuntimeError("stage 18 was not captured for both policies")
    return {"bundle": bundle, "stream": stream, "batches": batches, "captures": captures, "summaries": summaries}


def retained_rows() -> dict[str, dict[str, str]]:
    with (SOURCE_RESULT / "raw_runs.csv").open(encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return {
            row["policy"]: row
            for row in rows
            if row["instance_id"] == INSTANCE
            and int(row["stream_seed"]) == SEED
            and row["policy"] in POLICIES
        }


def evidence_rows(data: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    batches, summaries, captures = data["batches"], data["summaries"], data["captures"]
    cores = {policy: [batch_core(batch) for batch in batches[policy]] for policy in POLICIES}
    if len(cores[POLICIES[0]]) != 18 or cores[POLICIES[0]] != cores[POLICIES[1]]:
        raise RuntimeError("expected 18 operationally identical batches")
    retained = retained_rows()
    rows: list[dict[str, Any]] = []

    for policy in POLICIES:
        summary, source = summaries[policy], retained[policy]
        matching = all(
            str(summary[field]) == source[field]
            for field in ("status", "accepted_addition_count", "failure_stage", "failure_reason", "stream_sha256")
        )
        if not matching:
            raise RuntimeError(f"{policy} replay differs from the retained result")
        rows.append(
            {
                "record_type": "POLICY_REPLAY",
                "policy": policy,
                "status": summary["status"],
                "failure_stage": summary["failure_stage"],
                "accepted_addition_count": summary["accepted_addition_count"],
                "stage_evaluation_budget": engine.pilot.STAGE_EVALUATIONS,
                "failure_reason": summary["failure_reason"],
                "replay_matches_original": matching,
            }
        )
    for left, right in zip(batches[POLICIES[0]], batches[POLICIES[1]]):
        rows.append(
            {
                "record_type": "BATCH_PAIR",
                "batch_index": left.batch_index,
                "fixed_trigger_second": left.trigger_second,
                "count20_trigger_second": right.trigger_second,
                "fixed_trigger_cause": left.cause,
                "count20_trigger_cause": right.cause,
                "event_ids": "|".join(left.event_ids),
                "addition_count": len(left.customer_ids),
                "operationally_identical": batch_core(left) == batch_core(right),
            }
        )

    asset_payloads = {
        policy: {key: asdict(value) for key, value in sorted(captures[policy][1].asset_states.items())}
        for policy in POLICIES
    }
    if canonical_sha256(asset_payloads[POLICIES[0]]) != canonical_sha256(asset_payloads[POLICIES[1]]):
        raise RuntimeError("stage-18 asset maps differ")
    construction, cut = captures[POLICIES[0]]
    grouped: dict[tuple[str, str], list[Any]] = {}
    for state in cut.asset_states.values():
        grouped.setdefault((state.home_depot_id, state.vehicle_type), []).append(state)
    for (depot, vehicle_type), states in sorted(grouped.items()):
        available = sum(state.available_second <= TRIGGER + 1e-6 for state in states)
        rows.append(
            {
                "record_type": "ASSET_CLASS",
                "depot_id": depot,
                "vehicle_type": vehicle_type,
                "asset_total": len(states),
                "asset_available_at_trigger": available,
                "asset_future_release": len(states) - available,
                "asset_never_started": sum(state.next_trip_index == 1 for state in states),
            }
        )

    clock_rows = []
    for depot in sorted(data["bundle"].fleet_caps_by_depot):
        for vehicle_type in ("cv", "ev"):
            route = Route(f"CLOCK-{depot}-{vehicle_type}", vehicle_type, depot, [depot, CUSTOMER, depot])
            preferred, latest = route_clock(route, construction.effective_instance, data["bundle"].prices)
            row = {
                "record_type": "DEPOT_TYPE_CLOCK",
                "depot_id": depot,
                "vehicle_type": vehicle_type,
                "customer_id": CUSTOMER,
                "preferred_departure_second": preferred,
                "latest_departure_second": latest,
                "trigger_second": TRIGGER,
                "seconds_trigger_after_latest": TRIGGER - latest,
                "reachable_at_trigger": TRIGGER <= latest + 1e-6,
            }
            rows.append(row)
            clock_rows.append(row)

    event = next(event for event in data["stream"].events if event.customer_id == CUSTOMER)
    shenzhen = next(
        row for row in clock_rows if row["depot_id"] == "D_shenzhen" and row["vehicle_type"] == "cv"
    )
    for policy in POLICIES:
        batch = next(batch for batch in batches[policy] if CUSTOMER in batch.customer_ids)
        rows.append(
            {
                "record_type": "C135_TIMING",
                "policy": policy,
                "appearance_second": event.appearance_second,
                "ready_second": event.ready_second,
                "due_second": event.due_second,
                "service_second": event.service_second,
                "trigger_second": batch.trigger_second,
                "information_wait_seconds": batch.trigger_second - event.appearance_second,
                "shenzhen_cv_latest_departure_second": shenzhen["latest_departure_second"],
                "seconds_trigger_after_shenzhen_cv_latest": batch.trigger_second
                - float(shenzhen["latest_departure_second"]),
            }
        )
    return rows, {
        "batch_sha256": canonical_sha256(cores[POLICIES[0]]),
        "count_threshold": order_count_threshold(30, POLICIES[1]),
        "maximum_batch_size": max(len(batch.customer_ids) for batch in batches[POLICIES[1]]),
    }


def report(rows: Sequence[Mapping[str, Any]], facts: Mapping[str, Any]) -> str:
    assets = [row for row in rows if row["record_type"] == "ASSET_CLASS"]
    clocks = [row for row in rows if row["record_type"] == "DEPOT_TYPE_CLOCK"]
    timing = next(row for row in rows if row["record_type"] == "C135_TIMING")
    lines = [
        "# E7-O1 两个第18批失败的同档诊断",
        "",
        "## 结论",
        "",
        "两个失败不是缺车，也不是8次搜索预算不足。固定30分钟与累计20%或最多30分钟形成完全相同的18批；C135在57600秒才被处理，而深圳燃油车最迟必须在57332.433秒出发，已经晚267.567秒。",
        "",
        "该诊断不是正式实验结果。没有提高预算，没有改求解器、事件流或原O1结果。",
        "",
        "## 批次",
        "",
        f"20%规则需要累计{facts['count_threshold']}单才提前处理，实际任一批最多{facts['maximum_batch_size']}单，所以没有提前触发。两规则18批的时刻和订单逐批相同。",
        "",
        "## 第18批车队",
        "",
        "| 车场 | 车型 | 合法总数 | 当时可用 | 尚未返回 | 从未出车 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in assets:
        lines.append(
            f"| {row['depot_id']} | {row['vehicle_type']} | {row['asset_total']} | "
            f"{row['asset_available_at_trigger']} | {row['asset_future_release']} | {row['asset_never_started']} |"
        )
    lines += [
        f"| 合计 |  | {sum(int(row['asset_total']) for row in assets)} | "
        f"{sum(int(row['asset_available_at_trigger']) for row in assets)} | "
        f"{sum(int(row['asset_future_release']) for row in assets)} | "
        f"{sum(int(row['asset_never_started']) for row in assets)} |",
        "",
        "35辆合法车辆全部在状态表中，其中19辆已经释放，11辆尚未出车。",
        "",
        "## C135硬时间限制",
        "",
        f"C135在{float(timing['appearance_second']):.3f}秒出现，两个规则都在{float(timing['trigger_second']):.3f}秒处理，等待{float(timing['information_wait_seconds']):.3f}秒。",
        "",
        "| 车场 | 车型 | 最迟离场秒 | 触发时可达 | 晚了多少秒 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in clocks:
        lines.append(
            f"| {row['depot_id']} | {row['vehicle_type']} | {float(row['latest_departure_second']):.3f} | "
            f"{'是' if row['reachable_at_trigger'] else '否'} | {float(row['seconds_trigger_after_latest']):.3f} |"
        )
    lines += [
        "",
        "四个车场、两种车型在57600秒都无法满足C135的硬时间窗。增加搜索次数不能让时间倒退，所以提高当前8次预算不能挽救第18批。",
        "",
        "## 判定",
        "",
        "`HARD_CONSTRAINT_INFEASIBLE_AT_TRIGGER`。是否改变触发规则、允许途中改道或设置拒单出口，不属于本诊断。",
    ]
    return "\n".join(lines) + "\n"


def generate(output: Path) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite {output}")
    before = source_hashes()
    rows, facts = evidence_rows(replay())
    if source_hashes() != before:
        raise RuntimeError("retained O1 result changed during replay")
    assets = [row for row in rows if row["record_type"] == "ASSET_CLASS"]
    timing = next(row for row in rows if row["record_type"] == "C135_TIMING")
    totals = (
        sum(int(row["asset_total"]) for row in assets),
        sum(int(row["asset_available_at_trigger"]) for row in assets),
        sum(int(row["asset_never_started"]) for row in assets),
    )
    metadata = {
        "schema": "resetp.e7-o1-failure-diagnosis.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": INSTANCE,
        "stream_seed": SEED,
        "policies": list(POLICIES),
        "stage_evaluations": engine.pilot.STAGE_EVALUATIONS,
        "method": "same-eval8 replay plus exhaustive depot-type clock check",
        "formal_result": False,
        "original_result_directory": str(SOURCE_RESULT.relative_to(ROOT)),
        "original_result_files_sha256": before,
        "original_result_modified": False,
        "raw_row_count": len(rows),
        "batch_actual_sha256": facts["batch_sha256"],
        "script_sha256": sha256(Path(__file__)),
        "generation_command": "PYTHONPATH=solver/src:. build/python_envs/pyvrp-hgs-0.12.2/bin/python "
        "baselines/china_e3_e7/e7_o1_replanning_20260801/diagnose_fixed30_count20_failure.py",
        "check_command": "PYTHONPATH=solver/src:. build/python_envs/pyvrp-hgs-0.12.2/bin/python "
        "baselines/china_e3_e7/e7_o1_replanning_20260801/diagnose_fixed30_count20_failure.py --check",
    }
    decision = {
        "status": "PASS_E7_O1_FAILURE_DIAGNOSIS",
        "formal_result": False,
        "failure_classification": "HARD_CONSTRAINT_INFEASIBLE_AT_TRIGGER",
        "batch_sequences_identical": True,
        "batch_count_each_policy": 18,
        "full_fleet_present": totals[0] == 35,
        "asset_count": totals[0],
        "asset_available_at_trigger_count": totals[1],
        "asset_never_started_count": totals[2],
        "shenzhen_cv_latest_departure_second": timing["shenzhen_cv_latest_departure_second"],
        "trigger_second": timing["trigger_second"],
        "seconds_trigger_after_shenzhen_cv_latest": timing[
            "seconds_trigger_after_shenzhen_cv_latest"
        ],
        "higher_budget_run": False,
        "higher_budget_can_rescue_current_stage": False,
        "new_policy_proposed": False,
        "o2_started": False,
        "o3_started": False,
        "original_result_modified": False,
    }
    output.mkdir(parents=True)
    write_json(output / "metadata.json", metadata)
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(report(rows, facts), encoding="utf-8")
    write_json(output / "artifact_hashes.json", {name: sha256(output / name) for name in HASHED_FILES})


def check(output: Path) -> None:
    hashes = json.loads((output / "artifact_hashes.json").read_text())
    if set(hashes) != set(HASHED_FILES) or any(sha256(output / name) != digest for name, digest in hashes.items()):
        raise RuntimeError("artifact hashes do not close")
    metadata = json.loads((output / "metadata.json").read_text())
    decision = json.loads((output / "decision.json").read_text())
    with (output / "raw_runs.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if metadata["formal_result"] or decision["formal_result"] or len(rows) != metadata["raw_row_count"]:
        raise RuntimeError("metadata does not close")
    if metadata["original_result_files_sha256"] != source_hashes():
        raise RuntimeError("retained O1 source hashes changed")
    if metadata["script_sha256"] != sha256(Path(__file__)):
        raise RuntimeError("diagnostic script hash changed")
    batches = [row for row in rows if row["record_type"] == "BATCH_PAIR"]
    if len(batches) != 18 or any(row["operationally_identical"] != "True" for row in batches):
        raise RuntimeError("18-batch equality check failed")
    if any(row["fixed_trigger_second"] != row["count20_trigger_second"] for row in batches):
        raise RuntimeError("paired trigger clocks differ")
    assets = [row for row in rows if row["record_type"] == "ASSET_CLASS"]
    totals = (
        sum(int(row["asset_total"]) for row in assets),
        sum(int(row["asset_available_at_trigger"]) for row in assets),
        sum(int(row["asset_never_started"]) for row in assets),
    )
    if len(assets) != 8 or totals != (35, 19, 11):
        raise RuntimeError(f"asset arithmetic failed: {totals}")
    clocks = [row for row in rows if row["record_type"] == "DEPOT_TYPE_CLOCK"]
    if len(clocks) != 8 or any(row["reachable_at_trigger"] != "False" for row in clocks):
        raise RuntimeError("depot-type clock check failed")
    shenzhen = next(
        row for row in clocks if row["depot_id"] == "D_shenzhen" and row["vehicle_type"] == "cv"
    )
    latest, late = float(shenzhen["latest_departure_second"]), float(shenzhen["seconds_trigger_after_latest"])
    if abs(latest - 57_332.43306) > 1e-6 or abs(late - 267.56694) > 1e-6 or abs(late - (TRIGGER - latest)) > 1e-9:
        raise RuntimeError("C135 timing arithmetic failed")
    timings = [row for row in rows if row["record_type"] == "C135_TIMING"]
    if len(timings) != 2 or any(
        abs(float(row["trigger_second"]) - TRIGGER) > 1e-9
        or abs(float(row["shenzhen_cv_latest_departure_second"]) - latest) > 1e-9
        or abs(float(row["seconds_trigger_after_shenzhen_cv_latest"]) - late) > 1e-9
        for row in timings
    ):
        raise RuntimeError("policy-level C135 arithmetic failed")
    if decision["higher_budget_run"] or decision["higher_budget_can_rescue_current_stage"]:
        raise RuntimeError("budget diagnosis flags are wrong")
    print("PASS_E7_O1_FAILURE_DIAGNOSIS_CHECK")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    check(output) if args.check else generate(output)


if __name__ == "__main__":
    main()
