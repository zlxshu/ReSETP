#!/usr/bin/env python3
"""Controlled E3 warm-start experiment.

This is an additive runner.  It reads the sealed v11 M0 solutions and writes
to a new directory; it never edits the v11 directory or changes E2 paths.
Arm A and arm B share the exact same start, prices, fairness baseline, seed,
and evaluation budget.  Their only search-contract difference is whether a
customer may be inserted into the other depot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
from statistics import mean, median, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    run_tvci_carbon_schedule_pair,
)
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations

V11 = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
V11_FINAL = V11 / "final100"
DEFAULT_OUT = ROOT / "baselines/e3_ablation/e3_warmstart_controlled_20260713"
SIZE = "200c"
INSTANCE = "L-main-threeshift-200c-01"
BUNDLE = V11 / "assets/200c/derived_bundles/actual_gamma"
M0_SOLUTION_TEMPLATE = V11 / "solutions/E3__200c__M0__seed{seed}__fee0__eval4000__adopted.json"
M0_RUN_TEMPLATE = V11 / "runs/E3__200c__M0__seed{seed}__fee0__eval4000.json"
ARMS = ("A_no_cross", "B_cross")
SOURCE_PATHS = (
    "baselines/e3_ablation/e3_warmstart_controlled_20260713.py",
    "baselines/e3_ablation/e3_v3_runner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/operators/feasible_repair.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    "solver/src/setp_solver/search/multitrip_schedule.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def solution_from_file(path: Path):
    return legacy.solution_from_dict(read_json(path))


def owners_for_instance() -> dict[str, str]:
    return legacy.owner_map(INSTANCE)


def source_hashes() -> dict[str, str]:
    return {path: sha256(ROOT / path) for path in SOURCE_PATHS}


def m0_row(seed: int) -> dict[str, str]:
    with (V11_FINAL / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("run_id") == f"E3__200c__M0__seed{seed}__fee0__eval4000":
                return row
    raise ValueError(f"missing sealed v11 M0 row for seed {seed}")


def prices_m5() -> Any:
    return legacy.prices_for("M5", 0.0)


def common_start(seed: int):
    path = M0_SOLUTION_TEMPLATE.with_name(M0_SOLUTION_TEMPLATE.name.format(seed=seed))
    if not path.exists():
        raise FileNotFoundError(path)
    return path, solution_from_file(path)


def common_context(bundle: Any, owners: dict[str, str], prices: Any, *, allow_cross: bool, independent_profit: dict[str, float] | None = None) -> EvaluationContext:
    return EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=1.0,
        carbon_quota_kg=0.0,
        fairness_enabled=True,
        independent_profit=independent_profit,
        fairness_theta=1.0,
        customer_home_depot=owners,
        allow_cross_depot=allow_cross,
    )


def profit_values(solution: Any, bundle: Any, prices: Any, owners: dict[str, str]) -> dict[str, float]:
    rows = calculate_depot_profits(
        solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        customer_home_depot=owners,
        carbon_quota_kg=0.0,
    )
    return {depot: float(row.profit) for depot, row in rows.items()}


def task_spec(seed: int, arm: str, budget: int) -> dict[str, Any]:
    return {
        "run_id": f"E3_WARM__200c__{arm}__seed{seed}__fee0__eval{budget}",
        "instance": INSTANCE,
        "size": SIZE,
        "arm": arm,
        "seed": int(seed),
        "fee": 0.0,
        "budget": int(budget),
        "start_run_id": f"E3__200c__M0__seed{seed}__fee0__eval4000",
        "fairness_enabled": True,
        "fairness_theta": 1.0,
        "allow_cross_depot": arm == "B_cross",
        "contract_note": "A locks customers to frozen owners; B opens cross-depot moves; all other inputs are shared.",
    }


def task_fingerprint(spec: dict[str, Any], start_path: Path, hashes: dict[str, str]) -> str:
    payload = {
        "spec": spec,
        "source_hashes": hashes,
        "start_sha256": sha256(start_path),
        "v11_m0_run_sha256": sha256(M0_RUN_TEMPLATE.with_name(M0_RUN_TEMPLATE.name.format(seed=spec["seed"]))),
        "contract_sha256": sha256(legacy.CONTRACT_PATH),
        "owner_rows_sha256": sha256(legacy.OWNER_ROWS),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def nested_counts(value: Any, out: dict[str, int]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "score_counts" and isinstance(item, dict):
                for name, count in item.items():
                    if isinstance(count, (int, float)):
                        out[name] = out.get(name, 0) + int(count)
            nested_counts(item, out)
    elif isinstance(value, list):
        for item in value:
            nested_counts(item, out)


def score_counts(result: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    nested_counts(result.get("operator_counts", {}), counts)
    return counts


def run_one(spec: dict[str, Any], out: Path, hashes: dict[str, str]) -> dict[str, Any]:
    run_path = out / "runs" / f"{spec['run_id']}.json"
    start_path, start = common_start(int(spec["seed"]))
    fingerprint = task_fingerprint(spec, start_path, hashes)
    if run_path.exists():
        existing = read_json(run_path)
        if existing.get("task_fingerprint") == fingerprint and existing.get("status") == "OK":
            return existing
        raise RuntimeError(f"stale or failed row exists: {run_path}")

    row0 = m0_row(int(spec["seed"]))
    caps = json.loads(str(row0["depot_vehicle_counts_json"]))
    owners = owners_for_instance()
    prices = prices_m5()
    bundle = load_search_bundle(BUNDLE)
    independent_profit = profit_values(start, bundle, prices, owners)
    baseline_metrics = evaluate(start, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=0.0)
    allow_cross = bool(spec["allow_cross_depot"])
    policy = SearchPolicy(
        require_charging_signal=False,
        max_cv=14,
        max_ev=14,
        allow_cross_depot=allow_cross,
    )
    config = WinnerKernelConfig(
        seed=int(spec["seed"]),
        eval_budget=int(spec["budget"]),
        max_runtime_seconds=max(600.0, int(spec["budget"]) * 0.5),
        require_charging_signal=False,
    )
    started = __import__("time").perf_counter()
    with legacy.strict_mode(caps):
        result = run_tvci_carbon_schedule_pair(
            BUNDLE,
            config=config,
            initial_solution=start,
            prices=prices,
            policy=policy,
            carbon_weight=1.0,
            carbon_quota_kg=0.0,
            fairness_enabled=True,
            independent_profit=independent_profit,
            fairness_theta=1.0,
            customer_home_depot=owners,
        )
    search = legacy.annotate_cross_site(result["best_solution"], owners)
    context = common_context(bundle, owners, prices, allow_cross=allow_cross, independent_profit=independent_profit)
    with legacy.strict_mode(caps):
        prepared, certificate = prepare_solution(search, context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None:
        raise RuntimeError(f"{spec['run_id']} returned no strict certificate")
    metrics = evaluate(prepared, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=0.0)
    component_sum = sum(float(metrics[key]) for key in ("cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_occ", "cost_transship", "cost_carbon"))
    profits = profit_values(prepared, bundle, prices, owners)
    ratios = {depot: profits[depot] / value for depot, value in independent_profit.items() if abs(value) > 1e-12}
    counts = score_counts(result)
    run_elapsed = __import__("time").perf_counter() - started
    status = "OK" if bool(result.get("feasible")) and int(result.get("evaluations", -1)) == int(spec["budget"]) and not violations and abs(component_sum - float(metrics["total_cost"])) <= 1e-6 else "HALT_CONTRACT"
    reason = "" if status == "OK" else "; ".join(str(item) for item in violations) or "budget/feasibility/cost closure failed"
    row = {
        **spec,
        "status": status,
        "reason": reason,
        "actual_evals": int(result.get("evaluations", -1)),
        "elapsed_seconds": run_elapsed,
        "start_sha256": sha256(start_path),
        "task_fingerprint": fingerprint,
        "source_hashes_json": json.dumps(hashes, sort_keys=True),
        "contract_sha256": sha256(legacy.CONTRACT_PATH),
        "owner_rows_sha256": sha256(legacy.OWNER_ROWS),
        "battery_kwh": 280.0,
        "depot_charge_power_kw": 22.0,
        "common_start_total_cost": float(baseline_metrics["total_cost"]),
        "total_cost": float(metrics["total_cost"]),
        "cost_fix": float(metrics["cost_fix"]),
        "cost_km": float(metrics["cost_km"]),
        "cost_fuel": float(metrics["cost_fuel"]),
        "cost_elec": float(metrics["cost_elec"]),
        "cost_occ": float(metrics["cost_occ"]),
        "cost_transship": float(metrics["cost_transship"]),
        "cost_carbon": float(metrics["cost_carbon"]),
        "cost_component_error": abs(component_sum - float(metrics["total_cost"])),
        "cross_site_customer_count": len(prepared.cross_site_services),
        "cross_site_customer_ids_json": json.dumps(sorted(item.customer_id for item in prepared.cross_site_services)),
        "fairness_rejected_candidates": int(counts.get("strict_reject_profit_fairness", 0) + counts.get("strict_reject_fairness", 0)),
        "cross_site_attempted_candidates": int(counts.get("cross_site_complete_candidates", 0)),
        "cross_site_legal_candidates": int(counts.get("cross_site_legal_candidates", 0)),
        "cross_site_accepted_candidates": int(counts.get("cross_site_accepted_candidates", 0)),
        "profit_ratios_json": json.dumps(ratios, sort_keys=True),
        "min_profit_ratio": min(ratios.values(), default=""),
        "fairness_ok": all(float(value) >= 1.0 - 1e-9 for value in ratios.values()),
        "route_structure_signature": legacy.route_signature(prepared),
        "physical_cv": int(certificate.vehicle_counts["cv"]),
        "physical_ev": int(certificate.vehicle_counts["ev"]),
        "physical_total": int(certificate.vehicle_counts["cv"] + certificate.vehicle_counts["ev"]),
        "trip_count": len(certificate.trips),
        "depot_vehicle_counts_json": json.dumps(legacy._depot_counts(certificate), sort_keys=True),
        "operator_counts_json": json.dumps(result.get("operator_counts", {}), sort_keys=True),
        "history_rows": len(result.get("history", [])),
        "search_total_cost": float(metrics["total_cost"]),
    }
    write_json(out / "solutions" / f"{spec['run_id']}__search.json", legacy.solution_to_dict(prepared))
    write_json(out / "certificates" / f"{spec['run_id']}.json", certificate.as_dict())
    write_json(out / "history" / f"{spec['run_id']}.json", result.get("history", []))
    write_json(run_path, row)
    return row


def sign_test_p(differences: list[float]) -> float:
    positive = sum(value > 1e-9 for value in differences)
    n = sum(abs(value) > 1e-9 for value in differences)
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(positive, n + 1)) / (2 ** n)


def paired_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seed_values = sorted({int(row["seed"]) for row in rows})
    differences: list[float] = []
    strict_wins = 0
    fairness_all = True
    indexed = {(int(row["seed"]), str(row["arm"])): row for row in rows}
    for seed in seed_values:
        a = indexed[(seed, "A_no_cross")]
        b = indexed[(seed, "B_cross")]
        differences.append(float(a["total_cost"]) - float(b["total_cost"]))
        strict_wins += int(float(b["total_cost"]) < float(a["total_cost"]) - 1e-9 and int(b["cross_site_customer_count"]) > 0)
        fairness_all = fairness_all and bool(a["fairness_ok"]) and bool(b["fairness_ok"])
    wilcoxon_p: float | None = None
    try:
        from scipy.stats import wilcoxon

        wilcoxon_p = float(wilcoxon(differences, alternative="greater", method="exact").pvalue)
    except Exception:
        wilcoxon_p = None
    mean_saving = mean(differences) if differences else 0.0
    a_costs = [float(indexed[(seed, "A_no_cross")]["total_cost"]) for seed in seed_values]
    pct = [100.0 * diff / a_cost for diff, a_cost in zip(differences, a_costs)]
    strong = bool(strict_wins >= 7 and mean(pct) > 0.0 and median(pct) > 0.0 and wilcoxon_p is not None and wilcoxon_p < 0.05 and fairness_all)
    return {
        "paired_n": len(differences),
        "strict_wins": strict_wins,
        "mean_cost_difference_a_minus_b": mean_saving,
        "mean_saving_pct": mean(pct) if pct else 0.0,
        "median_saving_pct": median(pct) if pct else 0.0,
        "sd_saving_pct_population": pstdev(pct) if len(pct) > 1 else 0.0,
        "wilcoxon_one_sided_p": wilcoxon_p,
        "sign_test_one_sided_p": sign_test_p(differences),
        "fairness_all": fairness_all,
        "ideal_cost_gate": strong,
        "differences": differences,
        "saving_pct_by_seed": pct,
    }


def write_phase(out: Path, phase: str, rows: list[dict[str, Any]], specs: list[dict[str, Any]], hashes: dict[str, str]) -> dict[str, Any]:
    phase_dir = out / phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with (phase_dir / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with (phase_dir / "task_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(specs[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(specs)
    contract_ok = all(row["status"] == "OK" and int(row["actual_evals"]) == int(row["budget"]) and float(row["cost_component_error"]) <= 1e-6 for row in rows)
    summary = paired_summary(rows) if phase in {"gate", "formal"} and contract_ok else {}
    if phase == "preflight":
        verdict = "E3_WARM_PREFLIGHT_PASS" if contract_ok else "HALT_E3_WARM_PREFLIGHT"
        story = "短预检只证明能启动、能闭账，不对理想故事下结论。"
    elif phase == "gate":
        verdict = "E3_WARM_GATE_PASS" if contract_ok else "HALT_E3_WARM_GATE"
        story = "单种子完整预算门只判断正式合同和跨场动作是否能工作，不代表十种子统计结论。"
    else:
        verdict = "E3_WARM_FORMAL_PASS" if contract_ok else "HALT_E3_WARM_FORMAL"
        if not contract_ok:
            story = "正式对照合同未闭合，停止，不进入下一波。"
        elif summary.get("ideal_cost_gate"):
            story = "IDEAL_COST_SUPPORTED：在公平条件和同起点同预算下，跨场权利本身支持合作降本故事。"
        elif summary.get("mean_saving_pct", 0.0) > 0.0:
            story = "INTERMEDIATE：方向有利但未达到预注册理想门，不能写成稳定显著。"
        else:
            story = "NO_COST_RESCUE：受控暖启动没有恢复合作降本故事，转入历史归属错配敏感性检查前先审轨迹。"
    decision = {
        "schema": "setp.e3.warm.decision.v1",
        "phase": phase,
        "verdict": verdict,
        "row_count": len(rows),
        "ok_rows": sum(row["status"] == "OK" for row in rows),
        "contract_closed": contract_ok,
        "story_verdict": story,
        "summary": summary,
        "next_step": "单种子门通过后才允许跑十种子；十种子未过理想门则先审轨迹" if phase == "gate" else ("先审搜索轨迹；仅在证据支持时执行错配敏感性" if phase == "formal" and not summary.get("ideal_cost_gate") else "保留v11，写入受控暖启动论文口径；不自动替换E4/E6数据源"),
        "source_hashes": hashes,
    }
    metadata = {
        "schema": "setp.e3.warm.metadata.v1",
        "phase": phase,
        "v11_source": str(V11_FINAL.relative_to(ROOT)),
        "instance": INSTANCE,
        "bundle": str(BUNDLE.relative_to(ROOT)),
        "seeds": sorted({int(spec["seed"]) for spec in specs}),
        "arms": list(ARMS),
        "budget": int(specs[0]["budget"]),
        "contract": "same v11 M0 adopted start; same M5 prices; same theta=1 fairness; A owner-locked; B cross-depot enabled",
        "source_hashes": hashes,
    }
    write_json(phase_dir / "metadata.json", metadata)
    write_json(phase_dir / "decision.json", decision)
    lines = [
        f"# E3 暖启动受控对照：{phase}",
        "",
        f"判决：`{verdict}`。{story}",
        "",
        "这批运行只回答一个问题：从同一份独立方案继续搜索时，开放公平跨场动作有没有额外价值。它不替代 v11，也不证明普遍因果规律。",
        "",
        f"完成 {len(rows)} 行，合同通过 {decision['ok_rows']} 行。",
    ]
    if summary:
        lines.extend([
            "",
            f"严格胜出（B成本低于A且确实换场）：{summary['strict_wins']}/{summary['paired_n']}。",
            f"平均节省：{summary['mean_saving_pct']:.6f}%；中位数：{summary['median_saving_pct']:.6f}%。",
            f"单侧配对秩检验概率值：{summary['wilcoxon_one_sided_p'] if summary['wilcoxon_one_sided_p'] is not None else '未能计算'}；符号检验概率值：{summary['sign_test_one_sided_p']:.6f}。",
            "",
            "不能把同一批数据同时包装成从零搜索结论；v11 的 0.353% 仍是原始口径，本批是条件化的边际价值。",
        ])
    (phase_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths = [path for path in out.rglob("*") if path.is_file() and path.name != "artifact_hashes.json"]
    write_json(phase_dir / "artifact_hashes.json", {str(path.relative_to(out)): sha256(path) for path in sorted(paths)})
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("preflight", "gate", "formal"), required=True)
    parser.add_argument("--budget", type=int, default=0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = source_hashes()
    if args.phase == "preflight":
        seeds = [1]
        budget = int(args.budget) if args.budget > 0 else 200
    elif args.phase == "gate":
        seeds = [1]
        budget = int(args.budget) if args.budget > 0 else 4000
    else:
        seeds = list(range(1, 11))
        budget = int(args.budget) if args.budget > 0 else 4000
    specs = [task_spec(seed, arm, budget) for seed in seeds for arm in ARMS]
    write_json(out / f"{args.phase}_plan.json", {"phase": args.phase, "specs": specs, "source_hashes": hashes})
    rows = [run_one(spec, out, hashes) for spec in specs]
    decision = write_phase(out, args.phase, rows, specs, hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if str(decision["verdict"]).endswith("_PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
