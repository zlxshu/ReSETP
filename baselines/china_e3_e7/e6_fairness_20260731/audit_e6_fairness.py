#!/usr/bin/env python3
"""Zero-search E6 member-accounting audit over the sealed E3 solutions.

This program deliberately does not call a search routine.  It reuses the
twenty E3 ZONE/JOINT solution pairs, applies the repository's existing depot
profit ledger, audits whether the E3 JOINT runs persisted their nested
candidate solutions, and closes fail-closed when those candidates are absent.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean, median
import sys
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
E3_ROOT = ROOT / "baselines/china_e3_e7/e3_zone_joint_20260731"
E3_RUNNER = E3_ROOT / "run_e3_zone_joint.py"
CONTRACT = (
    ROOT
    / "docs/handoff/experiment_contract_v2_journal_aligned_20260730.md"
)
PROFIT_SOURCE = ROOT / "solver/src/setp_solver/profit.py"
TASK_ID = "E6-FAIRNESS-20260731"
STATUS = "HALT_E3_NESTED_CANDIDATE_SOLUTIONS_NOT_PERSISTED"
MISSING = "NA_CANDIDATE_POOL_NOT_PERSISTED"
THETA = 1.0
TOLERANCE = 1.0e-9
INSTANCES = (
    ("cn-prd-50c-01-V2-LOCATIONS", "MAIN_EXHIBIT"),
    ("cn-prd-100c-02-V2-LOCATIONS", "ROBUSTNESS"),
)
SEEDS = tuple(range(1, 11))
PROTECTED_HASHES = {
    "solver/src/setp_solver/cost.py":
        "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be",
    "solver/src/setp_solver/check.py":
        "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8",
    "solver/src/setp_solver/search/evaluation.py":
        "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py":
        "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1",
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/epochal_hgs.py":
        "655fa347b52a3e8ac20c5da6213c84b09ac90f96c1513ca95554753aad3f8a91",
}
EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache", "monitor_runtime"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(fields)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    line = f"{now_iso()} {message}"
    print(line, flush=True)
    with (HERE / "progress.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def verify_protected_hashes() -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, expected in PROTECTED_HASHES.items():
        path = ROOT / name
        actual = sha256(path)
        observed[name] = actual
        if actual != expected:
            raise RuntimeError(
                f"HALT_PROTECTED_HASH_DRIFT:{name}:{actual}!={expected}"
            )
    return observed


def verify_e3_manifest() -> dict[str, Any]:
    done = read_json(E3_ROOT / "done.json")
    if done.get("status") != "COMPLETE" or int(done.get("formal_units_run", -1)) != 40:
        raise RuntimeError("HALT_E3_NOT_COMPLETE")
    manifest = read_json(E3_ROOT / "artifact_hashes.json")
    files = dict(manifest["files"])
    failures: list[dict[str, str]] = []
    for name, expected in sorted(files.items()):
        path = ROOT / name
        if not path.is_file():
            failures.append(
                {"path": name, "expected": expected, "actual": "MISSING"}
            )
            continue
        actual = sha256(path)
        if actual != expected:
            failures.append(
                {"path": name, "expected": expected, "actual": actual}
            )
    if failures:
        raise RuntimeError(f"HALT_E3_ARTIFACT_HASH_DRIFT:{failures[:3]}")
    return {
        "e3_done_sha256": sha256(E3_ROOT / "done.json"),
        "e3_decision_sha256": sha256(E3_ROOT / "decision.json"),
        "e3_manifest_sha256": sha256(E3_ROOT / "artifact_hashes.json"),
        "e3_manifest_id": manifest["manifest_id"],
        "e3_manifest_file_count": len(files),
        "e3_manifest_failures": 0,
    }


def load_e3_modules() -> tuple[Any, Any]:
    for path in (ROOT / "solver/src", ROOT):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "e3_zone_joint_for_e6",
        E3_RUNNER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("HALT_E3_RUNNER_IMPORT_SPEC")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    e3 = runner.load_e3()
    return runner, e3


def recursive_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(recursive_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(recursive_keys(item))
    return keys


def audit_candidate_persistence() -> dict[str, Any]:
    traces: list[dict[str, Any]] = []
    forbidden_payload_keys = {
        "solution",
        "solution_payload",
        "routes",
        "node_sequence",
        "charging_actions",
        "member_profit",
        "depot_profit",
        "profit_breakdown",
    }
    offending: list[dict[str, Any]] = []
    trace_keys: set[str] = set()
    entry_keys: set[str] = set()
    total_entries = 0
    feasible_entries = 0
    route_pool_candidate_solutions_reported = 0
    for instance_id, _ in INSTANCES:
        for seed in SEEDS:
            path = (
                E3_ROOT
                / "formal/search_traces"
                / f"{instance_id}__seed{seed:02d}__JOINT.json"
            )
            payload = read_json(path)
            trace = list(payload["complete_candidate_evaluation_trace"])
            keys = recursive_keys(trace)
            present = sorted(forbidden_payload_keys.intersection(keys))
            if present:
                offending.append(
                    {"path": relative(path), "forbidden_keys": present}
                )
            trace_keys.update(payload.keys())
            for item in trace:
                entry_keys.update(item.keys())
                if item.get("failure_category") == "FEASIBLE":
                    feasible_entries += 1
            total_entries += len(trace)
            route_pool_candidate_solutions_reported += int(
                payload["route_pool_stats"][
                    "route_pool_candidate_solution_count"
                ]
            )
            traces.append(
                {
                    "path": relative(path),
                    "entry_count": len(trace),
                    "feasible_entry_count": sum(
                        item.get("failure_category") == "FEASIBLE"
                        for item in trace
                    ),
                    "route_pool_candidate_solution_count": int(
                        payload["route_pool_stats"][
                            "route_pool_candidate_solution_count"
                        ]
                    ),
                }
            )
    if offending:
        raise RuntimeError(
            f"HALT_UNEXPECTED_CANDIDATE_PAYLOAD_SCHEMA:{offending[:3]}"
        )
    final_plan_count = len(
        list((E3_ROOT / "formal/plans").glob("*__JOINT.json"))
    )
    if final_plan_count != 20:
        raise RuntimeError(
            f"HALT_E3_JOINT_FINAL_PLAN_DENOMINATOR:{final_plan_count}"
        )
    return {
        "schema": "resetp.e6-candidate-persistence-audit.v1",
        "created_at_utc": now_iso(),
        "e3_joint_trace_count": len(traces),
        "e3_joint_final_plan_count": final_plan_count,
        "trace_entry_count": total_entries,
        "trace_feasible_entry_count": feasible_entries,
        "route_pool_candidate_solution_count_reported": (
            route_pool_candidate_solutions_reported
        ),
        "trace_top_level_keys": sorted(trace_keys),
        "trace_entry_keys": sorted(entry_keys),
        "candidate_solution_payload_keys_found": [],
        "candidate_member_ledger_fields_found": [],
        "candidate_solution_files_found": 0,
        "only_final_solution_persisted_per_joint_unit": True,
        "nested_candidate_pool_reconstructible_from_current_artifacts": False,
        "reason": (
            "The trace stores evaluation index, source, status, objective, "
            "failure category, view and iteration, but not candidate routes, "
            "charging actions, solution hashes, or member-profit breakdowns."
        ),
        "traces": traces,
    }


def state_row(
    *,
    instance_id: str,
    sample_role: str,
    seed: int,
    state: str,
    source_arm: str,
    plan: dict[str, Any],
    status: dict[str, Any],
    breakdowns: dict[str, Any],
    baseline_profit: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    profits = {
        depot: float(item.profit)
        for depot, item in sorted(breakdowns.items())
    }
    costs = {
        depot: float(item.cost_total)
        for depot, item in sorted(breakdowns.items())
    }
    margins = {
        depot: profits[depot] - baseline_profit[depot]
        for depot in profits
    }
    ratios = {
        depot: profits[depot] / baseline_profit[depot]
        for depot in profits
    }
    minimum_member = min(margins, key=lambda depot: (margins[depot], depot))
    all_no_worse = all(
        margin >= -TOLERANCE for margin in margins.values()
    )
    row = {
        "instance_id": instance_id,
        "sample_role": sample_role,
        "seed": seed,
        "state": state,
        "state_status": "PASS_REUSED_E3_FINAL_SOLUTION",
        "source_arm": source_arm,
        "source_plan_path": str(status["plan_path"]),
        "source_plan_sha256": sha256(ROOT / str(status["plan_path"])),
        "source_solution_sha256": str(plan["solution_sha256"]),
        "total_cost_cny": float(plan["independent_recompute"]["objective"]),
        "vehicle_count": int(status["vehicle_count"]),
        "elapsed_seconds": float(status["elapsed_wall_seconds"]),
        "complete_candidate_evaluations_consumed": int(
            plan["complete_candidate_evaluations_consumed"]
        ),
        "profit_D_guangzhou_cny": profits["D_guangzhou"],
        "profit_D_shenzhen_cny": profits["D_shenzhen"],
        "member_profit_json": json.dumps(
            profits, ensure_ascii=False, sort_keys=True
        ),
        "member_cost_json": json.dumps(
            costs, ensure_ascii=False, sort_keys=True
        ),
        "member_profit_margin_vs_I_json": json.dumps(
            margins, ensure_ascii=False, sort_keys=True
        ),
        "member_profit_ratio_vs_I_json": json.dumps(
            ratios, ensure_ascii=False, sort_keys=True
        ),
        "weak_member_id": minimum_member,
        "weak_member_profit_change_vs_I_cny": margins[minimum_member],
        "minimum_member_profit_ratio": min(ratios.values()),
        "all_members_no_worse_than_I": all_no_worse,
        "theta": THETA,
        "search_reruns": 0,
        "nested_candidate_is_independent_sample": False,
    }
    member_rows: list[dict[str, Any]] = []
    for depot in sorted(profits):
        member_rows.append(
            {
                "instance_id": instance_id,
                "sample_role": sample_role,
                "seed": seed,
                "state": state,
                "member_id": depot,
                "baseline_profit_I_cny": baseline_profit[depot],
                "state_profit_cny": profits[depot],
                "profit_change_vs_I_cny": margins[depot],
                "profit_ratio_vs_I": ratios[depot],
                "participation_satisfied": margins[depot] >= -TOLERANCE,
                "status": "PASS_REUSED_E3_FINAL_SOLUTION",
            }
        )
    return row, member_rows


def missing_f_rows(
    instance_id: str,
    sample_role: str,
    seed: int,
    baseline_profit: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    row = {
        "instance_id": instance_id,
        "sample_role": sample_role,
        "seed": seed,
        "state": "F",
        "state_status": STATUS,
        "source_arm": MISSING,
        "source_plan_path": MISSING,
        "source_plan_sha256": MISSING,
        "source_solution_sha256": MISSING,
        "total_cost_cny": MISSING,
        "vehicle_count": MISSING,
        "elapsed_seconds": MISSING,
        "complete_candidate_evaluations_consumed": MISSING,
        "profit_D_guangzhou_cny": MISSING,
        "profit_D_shenzhen_cny": MISSING,
        "member_profit_json": MISSING,
        "member_cost_json": MISSING,
        "member_profit_margin_vs_I_json": MISSING,
        "member_profit_ratio_vs_I_json": MISSING,
        "weak_member_id": MISSING,
        "weak_member_profit_change_vs_I_cny": MISSING,
        "minimum_member_profit_ratio": MISSING,
        "all_members_no_worse_than_I": MISSING,
        "theta": THETA,
        "search_reruns": 0,
        "nested_candidate_is_independent_sample": False,
    }
    member_rows = [
        {
            "instance_id": instance_id,
            "sample_role": sample_role,
            "seed": seed,
            "state": "F",
            "member_id": depot,
            "baseline_profit_I_cny": value,
            "state_profit_cny": MISSING,
            "profit_change_vs_I_cny": MISSING,
            "profit_ratio_vs_I": MISSING,
            "participation_satisfied": MISSING,
            "status": STATUS,
        }
        for depot, value in sorted(baseline_profit.items())
    ]
    return row, member_rows


def collect_ledger(runner: Any, e3: Any) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    from setp_solver.profit import calculate_depot_profits

    raw_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    for instance_id, sample_role in INSTANCES:
        bundle = e3.load_bundle(instance_id)
        for seed in SEEDS:
            arm_data: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
            for arm in ("ZONE", "JOINT"):
                stem = f"{instance_id}__seed{seed:02d}__{arm}"
                plan_path = E3_ROOT / "formal/plans" / f"{stem}.json"
                status_path = (
                    E3_ROOT / "formal/task_status" / f"{stem}.json"
                )
                plan = read_json(plan_path)
                task_status = read_json(status_path)
                if canonical_sha256(plan["solution"]) != plan["solution_sha256"]:
                    raise RuntimeError(
                        f"HALT_E3_SOLUTION_PAYLOAD_DRIFT:{stem}"
                    )
                solution = e3.annotate_cross_site_services(
                    e3.solution_from_payload(plan["solution"]),
                    bundle.customer_home_depot,
                )
                breakdowns = calculate_depot_profits(
                    solution,
                    bundle.instance,
                    bundle.time_profile,
                    bundle.prices,
                    customer_home_depot=dict(bundle.customer_home_depot),
                    carbon_quota_kg=0.0,
                )
                allocated_cost = sum(
                    float(item.cost_total) for item in breakdowns.values()
                )
                objective = float(
                    plan["independent_recompute"]["objective"]
                )
                if not math.isclose(
                    allocated_cost,
                    objective,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-8,
                ):
                    raise RuntimeError(
                        f"HALT_MEMBER_COST_ALLOCATION_CLOSURE:"
                        f"{stem}:{allocated_cost}:{objective}"
                    )
                if (
                    canonical_sha256(runner.solution_payload(e3, solution))
                    != plan["solution_sha256"]
                ):
                    raise RuntimeError(
                        f"HALT_E3_SOLUTION_ROUNDTRIP_DRIFT:{stem}"
                    )
                arm_data[arm] = (plan, task_status, breakdowns)
            baseline_profit = {
                depot: float(item.profit)
                for depot, item in arm_data["ZONE"][2].items()
            }
            if any(value <= 0.0 for value in baseline_profit.values()):
                raise RuntimeError(
                    f"HALT_NONPOSITIVE_I_PROFIT:{instance_id}:{seed}:"
                    f"{baseline_profit}"
                )
            i_row, i_members = state_row(
                instance_id=instance_id,
                sample_role=sample_role,
                seed=seed,
                state="I",
                source_arm="ZONE",
                plan=arm_data["ZONE"][0],
                status=arm_data["ZONE"][1],
                breakdowns=arm_data["ZONE"][2],
                baseline_profit=baseline_profit,
            )
            u_row, u_members = state_row(
                instance_id=instance_id,
                sample_role=sample_role,
                seed=seed,
                state="U",
                source_arm="JOINT",
                plan=arm_data["JOINT"][0],
                status=arm_data["JOINT"][1],
                breakdowns=arm_data["JOINT"][2],
                baseline_profit=baseline_profit,
            )
            f_row, f_members = missing_f_rows(
                instance_id,
                sample_role,
                seed,
                baseline_profit,
            )
            raw_rows.extend((i_row, u_row, f_row))
            member_rows.extend((*i_members, *u_members, *f_members))
            log(
                f"UNIT {instance_id} seed={seed:02d} "
                f"I=PASS U=PASS "
                f"U_natural_pareto={u_row['all_members_no_worse_than_I']} "
                f"F={STATUS}"
            )
    return raw_rows, member_rows


def aggregate(
    raw_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for instance_id, sample_role in INSTANCES:
        i_rows = [
            row for row in raw_rows
            if row["instance_id"] == instance_id and row["state"] == "I"
        ]
        u_rows = [
            row for row in raw_rows
            if row["instance_id"] == instance_id and row["state"] == "U"
        ]
        natural = sum(
            bool(row["all_members_no_worse_than_I"]) for row in u_rows
        )
        summaries.append(
            {
                "instance_id": instance_id,
                "sample_role": sample_role,
                "seed_units": len(u_rows),
                "units_naturally_pareto_U": natural,
                "natural_pareto_pct_U": natural / len(u_rows) * 100.0,
                "I_total_cost_avg_cny": mean(
                    float(row["total_cost_cny"]) for row in i_rows
                ),
                "I_profit_D_guangzhou_avg_cny": mean(
                    float(row["profit_D_guangzhou_cny"])
                    for row in i_rows
                ),
                "I_profit_D_shenzhen_avg_cny": mean(
                    float(row["profit_D_shenzhen_cny"])
                    for row in i_rows
                ),
                "I_vehicle_count_avg": mean(
                    float(row["vehicle_count"]) for row in i_rows
                ),
                "I_elapsed_seconds_avg": mean(
                    float(row["elapsed_seconds"]) for row in i_rows
                ),
                "U_total_cost_avg_cny": mean(
                    float(row["total_cost_cny"]) for row in u_rows
                ),
                "U_profit_D_guangzhou_avg_cny": mean(
                    float(row["profit_D_guangzhou_cny"])
                    for row in u_rows
                ),
                "U_profit_D_shenzhen_avg_cny": mean(
                    float(row["profit_D_shenzhen_cny"])
                    for row in u_rows
                ),
                "U_vehicle_count_avg": mean(
                    float(row["vehicle_count"]) for row in u_rows
                ),
                "U_elapsed_seconds_avg": mean(
                    float(row["elapsed_seconds"]) for row in u_rows
                ),
                "U_weak_member_change_avg_cny": mean(
                    float(row["weak_member_profit_change_vs_I_cny"])
                    for row in u_rows
                ),
                "U_weak_member_change_median_cny": median(
                    float(row["weak_member_profit_change_vs_I_cny"])
                    for row in u_rows
                ),
                "F_total_cost_avg_cny": MISSING,
                "F_profit_D_guangzhou_avg_cny": MISSING,
                "F_profit_D_shenzhen_avg_cny": MISSING,
                "F_vehicle_count_avg": MISSING,
                "F_elapsed_seconds_avg": MISSING,
                "fairness_cost_pct_F_vs_U": MISSING,
                "F_weak_member_improvement_cny": MISSING,
            }
        )
    u_all = [row for row in raw_rows if row["state"] == "U"]
    overall = {
        "units_total": len(u_all),
        "units_naturally_pareto": sum(
            bool(row["all_members_no_worse_than_I"]) for row in u_all
        ),
        "natural_pareto_pct": (
            sum(bool(row["all_members_no_worse_than_I"]) for row in u_all)
            / len(u_all)
            * 100.0
        ),
        "u_complete_candidate_evaluations_consumed": sum(
            int(row["complete_candidate_evaluations_consumed"])
            for row in u_all
        ),
        "u_recorded_elapsed_seconds_sum": sum(
            float(row["elapsed_seconds"]) for row in u_all
        ),
        "u_recorded_elapsed_seconds_two_worker_lower_bound": (
            sum(float(row["elapsed_seconds"]) for row in u_all) / 2.0
        ),
        "fairness_cost_pct": None,
        "f_weak_member_improvement": None,
    }
    return summaries, overall


def fmt(value: Any, digits: int = 3) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def build_report(
    summaries: list[dict[str, Any]],
    overall: dict[str, Any],
    candidate_audit: dict[str, Any],
    e3_verification: dict[str, Any],
) -> str:
    table_rows = []
    for row in summaries:
        table_rows.append(
            "| {instance_id} | {natural}/{seed_units} | {i_cost} | "
            "{i_gz} | {i_sz} | {i_veh} | {i_time} | {u_cost} | "
            "{u_gz} | {u_sz} | {u_veh} | {u_time} | {missing} |".format(
                instance_id=row["instance_id"],
                natural=row["units_naturally_pareto_U"],
                seed_units=row["seed_units"],
                i_cost=fmt(row["I_total_cost_avg_cny"]),
                i_gz=fmt(row["I_profit_D_guangzhou_avg_cny"]),
                i_sz=fmt(row["I_profit_D_shenzhen_avg_cny"]),
                i_veh=fmt(row["I_vehicle_count_avg"], 2),
                i_time=fmt(row["I_elapsed_seconds_avg"], 2),
                u_cost=fmt(row["U_total_cost_avg_cny"]),
                u_gz=fmt(row["U_profit_D_guangzhou_avg_cny"]),
                u_sz=fmt(row["U_profit_D_shenzhen_avg_cny"]),
                u_veh=fmt(row["U_vehicle_count_avg"], 2),
                u_time=fmt(row["U_elapsed_seconds_avg"], 2),
                missing=MISSING,
            )
        )
    per_instance_findings = "\n".join(
        (
            f"- `{row['instance_id']}`：U 自然满足参与保障 "
            f"{row['units_naturally_pareto_U']}/{row['seed_units']}；"
            f"U 中弱势成员相对 I 的收益变化均值为 "
            f"{row['U_weak_member_change_avg_cny']:.3f} 元，"
            f"中位数为 {row['U_weak_member_change_median_cny']:.3f} 元。"
        )
        for row in summaries
    )
    return f"""# E6 协同收益公平实验：成员账本闭合、F 候选池缺失停机

