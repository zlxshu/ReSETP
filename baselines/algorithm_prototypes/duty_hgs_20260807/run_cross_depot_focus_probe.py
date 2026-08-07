#!/usr/bin/env python3
"""Evaluate the geometrically promising cross-depot moves on one China81 input.

The probe is deliberately narrower than a full education round.  It reads the
already saved geometric screen, keeps only customers whose selected distance
delta is negative, and sends every existing cross-depot move involving those
customers through the same charging repair, incremental evaluator, and
full-truth sentinel used by Duty education.  It does not apply a move, rank
instances, or select a formal experiment case.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import resource
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

from duty_hgs.charging import ChargingRepairCache
from duty_hgs.contracts import SearchAccounting
from duty_hgs.education import evaluate_move
from duty_hgs.evaluation import DutyFullEvaluator, DutyIncrementalEvaluator
from duty_hgs.operators import generate_problem_moves
from duty_hgs.population import AdaptivePenaltyManager
from run_real_input_technical_trial import (
    PROTECTED,
    _build_context,
    _json,
    _parameters,
    _policy,
    _sha256,
    _source_provenance,
    _write_failure_package,
)

FIELDS = (
    "action_id",
    "focus_customer_ids",
    "focus_distance_advantage_km",
    "status",
    "evaluated",
    "complete_model_feasible",
    "violation_count",
    "violations_json",
    "cross_site_service_count",
    "after_cost_cny",
    "cost_change_cny",
    "after_emissions_kg",
    "minimum_participation_margin_cny",
    "penalized_change_cny",
    "improves_initial_penalized",
    "maximum_charge_end_soc",
    "charging_actions_entering_taper_region",
    "wall_seconds",
    "error_type",
    "error",
)


FOCUS_MODES = {
    "all_cross_depot": {
        "column": None,
        "description": "all generated cross-depot moves",
    },
    "direct_roundtrip": {
        "column": "best_alternate_minus_owner_roundtrip_km",
        "description": "alternate-depot direct round trip",
    },
    "route_marginal_capacity": {
        "column": "best_capacity_relocate_net_delta_km",
        "description": "capacity-feasible route-marginal relocation",
    },
}


def _focus_customers(
    opportunity_csv: Path,
    instance_id: str,
    focus_mode: str = "direct_roundtrip",
) -> dict[str, float]:
    try:
        mode = FOCUS_MODES[focus_mode]
    except KeyError as exc:
        raise ValueError(f"unknown focus mode: {focus_mode}") from exc
    column = mode["column"]
    if column is None:
        raise ValueError("all-cross-depot mode does not use a geometric screen")
    with opportunity_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {
        row["customer_id"]: float(row[column])
        for row in rows
        if row["instance_id"] == instance_id
        and row.get(column, "") not in (None, "")
        and float(row[column]) < 0.0
    }
    if not result:
        raise ValueError(
            f"{instance_id} has no customer with a negative {column} "
            "in the saved geometric screen"
        )
    return result


def _move_customers(move: Any) -> frozenset[str]:
    return frozenset(
        str(getattr(move, name))
        for name in (
            "customer_id",
            "left_customer_id",
            "right_customer_id",
        )
        if hasattr(move, name)
    )


def _charging_observations(evaluation, capacity_kwh: float) -> tuple[float, int]:
    ends = [
        float(action.end_energy_kwh)
        for action in evaluation.prepared_solution.charging_actions
        if action.end_energy_kwh is not None
    ]
    if not ends:
        return 0.0, 0
    threshold = 0.9 * float(capacity_kwh)
    return (
        max(ends) / float(capacity_kwh),
        sum(value > threshold + 1.0e-9 for value in ends),
    )


def _peak_rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return value / (1024.0 * 1024.0)
    return value / 1024.0


def _optional_float(value: float | None) -> float | str:
    return "" if value is None else float(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument(
        "--opportunity-csv",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--focus-mode",
        choices=tuple(FOCUS_MODES),
        default="direct_roundtrip",
    )
    parser.add_argument("--stderr-capture-state", default="caller_not_declared")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[3]
    output = args.output_dir.resolve()
    if args.focus_mode == "all_cross_depot":
        if args.opportunity_csv is not None:
            raise ValueError(
                "all-cross-depot mode does not accept an opportunity CSV"
            )
        opportunity_csv = None
    elif args.opportunity_csv is None:
        relative_csv = (
            "unified_instance_scout/opportunity_27_20260807/"
            "customer_opportunities.csv"
            if args.focus_mode == "direct_roundtrip"
            else "unified_instance_scout/marginal_27_20260807/"
            "customer_marginals.csv"
        )
        opportunity_csv = (
            repo
            / "baselines/algorithm_prototypes/duty_hgs_20260807"
            / relative_csv
        )
    else:
        opportunity_csv = args.opportunity_csv.resolve()
    focus_description = FOCUS_MODES[args.focus_mode]["description"]
    focus_column = FOCUS_MODES[args.focus_mode]["column"]
    provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state=args.stderr_capture_state,
    )
    if not provenance["worktree_clean_before_run"]:
        raise RuntimeError("cross-depot focus probe requires a clean worktree")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": (
                "one-step cross-depot focus probe on customers with a "
                f"negative saved {focus_description} distance delta"
            ),
            "instance_id": args.instance_id,
            "code_provenance": provenance,
            "opportunity_csv": (
                None if opportunity_csv is None else str(opportunity_csv)
            ),
            "focus_mode": args.focus_mode,
        },
    )

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    bundle, initial, pi0, context = _build_context(repo, args.instance_id)
    evaluator = DutyFullEvaluator(context)
    initial_evaluation = evaluator.evaluate(initial)
    if not initial_evaluation.feasible:
        raise ValueError("registered initial solution is not complete-model feasible")
    policy = _policy(evaluator)
    parameters = _parameters()
    penalty_manager = AdaptivePenaltyManager(parameters.penalties)
    penalty_manager.register(initial_evaluation)
    initial_penalized = float(penalty_manager.cost(initial_evaluation))
    capacity = bundle.instance.battery_capacity_kwh(
        fallback=bundle.prices.B_battery_kwh
    )
    initial_max_soc, initial_taper_actions = _charging_observations(
        initial_evaluation,
        capacity,
    )

    all_moves = generate_problem_moves(
        initial,
        initial_evaluation,
        bundle.instance,
    )
    cross_moves = tuple(
        move for move in all_moves if move.channel == "depot_collaboration"
    )
    if args.focus_mode == "all_cross_depot":
        focused_moves = tuple(sorted(cross_moves, key=lambda move: move.action_id))
        focus = {
            customer_id: 0.0
            for move in focused_moves
            for customer_id in _move_customers(move)
        }
    else:
        if opportunity_csv is None:
            raise AssertionError("geometric focus mode requires an input CSV")
        focus = _focus_customers(
            opportunity_csv,
            args.instance_id,
            args.focus_mode,
        )
        focused_moves = tuple(
            sorted(
                (
                    move
                    for move in cross_moves
                    if _move_customers(move).intersection(focus)
                ),
                key=lambda move: move.action_id,
            )
        )
    if not focused_moves:
        raise ValueError("no generated cross-depot move involves a focus customer")

    accounting = SearchAccounting()
    incremental = DutyIncrementalEvaluator(evaluator)
    accounting.record_cache_seed(incremental.seed(initial))
    repair_cache = (
        None
        if args.focus_mode == "all_cross_depot"
        else ChargingRepairCache(context, policy)
    )
    status_counts: Counter[str] = Counter()
    error_counts: Counter[tuple[str, str, str]] = Counter()
    evaluated_count = 0
    feasible_count = 0
    improving_count = 0
    best = None
    best_penalized = None
    best_row: dict[str, Any] | None = None
    started = perf_counter()

    with (output / "candidate_rows.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for move in focused_moves:
            outcome = evaluate_move(
                initial,
                move,
                evaluator=evaluator,
                charging_policy=policy,
                incremental_evaluator=incremental,
                charging_repair_cache=repair_cache,
            )
            accounting.record_outcome(outcome)
            status = outcome.status.value
            status_counts[status] += 1
            involved = sorted(_move_customers(move).intersection(focus))
            evaluation = outcome.evaluation
            after_cost = None
            cost_change = None
            after_emissions = None
            minimum_margin = None
            penalized_change = None
            improves = False
            feasible = False
            violations = None
            violation_rows: list[dict[str, Any]] = []
            cross_site_count = None
            maximum_charge_end_soc = None
            taper_actions = None
            if evaluation is not None:
                evaluated_count += 1
                after_cost = float(evaluation.total_cost)
                cost_change = after_cost - float(initial_evaluation.total_cost)
                after_emissions = float(evaluation.breakdown["E_total"])
                minimum_margin = min(
                    float(value)
                    for value in evaluation.participation_margin.values()
                )
                candidate_penalized = float(penalty_manager.cost(evaluation))
                penalized_change = candidate_penalized - initial_penalized
                feasible = bool(evaluation.feasible)
                violations = len(evaluation.violations)
                violation_rows = [
                    asdict(item) for item in evaluation.violations
                ]
                cross_site_count = len(
                    evaluation.prepared_solution.cross_site_services
                )
                maximum_charge_end_soc, taper_actions = (
                    _charging_observations(evaluation, capacity)
                )
                improves = bool(feasible and penalized_change < 0.0)
                feasible_count += int(feasible)
                improving_count += int(improves)
                if feasible and (
                    best_penalized is None
                    or candidate_penalized < best_penalized
                    or (
                        candidate_penalized == best_penalized
                        and outcome.action_id < best.action_id
                    )
                ):
                    best = outcome
                    best_penalized = candidate_penalized
            if outcome.error_type or outcome.error:
                error_counts[(status, outcome.error_type or "", outcome.error or "")] += 1
            row = {
                "action_id": outcome.action_id,
                "focus_customer_ids": "|".join(involved),
                "focus_distance_advantage_km": "|".join(
                    f"{customer}:{-focus[customer]:.12g}" for customer in involved
                ) if args.focus_mode != "all_cross_depot" else "",
                "status": status,
                "evaluated": evaluation is not None,
                "complete_model_feasible": feasible if evaluation is not None else "",
                "violation_count": "" if violations is None else violations,
                "violations_json": json.dumps(
                    violation_rows,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "cross_site_service_count": (
                    "" if cross_site_count is None else cross_site_count
                ),
                "after_cost_cny": _optional_float(after_cost),
                "cost_change_cny": _optional_float(cost_change),
                "after_emissions_kg": _optional_float(after_emissions),
                "minimum_participation_margin_cny": _optional_float(minimum_margin),
                "penalized_change_cny": _optional_float(penalized_change),
                "improves_initial_penalized": improves if evaluation is not None else "",
                "maximum_charge_end_soc": _optional_float(maximum_charge_end_soc),
                "charging_actions_entering_taper_region": (
                    "" if taper_actions is None else taper_actions
                ),
                "wall_seconds": float(outcome.wall_seconds),
                "error_type": outcome.error_type or "",
                "error": outcome.error or "",
            }
            writer.writerow(row)
            handle.flush()
            if best is outcome:
                best_row = dict(row)

    error_rows = [
        {
            "status": status,
            "error_type": error_type,
            "error": error,
            "count": count,
        }
        for (status, error_type, error), count in sorted(error_counts.items())
    ]
    if error_rows:
        with (output / "rejection_summary.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=tuple(error_rows[0]),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(error_rows)

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    failure_reasons = []
    if protected_before != protected_after:
        failure_reasons.append("a protected evaluator file changed")
    if accounting.sentinel_evaluations <= 0:
        failure_reasons.append("the full-truth sentinel was not exercised")
    verdict = (
        "CROSS_DEPOT_FOCUS_PROBE_COMPLETE"
        if not failure_reasons
        else "CROSS_DEPOT_FOCUS_PROBE_FAILED"
    )
    elapsed = perf_counter() - started
    raw_row = {
        "instance_id": args.instance_id,
        "verdict": verdict,
        "focus_customer_count": len(focus),
        "focus_customers_json": json.dumps(
            focus, ensure_ascii=False, sort_keys=True
        ),
        "all_generated_move_count": len(all_moves),
        "all_cross_depot_move_count": len(cross_moves),
        "focused_cross_depot_move_count": len(focused_moves),
        "evaluated_count": evaluated_count,
        "complete_model_feasible_count": feasible_count,
        "improving_feasible_count": improving_count,
        "status_counts_json": json.dumps(
            dict(sorted(status_counts.items())),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "initial_cost_cny": float(initial_evaluation.total_cost),
        "initial_emissions_kg": float(initial_evaluation.breakdown["E_total"]),
        "initial_minimum_participation_margin_cny": min(
            float(value)
            for value in initial_evaluation.participation_margin.values()
        ),
        "initial_maximum_charge_end_soc": initial_max_soc,
        "initial_charging_actions_entering_taper_region": initial_taper_actions,
        "best_feasible_action_id": "" if best is None else best.action_id,
        "best_feasible_penalized_change_cny": (
            "" if best_penalized is None else best_penalized - initial_penalized
        ),
        "best_feasible_improves_initial": bool(
            best_penalized is not None and best_penalized < initial_penalized
        ),
        "incremental_evaluations": accounting.incremental_evaluations,
        "sentinel_evaluations": accounting.sentinel_evaluations,
        "wall_seconds": elapsed,
        "peak_rss_mb": _peak_rss_mb(),
        "failure_reason": "; ".join(failure_reasons),
    }
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=tuple(raw_row),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(raw_row)

    if best is not None and best.evaluation is not None and best.candidate is not None:
        _json(
            output / "best_candidate.json",
            {
                "candidate": asdict(best.candidate),
                "evaluation": {
                    "total_cost": float(best.evaluation.total_cost),
                    "breakdown": dict(best.evaluation.breakdown),
                    "violations": [
                        asdict(item) for item in best.evaluation.violations
                    ],
                    "participation_margin": dict(
                        best.evaluation.participation_margin
                    ),
                    "prepared_solution": asdict(
                        best.evaluation.prepared_solution
                    ),
                },
                "candidate_row": best_row,
            },
        )

    _json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failure_reasons": failure_reasons,
            "formal_algorithm_result": False,
            "formal_mechanism_result": False,
            "formal_instance_selected": None,
            "probe_scope": (
                "one-step existing depot-collaboration moves involving only "
                f"customers whose saved {focus_description} distance delta "
                "is strictly negative"
            ),
            "what_this_does_not_answer": [
                "the value of all cross-depot moves",
                "the result after repeated full-neighbourhood education",
                "a formal fairness effect",
                "a formal nonlinear-charging effect",
                "a dynamic rolling-policy effect",
            ],
        },
    )
    metadata = {
        "status": "COMPLETE" if not failure_reasons else "FAILED",
        "purpose": (
            "one-step cross-depot focus probe on customers with a negative "
            f"saved {focus_description} distance delta"
        ),
        "instance_id": args.instance_id,
        "instance_formally_selected": False,
        "code_provenance": provenance,
        "opportunity_csv": (
            None if opportunity_csv is None else str(opportunity_csv)
        ),
        "focus_mode": args.focus_mode,
        "focus_rule": (
            "all generated depot-collaboration moves; no geometric filter"
            if focus_column is None
            else f"{focus_column} < 0 in the already saved geometric screen; "
            "no result-dependent threshold"
        ),
        "focus_customers": focus,
        "truth_sentinel_enabled": context.incremental_full_truth_sentinel_enabled,
        "battery_capacity_kwh": capacity,
        "taper_start_soc": 0.9,
        "penalty_parameters": asdict(parameters.penalties),
        "charging_policy": asdict(policy),
        "pi0": {
            "values": pi0,
            "externally_frozen": False,
            "formal_reuse_allowed": False,
        },
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    _json(output / "metadata.json", metadata)
    report = f"""# 跨车场高机会动作技术探针

