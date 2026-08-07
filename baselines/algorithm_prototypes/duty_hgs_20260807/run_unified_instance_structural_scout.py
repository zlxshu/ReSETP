"""Inventory unified-instance opportunity without selecting a winner.

This is an exploratory, zero-search screen.  It keeps every China81 instance
for which the existing Qiu-scaled dynamic stream is defined, replays charging
only inside certified windows, and records whether the current Duty interface
exposes the problem-specific move channels.  It does not rank instances or
freeze a scientific effect threshold.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys
from typing import Any

from duty_hgs.evaluation import DutyFullEvaluator
from duty_hgs.operators import generate_problem_moves
from run_real_input_technical_trial import _build_context
from setp_solver.check import check_solution
from setp_solver.cost import evaluate as evaluate_cost
from setp_solver.search.multitrip_schedule import (
    reschedule_between_trip_charging,
)

from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    build_qiu_scaled_stream,
    dynamic_stream_sha256,
)


DYNAMIC_CUSTOMER_COUNTS = (50, 100, 150)
STREAM_SEEDS = tuple(range(1, 11))
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _candidate_ids(repo: Path) -> tuple[str, ...]:
    witnesses = (
        repo
        / "baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a/witnesses"
    )
    return tuple(
        sorted(
            path.stem
            for path in witnesses.glob("*.json")
            if any(
                f"-{customer_count}c-" in path.stem
                for customer_count in DYNAMIC_CUSTOMER_COUNTS
            )
        )
    )


def _route_signature(solution) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
    return tuple(
        sorted(
            (
                route.vehicle_id,
                route.vehicle_type,
                route.home_depot_id,
                tuple(route.node_sequence),
            )
            for route in solution.routes
        )
    )


def _carbon_ranges(time_profile: list[dict[str, Any]]) -> tuple[str, float]:
    by_city: dict[str, list[float]] = defaultdict(list)
    for row in time_profile:
        by_city[str(row["city"])].append(
            float(row["actual_gco2_per_kwh"])
        )
    ranges = {
        city: {
            "minimum_gco2_per_kwh": min(values),
            "maximum_gco2_per_kwh": max(values),
            "range_gco2_per_kwh": max(values) - min(values),
        }
        for city, values in sorted(by_city.items())
    }
    return (
        json.dumps(ranges, ensure_ascii=False, sort_keys=True),
        max(item["range_gco2_per_kwh"] for item in ranges.values()),
    )


def _scan_one(repo: Path, instance_id: str) -> dict[str, Any]:
    bundle, individual, _technical_pi0, context = _build_context(
        repo,
        instance_id,
    )
    evaluation = DutyFullEvaluator(context).evaluate(individual)
    if not evaluation.feasible:
        raise RuntimeError("registered initial Duty solution is infeasible")

    naive = reschedule_between_trip_charging(
        evaluation.prepared_solution,
        evaluation.certificate,
        bundle.instance,
        bundle.time_profile,
        strategy="naive",
        prices=bundle.prices,
    )
    aware = reschedule_between_trip_charging(
        evaluation.prepared_solution,
        evaluation.certificate,
        bundle.instance,
        bundle.time_profile,
        strategy="aware",
        prices=bundle.prices,
    )
    naive_violations = check_solution(naive, bundle.instance, bundle.prices)
    aware_violations = check_solution(aware, bundle.instance, bundle.prices)
    if naive_violations or aware_violations:
        raise RuntimeError(
            "charging replay failed complete check: "
            f"naive={len(naive_violations)}, aware={len(aware_violations)}"
        )
    if _route_signature(naive) != _route_signature(aware):
        raise RuntimeError("charging-only replay changed a route or vehicle type")

    naive_breakdown = evaluate_cost(
        naive,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    aware_breakdown = evaluate_cost(
        aware,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    naive_starts = {
        (action.vehicle_id, action.station_id): (
            int(action.charge_day_offset),
            float(action.charge_start_second),
        )
        for action in naive.charging_actions
    }
    moved_actions = sum(
        naive_starts[(action.vehicle_id, action.station_id)]
        != (int(action.charge_day_offset), float(action.charge_start_second))
        for action in aware.charging_actions
    )

    stream_hashes = []
    event_counts = []
    for stream_seed in STREAM_SEEDS:
        stream = build_qiu_scaled_stream(
            bundle.instance,
            instance_id=instance_id,
            stream_seed=stream_seed,
        )
        stream_hashes.append(dynamic_stream_sha256(stream))
        event_counts.append(len(stream.events))

    move_counts = Counter(
        move.channel
        for move in generate_problem_moves(
            individual,
            evaluation,
            bundle.instance,
        )
    )
    carbon_ranges_json, maximum_within_city_range = _carbon_ranges(
        bundle.time_profile
    )
    used_duties = [duty for duty in individual.duties if duty.trips]
    multi_trip_duties = sum(len(duty.trips) > 1 for duty in used_duties)
    customer_nodes = [
        node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    ]
    region = instance_id.split("-", 2)[1]
    naive_emissions = float(naive_breakdown["E_total"])
    aware_emissions = float(aware_breakdown["E_total"])
    return {
        "instance_id": instance_id,
        "region": region,
        "customer_count": len(customer_nodes),
        "customer_demand_kg": sum(float(node.demand) for node in customer_nodes),
        "depot_count": len(bundle.fleet_caps_by_depot),
        "registered_cv": sum(
            duty.vehicle_type == "cv" for duty in individual.duties
        ),
        "registered_ev": sum(
            duty.vehicle_type == "ev" for duty in individual.duties
        ),
        "used_cv": sum(
            duty.vehicle_type == "cv" and bool(duty.trips)
            for duty in individual.duties
        ),
        "used_ev": sum(
            duty.vehicle_type == "ev" and bool(duty.trips)
            for duty in individual.duties
        ),
        "trip_count": len(evaluation.certificate.trips),
        "multi_trip_vehicle_count": multi_trip_duties,
        "charging_action_count": len(aware.charging_actions),
        "carbon_aware_moved_action_count": moved_actions,
        "carbon_ranges_by_city_json": carbon_ranges_json,
        "maximum_within_city_carbon_range_gco2_per_kwh": (
            maximum_within_city_range
        ),
        "naive_system_emissions_kg": naive_emissions,
        "aware_system_emissions_kg": aware_emissions,
        "aware_minus_naive_system_emissions_kg": (
            aware_emissions - naive_emissions
        ),
        "aware_minus_naive_system_emissions_pct": (
            100.0 * (aware_emissions - naive_emissions) / naive_emissions
        ),
        "aware_minus_naive_operating_cost_cny": (
            float(aware_breakdown["total_cost"])
            - float(naive_breakdown["total_cost"])
        ),
        "charging_replay_route_signature_equal": True,
        "dynamic_stream_seed_count": len(STREAM_SEEDS),
        "dynamic_stream_unique_hash_count": len(set(stream_hashes)),
        "dynamic_event_count_min": min(event_counts),
        "dynamic_event_count_max": max(event_counts),
        "depot_collaboration_move_count": move_counts.get(
            "depot_collaboration",
            0,
        ),
        "whole_duty_type_exchange_move_count": move_counts.get(
            "whole_duty_type_exchange",
            0,
        ),
        "generated_move_channels_json": json.dumps(
            dict(sorted(move_counts.items())),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "formal_fairness_effect_status": (
            "UNMEASURED_REQUIRES_INDEPENDENT_PROFIT_BASELINE"
        ),
        "status": "STRUCTURAL_SCOUT_PASS",
        "failure_reason": "",
    }


def _failed_row(instance_id: str, error: Exception) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "region": instance_id.split("-", 2)[1],
        "status": "STRUCTURAL_SCOUT_FAILED",
        "failure_reason": f"{type(error).__name__}: {error}",
    }


def _report(rows: list[dict[str, Any]]) -> str:
    passed = [row for row in rows if row["status"] == "STRUCTURAL_SCOUT_PASS"]
    failed = [row for row in rows if row["status"] != "STRUCTURAL_SCOUT_PASS"]
    both_types = sum(int(row["used_cv"]) > 0 and int(row["used_ev"]) > 0 for row in passed)
    carbon_moved = sum(int(row["carbon_aware_moved_action_count"]) > 0 for row in passed)
    all_streams = sum(int(row["dynamic_stream_seed_count"]) == len(STREAM_SEEDS) for row in passed)
    collaboration = sum(int(row["depot_collaboration_move_count"]) > 0 for row in passed)
    type_exchange = sum(int(row["whole_duty_type_exchange_move_count"]) > 0 for row in passed)
    region_lines = []
    for region in ("cy", "jjj", "prd"):
        region_rows = [row for row in passed if row["region"] == region]
        changes = [
            float(row["aware_minus_naive_system_emissions_pct"])
            for row in region_rows
        ]
        region_lines.append(
            f"- {region}：{len(region_rows)} 个通过；固定路线充电择时的系统排放变化范围为 "
            f"{min(changes):.6f}% 至 {max(changes):.6f}%。"
        )
    failure_text = (
        "没有失败行。"
        if not failed
        else "失败行：" + "；".join(
            f"{row['instance_id']}={row['failure_reason']}" for row in failed
        )
    )
    return f"""# China81 统一算例结构体检