状态：`{STATUS}`。本轮没有运行任何搜索，`search_reruns=0`。E3 的 40 个
已认证单元原样保留；I 直接复用同 seed 的 ZONE 最终解，U 直接复用同 seed 的
JOINT 最终解。成员账本已闭合，但 E3 没有保存构造 F 所需的嵌套候选解本体，
因此不能如实计算 F、公平代价或 F 下弱势成员改善。

## 三个问题的直接回答

第一，U 状态自然满足所有成员不吃亏的 seed 单元为
**{overall['units_naturally_pareto']}/{overall['units_total']}（{overall['natural_pareto_pct']:.1f}%）**。
两个算例分别见下表。这个结果按 20 个预定 seed 单元全分母报告，没有挑单元。

第二，在需要显式公平约束的单元上，F 相对 U 的系统成本增量**当前不可计算**。
原因不是成员账本缺失，而是 E3 trace 没有候选解本体；只有总成本无法判断每个候选
是否满足两名成员的参与条件，也无法从中选出最低系统成本的公平解。

第三，F 状态下弱势成员的收益改善**当前不可计算**。把 I 直接当作所有 binding
单元的 F 会人为忽略 U 候选池中可能存在的更低成本公平方案，违反“最低系统成本
公平候选 + I 回退”的定义，因此本报告没有这样近似。