## 结论

`{args.instance_id}` 共有 {len(focus)} 名客户在已保存的“{focus_description}”筛查中距离变化为负。现有动作生成器围绕这些客户生成 {len(focused_moves)} 个跨车场候选，其中 {evaluated_count} 个进入完整评价，{feasible_count} 个通过完整模型，{improving_count} 个相对登记起点的罚后目标更优。完整真值复核执行 {accounting.sentinel_evaluations} 次，耗时 {elapsed:.3f} 秒，进程峰值内存 {raw_row['peak_rss_mb']:.3f} MB。

本探针不应用候选，不跑完整教育，不选择正式算例。其范围只覆盖几何上已经跨场更近的客户；空结果不代表所有跨车场动作无效。

## 交付前九条自检

1. 每个事实是否有出处？——逐动作证据在 `candidate_rows.csv`，拒绝汇总在 `rejection_summary.csv`，总数在 `raw_runs.csv`。
2. 有没有把建议或担忧写成已决或状态？——没有；算例没有被选定。
3. 是否超出任务范围？——没有；只检查统一算例探索中的跨车场缺口。
4. 是否碰受保护文件？——未碰；三个文件前后哈希一致，见 `metadata.json`。
5. 待决事项是否给出选项和代价？——本包不新增用户待决事项。
6. 是否使用自造词或内部任务号？——没有。
7. 失败、跳过、超时和异常是否保留？——每个拒绝状态逐行保留，重复原因另有汇总。
8. 四件套是否齐全？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，另附候选明细。
9. 交接记录是否同步？——三个算例探针完成后统一同步项目交接和记忆。
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
    print(
        json.dumps(
            {
                "output": str(output),
                "verdict": verdict,
                "focused_moves": len(focused_moves),
                "evaluated": evaluated_count,
                "feasible": feasible_count,
                "improving": improving_count,
                "wall_seconds": elapsed,
                "peak_rss_mb": raw_row["peak_rss_mb"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if not failure_reasons else 2


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