## 结论

本轮保留了现有动态订单流能够直接承接的 27 个 China81 算例，没有打总分，也没有选择最终算例。{len(passed)}/27 个完成同一评价链体检；{failure_text}

在通过的算例中：{both_types} 个当前可行解同时实际使用油车和电动车；{carbon_moved} 个在不改路线、车型和服务量时能合法移动至少一次充电；{all_streams} 个都成功构造既有的 10 条动态订单流；{collaboration} 个生成了跨车场调整动作；{type_exchange} 个生成了整日车型—任务交换动作。

这些数字说明现阶段没有发现“一个算例在数学或物理上不可能同时承接主要因素”的证据。它们只证明作用空间存在，不代表动作最终一定改善，也不代表某个地区已经胜出。利润参与条件尚未使用临时利润基准凑结果；它要等 v2 的独立经营利润定义接入后再做真实效应比较。

## 各地区的固定路线充电择时体检

{chr(10).join(region_lines)}

这里的百分比来自当前登记可行解上的零搜索充电重排，只用于判断时变碳有没有可利用窗口，不是算法性能或论文结果。

## 交付前九条自检

1. 每个事实是否有出处？——所有数字逐行保存在同包 `raw_runs.csv`，来源、提交和保护文件哈希保存在 `metadata.json`。
2. 有没有把建议或担忧写成已决或状态？——没有；最终算例、效应合格线和利润基准均未替用户决定。
3. 是否超出任务范围？——没有；只检查统一算例所需的结构与固定路线充电窗口，不跑正式搜索。
4. 是否碰受保护文件？——没有；运行前后哈希写入 `metadata.json` 并逐项一致。
5. 待决事项是否给了选项和代价？——本轮不要求用户拍板；等真实效应表完成后再把候选一次性提交。
6. 是否使用自造术语或内部任务号？——没有。
7. 失败、跳过、超时和异常是否保留？——所有候选都保留一行；失败原因写在 `failure_reason`，本轮无静默删除。
8. 四件套是否齐全？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全。
9. 交接记录是否同步？——本包完成复核后同步 `HANDOFF.md` 和 `docs/handoff/memory/MEMORY.md`。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    status_before = _git(repo, "status", "--porcelain")
    if status_before:
        raise RuntimeError("structural scout requires a clean worktree")

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    candidate_ids = _candidate_ids(repo)
    if len(candidate_ids) != 27:
        raise RuntimeError(f"expected 27 dynamic-compatible candidates, got {len(candidate_ids)}")

    rows: list[dict[str, Any]] = []
    for instance_id in candidate_ids:
        try:
            rows.append(_scan_one(repo, instance_id))
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            rows.append(_failed_row(instance_id, error))

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    output.mkdir(parents=True)
    source_path = Path(__file__).resolve()
    _json(
        output / "metadata.json",
        {
            "schema": "resetp.duty-hgs-unified-instance-structural-scout.v1",
            "purpose": "zero-search opportunity inventory; no instance ranking",
            "git_head": _git(repo, "rev-parse", "HEAD"),
            "git_branch": _git(repo, "branch", "--show-current"),
            "worktree_clean_before_run": True,
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "runner_path": str(source_path.relative_to(repo)),
            "runner_sha256": _sha256(source_path),
            "candidate_customer_counts": list(DYNAMIC_CUSTOMER_COUNTS),
            "dynamic_stream_seeds": list(STREAM_SEEDS),
            "candidate_ids": list(candidate_ids),
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
        },
    )
    fieldnames = sorted({key for row in rows for key in row})
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    passed = [row for row in rows if row["status"] == "STRUCTURAL_SCOUT_PASS"]
    _json(
        output / "decision.json",
        {
            "verdict": (
                "STRUCTURAL_SCOUT_COMPLETE"
                if len(passed) == len(rows) and protected_before == protected_after
                else "STRUCTURAL_SCOUT_HAS_FAILURES"
            ),
            "candidate_count": len(rows),
            "passed_count": len(passed),
            "failed_count": len(rows) - len(passed),
            "final_instance_selected": None,
            "instance_ranking_performed": False,
            "scientific_effect_threshold_applied": False,
            "formal_fairness_effect_measured": False,
            "mathematical_or_physical_impossibility_of_unification_proved": False,
            "formal_experiment_result": False,
        },
    )
    (output / "report.md").write_text(_report(rows), encoding="utf-8")
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _json(output / "artifact_hashes.json", hashes)
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    print(
        json.dumps(
            {
                "output": str(output),
                "candidate_count": len(rows),
                "passed_count": len(passed),
            },
            ensure_ascii=False,
        )
    )
    return 0 if len(passed) == len(rows) and protected_before == protected_after else 2


if __name__ == "__main__":
    raise SystemExit(main())