## 成员收益核算定义与出处

现有账本位于 `solver/src/setp_solver/profit.py` 的
`calculate_depot_profits()`，并由 `solver/tests/test_profit.py` 的手算测试覆盖。
对一个完整解，客户收入按 `revenue_per_kg × demand_kg` 计入实际服务该客户的
路线所属车场；车辆固定费、里程成本和燃油费计入路线所属车场；充电电费、公共站
占用费和电动车间接排放根据充电动作的车辆所对应路线计入该路线所属车场；全系统
碳交易成本按各车场排放占比分摊；当服务车场不同于 `customer_home_depot` 时，
跨场服务费计入服务车场。成员总成本为上述成本之和，成员收益为
`prior_profit + revenue - cost_total`；本批 `prior_profit=0`。

I 状态下，成员基准是同一算例、同一 seed 的 E3 ZONE 最终完整解上按上述账本计算
的车场收益。U 状态下，成员实际值是对应 E3 JOINT 最终完整解上的车场收益。
参与条件固定为 θ=1，即对每个车场 d 都要求
`profit_d(state) >= profit_d(I)`。实现比较仅使用 `1e-9` 元数值容差处理浮点闭合，
不把它解释为科学松弛。40 个 I/U 方案的成员成本之和均与 E3 完整系统目标在
`1e-8` 元绝对误差内闭合。

## 期刊式主表

下表一行一算例，均为 10 seeds 均值。F 列没有用空白或 0 伪装，而是显式标注
`{MISSING}`。

| 算例 | U 自然帕累托 | I 成本 | I 广州收益 | I 深圳收益 | I 车 | I 秒 | U 成本 | U 广州收益 | U 深圳收益 | U 车 | U 秒 | F |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(table_rows)}

{per_instance_findings}

## F 为何不能从现存 E3 产物恢复

20 份 JOINT trace 共记录
{candidate_audit['trace_entry_count']} 次完整候选评价，其中
{candidate_audit['trace_feasible_entry_count']} 行被归类为可行；trace 还报告
{candidate_audit['route_pool_candidate_solution_count_reported']} 个路线池候选解。
但逐候选行只含 `evaluation_index/source/status/complete_objective/`
`failure_category/view/iteration`，没有路线、充电动作、解哈希或成员收益。
每个 JOINT 单元只在 `formal/plans/` 保存了一个最终解。运行时内存中的
`exact_candidates`/`elite_completions` 已随 E3 进程结束消失，因此现有 trace
不能反演候选的客户—车场分配、成本分摊或参与可行性。

若用户批准补跑，最小补充不是重跑 I，而是对 20 个 U 单元按原算例、seed、共同初解、
cap=400 和冻结搜索语义做一次**仅增持久化的确定性回放**：在完整候选复核点保存
候选 solution、完整目标、成员账本、可行证书及来源序号；随后验证最终 U 解哈希仍
与 E3 封存值一致，再在同次 U 候选池中筛 F，并显式加入 I 回退。按 E3 记录，这会
重新执行 {overall['u_complete_candidate_evaluations_consumed']} 次完整候选评价；
原 U 单元墙钟合计 {overall['u_recorded_elapsed_seconds_sum']:.3f} 秒，按两 worker
简单除二的计算下界约 {overall['u_recorded_elapsed_seconds_two_worker_lower_bound']/60.0:.2f}
分钟，尚未计序列化、独立复核和打包开销。本轮未执行该补跑，等待用户裁决。

## 不设 α 网格

θ 固定为 1，因为它是“每个成员均不低于不合作基准”的自然结构端点，而不是任选阈值。
旧批次 54 个 spec 中 24 个自然满足、30 个存在 binding 空间，以及 α=0.25 到 0.5
仅一次方案切换的数字，只用于解释为何本任务不设粗网格；它们没有进入本批的自然
帕累托比例、成本、成员收益或任何 E6 结果。

## 与 E3 运营权衡的联合解释

E3 已证明 JOINT 相对 ZONE 在 50c/100c 分别降本 2.272759%/0.693115%，车辆均值
由 9→8、18→17.2；与此同时，里程增加 28.04%/12.18%，碳排增加
4.04%/1.18%。本轮进一步发现，最终 U 解虽然降低系统成本，却在 20/20 seed
单元中至少使一个成员收益低于 I。因 F 尚不可计算，当前只能确认“系统降本不自动
等于成员层帕累托改进”，不能判断显式参与保障的系统代价大小。

## 可直接用于正文的中文（当前只能作为停机边界说明）

在两个预定算例的 20 个共同种子单元中，无约束联合配送最终解均未自然满足所有成员
不低于分区独立经营基准（0/20，0.0%），表明系统成本节省并未自动转化为成员层面的
帕累托改进。该发现应与 E3 的运营权衡一并理解：联合配送降低了系统总成本和车辆数，
但同时提高了行驶里程与碳排放。由于原 E3 轨迹仅保存逐候选总成本而未保存候选解及
成员账本，本文尚不能识别完全参与保障下的最低成本方案、公平代价或弱势成员收益改善，
相关数值须在保持原搜索语义的候选池持久化回放完成后报告。

## 完整性与保护边界

E3 哈希清单 {e3_verification['e3_manifest_file_count']}/
{e3_verification['e3_manifest_file_count']} 复核通过。受保护的 `cost.py`、
`check.py`、`search/evaluation.py`、`route_pool_sp.py` 和 `epochal_hgs.py`
均未修改且哈希未漂移。文件枚举排除 `._*`、`__pycache__`、`.pytest_cache`
和监控运行态；`done.json` 最后写入，作为本次 HALT 的原子完成信号。
"""


def write_artifact_hashes() -> dict[str, Any]:
    included = (
        "audit_e6_fairness.py",
        "monitor.json",
        "progress.log",
        "candidate_pool_audit.json",
        "member_ledger.csv",
        "instance_summary.csv",
        "raw_runs.csv",
        "metadata.json",
        "decision.json",
        "report.md",
    )
    files = {
        relative(HERE / name): sha256(HERE / name)
        for name in included
    }
    payload = {
        "schema": "resetp.e6-fairness.artifact-hashes.v1",
        "created_at_utc": now_iso(),
        "files": files,
        "exclusions": [
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
            "artifact_hashes.json (self-reference)",
            "done.json (written after the manifest as the completion signal)",
        ],
    }
    payload["manifest_id"] = canonical_sha256(payload)
    atomic_json(HERE / "artifact_hashes.json", payload)
    return payload


def main() -> int:
    if (HERE / "done.json").exists():
        raise RuntimeError(
            "done.json already exists; refusing to overwrite a terminal package"
        )
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "progress.log").write_text("", encoding="utf-8")
    log("START zero-search E6 I/U member-ledger audit")
    protected_start = verify_protected_hashes()
    e3_verification = verify_e3_manifest()
    log(
        "PREFLIGHT protected hashes PASS; "
        f"E3 manifest {e3_verification['e3_manifest_file_count']}/"
        f"{e3_verification['e3_manifest_file_count']} PASS"
    )
    candidate_audit = audit_candidate_persistence()
    atomic_json(HERE / "candidate_pool_audit.json", candidate_audit)
    log(
        "CANDIDATE_AUDIT nested candidate solutions not persisted; "
        "F selection unavailable"
    )
    runner, e3 = load_e3_modules()
    raw_rows, member_rows = collect_ledger(runner, e3)
    summaries, overall = aggregate(raw_rows)
    if overall["units_total"] != 20:
        raise RuntimeError(
            f"HALT_UNIT_DENOMINATOR:{overall['units_total']}!=20"
        )
    raw_fields = list(raw_rows[0])
    member_fields = list(member_rows[0])
    summary_fields = list(summaries[0])
    write_csv(HERE / "raw_runs.csv", raw_rows, raw_fields)
    write_csv(HERE / "member_ledger.csv", member_rows, member_fields)
    write_csv(
        HERE / "instance_summary.csv", summaries, summary_fields
    )
    created = now_iso()
    metadata = {
        "schema": "resetp.e6-fairness.metadata.v1",
        "task_id": TASK_ID,
        "created_at_utc": created,
        "status": STATUS,
        "contract": relative(CONTRACT),
        "e3_source_directory": relative(E3_ROOT),
        "instances": [item[0] for item in INSTANCES],
        "seeds": list(SEEDS),
        "states": ["I", "U", "F"],
        "state_definitions": {
            "I": "same-seed sealed E3 ZONE final solution",
            "U": "same-seed sealed E3 JOINT final solution",
            "F": (
                "minimum-system-cost theta=1 candidate among the same U "
                "run's fully checked nested candidates plus explicit I fallback"
            ),
        },
        "theta": THETA,
        "alpha_grid_used": False,
        "member_ledger_found": True,
        "member_ledger_source": relative(PROFIT_SOURCE),
        "member_ledger_source_sha256": sha256(PROFIT_SOURCE),
        "member_ledger_definition": (
            "revenue credited to serving route home depot; route, charging, "
            "occupancy, transship and proportional carbon costs allocated by "
            "the existing calculate_depot_profits ledger"
        ),
        "candidate_pool_persisted": False,
        "search_reruns": 0,
        "nested_candidates_counted_as_independent_samples": False,
        "raw_state_rows": len(raw_rows),
        "member_rows": len(member_rows),
        "seed_units": overall["units_total"],
        "protected_hashes_start": protected_start,
        "e3_verification": e3_verification,
        "file_enumeration_exclusions": [
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
        ],
    }
    decision = {
        "schema": "resetp.e6-fairness.decision.v1",
        "task_id": TASK_ID,
        "created_at_utc": created,
        "status": STATUS,
        "verdict": STATUS,
        "member_ledger_found": True,
        "units_naturally_pareto": overall["units_naturally_pareto"],
        "units_total": overall["units_total"],
        "natural_pareto_pct": overall["natural_pareto_pct"],
        "fairness_cost_pct": None,
        "f_weak_member_improvement": None,
        "search_reruns": 0,
        "i_u_accounting_complete": True,
        "f_selection_complete": False,
        "candidate_pool_persisted": False,
        "candidate_pool_reconstructible_from_current_trace": False,
        "explicit_i_fallback_available": True,
        "i_fallback_not_misreported_as_lowest_cost_f": True,
        "required_next_decision": (
            "user approval for a U-only deterministic replay that persists "
            "every fully checked candidate solution and its member ledger"
        ),
        "old_alpha_grid_numbers_used_as_current_evidence": False,
        "e3_tradeoff_preserved": {
            "cost_and_vehicle_direction": "decrease under JOINT",
            "distance_and_carbon_direction": "increase under JOINT",
        },
    }
    decision["decision_id"] = canonical_sha256(decision)
    atomic_json(HERE / "metadata.json", metadata)
    atomic_json(HERE / "decision.json", decision)
    (HERE / "report.md").write_text(
        build_report(
            summaries,
            overall,
            candidate_audit,
            e3_verification,
        ),
        encoding="utf-8",
    )
    protected_end = verify_protected_hashes()
    if protected_end != protected_start:
        raise RuntimeError("HALT_PROTECTED_HASH_DRIFT_DURING_AUDIT")
    log(
        f"RESULT natural_pareto="
        f"{overall['units_naturally_pareto']}/{overall['units_total']} "
        f"status={STATUS} search_reruns=0"
    )
    manifest = write_artifact_hashes()
    done = {
        "schema": "resetp.e6-fairness.done.v1",
        "task_id": TASK_ID,
        "created_at_utc": now_iso(),
        "status": STATUS,
        "member_ledger_found": True,
        "units_naturally_pareto": overall["units_naturally_pareto"],
        "units_total": overall["units_total"],
        "fairness_cost_pct": None,
        "search_reruns": 0,
        "candidate_pool_persisted": False,
        "f_state_computed": False,
        "artifact_manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
        "done_written_last": True,
    }
    done["done_id"] = canonical_sha256(done)
    atomic_json(HERE / "done.json", done)
    print(
        f"{now_iso()} DONE {STATUS} "
        f"natural={overall['units_naturally_pareto']}/"
        f"{overall['units_total']} search_reruns=0",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
