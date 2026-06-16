"""Scale robustness runner for winner-kernel ALNS versus fair SA.

This module is intentionally isolated from the formal E1-E7 runners. It only
writes evidence under ``solver/reports/alns_scale_crush`` and reads generated
scale instances from ``models/data_bundle/generated_instances``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any

import numpy as np

from ..prices import DEFAULT_PRICES
from .alns_crush import INSTANCE_DIRS
from .alns_crush_v2 import (
    FAIR_SA_EVAL_BUDGET,
    FAIR_SA_MAX_RUNTIME_SECONDS,
    _fair_sa_reference,
    _parse_seed_list,
    _run_winner_rows,
    _summary_rows,
    _wilcoxon_vs_fair_sa,
    _write_csv,
    _write_json,
    run_task1,
)
from .bundle import load_search_bundle
from .winner_operators import operator_base_id, winner_operator_module


SCALE_CRUSH_DIR = Path("solver/reports/alns_scale_crush")
SCALE_INSTANCE_NAMES = ("Scale-150", "Scale-200")
SCALE_INSTANCE_DIRS = {name: INSTANCE_DIRS[name] for name in SCALE_INSTANCE_NAMES}
KNOWN_CONTEXT_ROWS = [
    {
        "instance": "100-01-24h",
        "known_status": "碾压",
        "known_evidence": "V2: winner kernel mean £4878 vs fair SA £5347, about 8.8% lower; 32 routes.",
        "constraint_note": "single 100-customer static instance, looser route-count headroom.",
    },
    {
        "instance": "L-main",
        "known_status": "持平",
        "known_evidence": "V2: winner kernel about £8351 vs fair SA about £8319; capacity lower bound 60, best near 64 routes.",
        "constraint_note": "three-shift 219-customer instance near capacity route-count lower bound.",
    },
]


def run_scale_crush(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    eval_budget: int = FAIR_SA_EVAL_BUDGET,
    max_runtime_seconds: float = FAIR_SA_MAX_RUNTIME_SECONDS,
    algorithm: str = "ALNS-Wouda",
    instance_dirs: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Run fair-SA and winner-kernel comparisons on generated scale instances."""

    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    selected_instances = instance_dirs or SCALE_INSTANCE_DIRS
    started = time.perf_counter()
    _write_preflight(root, out, selected_instances)
    instance_rows = [_instance_stats(root, name, rel_dir) for name, rel_dir in selected_instances.items()]
    _write_csv(out / "instance_stats.csv", instance_rows)

    fair_result = run_task1(
        root,
        out / "fair_sa",
        seeds=seeds,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        instance_dirs=selected_instances,
        include_sa_config_audit=False,
    )
    fair_reference = _load_json(out / "fair_sa" / "fair_sa_reference_costs.json")
    fair_rows = _read_csv(out / "fair_sa" / "fair_sa_10seed_cost_breakdown.csv")
    for row in fair_rows:
        row["variant"] = "fair_sa"
        row["operator_base_id"] = ""

    winner_rows = _run_winner_rows(
        root,
        seeds=seeds,
        eval_budget=eval_budget,
        max_runtime_seconds=max_runtime_seconds,
        algorithm=algorithm,
        include_route_elimination=False,
        variant="winner_kernel_only",
        out=out / "winner",
        instance_dirs=selected_instances,
    )
    for row in winner_rows:
        fair_mean = float(fair_reference["instances"][row["instance"]]["scikit-opt-SA"]["mean_total_cost"])
        row["gap_vs_fair_sa_mean_pct"] = (float(row["total_cost"]) - fair_mean) / fair_mean * 100.0

    combined_rows = [*_coerce_numeric_rows(fair_rows), *winner_rows]
    summary_rows = _summary_rows(combined_rows, variant="")
    wilcoxon_rows = _with_greater_wilcoxon(_wilcoxon_vs_fair_sa(winner_rows, fair_reference), winner_rows, fair_reference)
    verdict_rows = [
        scale_verdict_row(row, fair_reference, wilcoxon_rows)
        for row in summary_rows
        if str(row.get("variant")) == "winner_kernel_only"
    ]
    route_headroom_rows = _route_headroom_rows(summary_rows, instance_rows)
    reference = _reference_costs(fair_reference, winner_rows, summary_rows, eval_budget, max_runtime_seconds)

    _write_csv(out / "cost_breakdown.csv", combined_rows)
    _write_csv(out / "summary.csv", summary_rows)
    _write_csv(out / "wilcoxon_vs_fair_sa.csv", wilcoxon_rows)
    _write_csv(out / "route_headroom.csv", route_headroom_rows)
    _write_csv(out / "verdict.csv", verdict_rows)
    _write_json(out / "reference_costs.json", reference)
    (out / "final_report.md").write_text(
        _final_report(instance_rows, summary_rows, wilcoxon_rows, route_headroom_rows, verdict_rows),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "setp-alns-scale-crush.v1",
        "runner": "setp_solver.search.alns_scale_crush",
        "started_unix": started,
        "elapsed_seconds": time.perf_counter() - started,
        "instances": {name: str(path) for name, path in selected_instances.items()},
        "seeds": [int(seed) for seed in seeds],
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "fair_sa": fair_result,
        "winner_operator_module": winner_operator_module,
        "operator_base_id": operator_base_id,
        "semantic_guards": [
            "Does not modify cost.py/check.py/evaluation.py model semantics.",
            "Does not modify PRIMARY_ALGORITHM.",
            "Does not run formal E1-E7.",
            "Only winner_kernel_only is compared with fair scikit-opt-SA; no route-elimination, true-cost repair, RRT/AlphaUCB, or local-search add-ons are introduced.",
        ],
        "zero_violation_gate": all(int(row.get("violation_count", 0)) == 0 for row in combined_rows),
        "expected_row_count": len(selected_instances) * len(seeds) * 2,
        "actual_row_count": len(combined_rows),
        "outputs": [
            "instance_stats.csv",
            "cost_breakdown.csv",
            "summary.csv",
            "wilcoxon_vs_fair_sa.csv",
            "route_headroom.csv",
            "reference_costs.json",
            "final_report.md",
        ],
    }
    _write_json(out / "manifest.json", manifest)
    return {"gate": "ALNS_SCALE_CRUSH_COMPLETE", "manifest": str(out / "manifest.json"), "elapsed_seconds": manifest["elapsed_seconds"]}


def scale_verdict_row(
    summary_row: dict[str, Any],
    fair_reference: dict[str, Any],
    wilcoxon_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply the scale-crush verdict gate to one winner summary row."""

    instance_name = str(summary_row["instance"])
    fair = fair_reference["instances"][instance_name]["scikit-opt-SA"]
    p_row = next(
        row
        for row in wilcoxon_rows
        if row["instance"] == instance_name
        and row["variant"] == summary_row["variant"]
        and row["algorithm"] == summary_row["algorithm"]
    )
    fair_mean = float(fair["mean_total_cost"])
    winner_mean = float(summary_row["mean_total_cost"])
    fair_std = float(fair["std_total_cost"])
    winner_std = float(summary_row["std_total_cost"])
    diff_abs = winner_mean - fair_mean
    diff_pct = diff_abs / fair_mean * 100.0 if abs(fair_mean) > 1e-12 else math.nan
    wins = int(p_row["wins_alg_lower"])
    p_value = float(p_row["p_value_less"])
    p_value_greater = float(p_row.get("p_value_greater", math.nan))
    std_ok = winner_std <= 1.25 * fair_std
    if diff_pct < -1.0 and p_value < 0.05 and wins >= 8 and std_ok:
        verdict = "碾压"
        reason = "winner mean lower by >1pp, paired Wilcoxon significant, wins>=8/10, std gate passed"
    elif diff_pct > 1.0 and p_value_greater < 0.05:
        verdict = "失败"
        reason = "winner mean worse by >1pp and paired Wilcoxon greater-side test is significant"
    else:
        verdict = "持平"
        reason = "no significant >1pp winner advantage under the fixed fair-SA baseline"
    return {
        "instance": instance_name,
        "variant": summary_row["variant"],
        "algorithm": summary_row["algorithm"],
        "fair_sa_mean": fair_mean,
        "winner_mean": winner_mean,
        "diff_abs_winner_minus_fair_sa": diff_abs,
        "diff_pct_winner_minus_fair_sa": diff_pct,
        "winner_best": float(summary_row["best_total_cost"]),
        "fair_sa_best": float(fair["best_total_cost"]),
        "winner_std": winner_std,
        "fair_sa_std": fair_std,
        "winner_std_le_1p25_sa_std": std_ok,
        "wins_winner_lower": wins,
        "n_pairs": int(p_row["n_pairs"]),
        "p_value_less": p_value,
        "p_value_greater": p_value_greater,
        "verdict": verdict,
        "reason": reason,
    }


def _instance_stats(repo_root: Path, instance_name: str, rel_dir: Path) -> dict[str, Any]:
    bundle_dir = repo_root / rel_dir
    instance_json = _load_json(bundle_dir / "instance.json")
    manifest_path = bundle_dir / "three_shift_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else {}
    customers = [
        node
        for node in instance_json.get("nodes", [])
        if str(node.get("type", node.get("node_type", ""))).lower() == "c"
    ]
    demands = [float(node.get("demand", 0.0)) for node in customers]
    widths = [float(node.get("due_time", 0.0)) - float(node.get("ready_time", 0.0)) for node in customers]
    kept_by_shift = kept_count_by_shift(manifest)
    capacity = _price(DEFAULT_PRICES, "Q_capacity")
    ffd = first_fit_decreasing_bin_count(demands, capacity)
    return {
        "instance": instance_name,
        "bundle_dir": str(rel_dir),
        "scenario_id": instance_json.get("scenario_id"),
        "requested_customer_count": _target_from_name(instance_name),
        "actual_customer_count": len(customers),
        "kept_customer_count_manifest": int(manifest.get("kept_customer_count", len(customers))),
        "deleted_customer_count": int(manifest.get("deleted_customer_count", 0)),
        "kept_by_shift": json.dumps(kept_by_shift, ensure_ascii=False, sort_keys=True),
        "total_demand": sum(demands),
        "capacity_route_lower_bound": capacity_route_lower_bound(demands, capacity),
        "capacity_only_ffd_route_count": int(ffd["bin_count"]),
        "capacity_only_ffd_total_slack": float(ffd["total_slack"]),
        "time_window_width_min_seconds": min(widths) if widths else 0.0,
        "time_window_width_mean_seconds": statistics.fmean(widths) if widths else 0.0,
        "time_window_width_median_seconds": float(np.median(widths)) if widths else 0.0,
        "time_window_width_max_seconds": max(widths) if widths else 0.0,
        "three_shift_manifest": str(manifest_path),
        "dynamic_events_tsv_exists": (bundle_dir / "dynamic_events.tsv").exists(),
        "shift_structure": "0h/9h/18h, third-shift customers with shifted due_time > 86400s deleted",
    }


def kept_count_by_shift(manifest: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in manifest.get("kept_customers", []):
        key = str(int(float(row.get("shift_seconds", 0.0)) // (9.0 * 3600.0)))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def capacity_route_lower_bound(demands: list[float], capacity: float) -> int:
    if capacity <= 0:
        raise ValueError("capacity must be positive")
    return int(math.ceil(sum(max(0.0, float(value)) for value in demands) / float(capacity)))


def first_fit_decreasing_bin_count(demands: list[float], capacity: float) -> dict[str, Any]:
    if capacity <= 0:
        raise ValueError("capacity must be positive")
    loads: list[float] = []
    for demand in sorted((max(0.0, float(value)) for value in demands), reverse=True):
        chosen: int | None = None
        for idx, load in enumerate(loads):
            if load + demand <= capacity + 1e-9 and (chosen is None or load > loads[chosen]):
                chosen = idx
        if chosen is None:
            loads.append(demand)
        else:
            loads[chosen] += demand
    total = sum(max(0.0, float(value)) for value in demands)
    return {
        "bin_count": len(loads),
        "capacity": float(capacity),
        "total_demand": total,
        "total_slack": len(loads) * float(capacity) - total,
        "loads": loads,
    }


def _route_headroom_rows(summary_rows: list[dict[str, Any]], instance_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats = {row["instance"]: row for row in instance_rows}
    out: list[dict[str, Any]] = []
    for row in summary_rows:
        if row["instance"] not in stats:
            continue
        lb = float(stats[row["instance"]]["capacity_route_lower_bound"])
        ffd = float(stats[row["instance"]]["capacity_only_ffd_route_count"])
        mean_routes = float(row["mean_route_count"])
        out.append(
            {
                "instance": row["instance"],
                "variant": row["variant"],
                "algorithm": row["algorithm"],
                "mean_route_count": mean_routes,
                "median_route_count": row["median_route_count"],
                "capacity_route_lower_bound": lb,
                "capacity_only_ffd_route_count": ffd,
                "mean_routes_minus_capacity_lb": mean_routes - lb,
                "mean_routes_minus_ffd": mean_routes - ffd,
            }
        )
    return out


def _with_greater_wilcoxon(
    wilcoxon_rows: list[dict[str, Any]],
    winner_rows: list[dict[str, Any]],
    fair_reference: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in winner_rows:
        grouped.setdefault((str(row["variant"]), str(row["instance"]), str(row["algorithm"])), []).append(row)
    out: list[dict[str, Any]] = []
    for row in wilcoxon_rows:
        key = (str(row["variant"]), str(row["instance"]), str(row["algorithm"]))
        fair = fair_reference["instances"][row["instance"]]["scikit-opt-SA"]
        seed_costs = {str(seed): float(cost) for seed, cost in fair.get("seed_total_costs", {}).items()}
        diffs = [
            float(item["total_cost"]) - seed_costs[str(int(item["seed"]))]
            for item in sorted(grouped.get(key, []), key=lambda item: int(item["seed"]))
            if str(int(item["seed"])) in seed_costs
        ]
        p_value, method = _wilcoxon_greater(diffs)
        out.append({**row, "p_value_greater": p_value, "greater_method": method})
    return out


def _wilcoxon_greater(diffs: list[float]) -> tuple[float, str]:
    nonzero = [float(value) for value in diffs if abs(float(value)) > 1e-9]
    if not nonzero:
        return 1.0, "all_zero"
    try:
        from scipy.stats import wilcoxon

        result = wilcoxon(nonzero, alternative="greater", zero_method="wilcox", method="auto")
        return float(result.pvalue), "scipy_wilcoxon_greater"
    except Exception:
        losses = sum(1 for value in nonzero if value > 0.0)
        return sum(math.comb(len(nonzero), k) for k in range(losses, len(nonzero) + 1)) / (2 ** len(nonzero)), "fallback_sign_test_greater"


def _reference_costs(
    fair_reference: dict[str, Any],
    winner_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    winner_seed_costs: dict[str, dict[str, float]] = {}
    for row in winner_rows:
        winner_seed_costs.setdefault(str(row["instance"]), {})[str(int(row["seed"]))] = float(row["total_cost"])
    return {
        "schema_version": "setp-alns-scale-crush-reference-costs.v1",
        "baseline_algorithm": "scikit-opt-SA",
        "winner_variant": "winner_kernel_only",
        "operator_base_id": operator_base_id,
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "fair_sa_reference": fair_reference,
        "winner_kernel_seed_costs": winner_seed_costs,
        "summary": summary_rows,
    }


def _final_report(
    instance_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    wilcoxon_rows: list[dict[str, Any]],
    route_headroom_rows: list[dict[str, Any]],
    verdict_rows: list[dict[str, Any]],
) -> str:
    summary_lookup = {(row["instance"], row["variant"], row["algorithm"]): row for row in summary_rows}
    route_lookup = {(row["instance"], row["variant"], row["algorithm"]): row for row in route_headroom_rows}
    wilcox_lookup = {(row["instance"], row["variant"], row["algorithm"]): row for row in wilcoxon_rows}
    lines = [
        "# ALNS Scale Crush 150/200",
        "",
        "This report uses newly generated static three-shift 24h instances and compares winner_kernel_v1 against fair scikit-opt-SA with the same 16000-evaluation / 900-second口径.",
        "",
        "Honesty note: 150/200 follow the same tight three-shift construction as L-main, so持平 is expected if route-count headroom is physically thin. No parameter tuning, seed picking, route-elimination add-on, true-cost repair, RRT/AlphaUCB, or embedded LS is introduced in this scale run.",
        "",
        "## Generation",
    ]
    for row in instance_rows:
        lines.append(
            f"- {row['instance']}: customers={row['actual_customer_count']} requested={row['requested_customer_count']}, "
            f"demand={float(row['total_demand']):.3f}, capacity_lb={row['capacity_route_lower_bound']}, "
            f"FFD={row['capacity_only_ffd_route_count']}, kept_by_shift={row['kept_by_shift']}, "
            f"deleted={row['deleted_customer_count']}, dynamic_events_tsv_exists={row['dynamic_events_tsv_exists']}."
        )
    lines.extend(["", "## Scale Verdict"])
    for verdict in verdict_rows:
        fair = summary_lookup[(verdict["instance"], "fair_sa", "scikit-opt-SA")]
        winner = summary_lookup[(verdict["instance"], verdict["variant"], verdict["algorithm"])]
        route = route_lookup[(verdict["instance"], verdict["variant"], verdict["algorithm"])]
        wilcox = wilcox_lookup[(verdict["instance"], verdict["variant"], verdict["algorithm"])]
        lines.append(
            f"- {verdict['instance']}: {verdict['verdict']}; winner mean £{float(winner['mean_total_cost']):.3f} "
            f"vs fair SA £{float(fair['mean_total_cost']):.3f}, diff={float(verdict['diff_pct_winner_minus_fair_sa']):.3f}%, "
            f"best winner £{float(winner['best_total_cost']):.3f}, p_less={float(wilcox['p_value_less']):.6g}, "
            f"p_greater={float(wilcox['p_value_greater']):.6g}, wins={wilcox['wins_alg_lower']}/{wilcox['n_pairs']}, "
            f"routes={float(route['mean_route_count']):.2f} vs capacity_lb={route['capacity_route_lower_bound']}."
        )
    lines.extend(["", "## Context"])
    for row in KNOWN_CONTEXT_ROWS:
        lines.append(f"- {row['instance']}: {row['known_status']}; {row['known_evidence']} {row['constraint_note']}")
    lines.extend(
        [
            "",
            "Conclusion rule: 碾压 requires >1pp lower mean cost, paired Wilcoxon p_less<0.05, wins>=8/10, and winner std <= 1.25x SA std. 失败 is used when winner is >1pp worse and paired Wilcoxon p_greater<0.05. Otherwise the scale instance is marked 持平.",
        ]
    )
    return "\n".join(lines)


def _coerce_numeric_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if key in {"instance", "algorithm", "variant", "operator_base_id"}:
                converted[key] = value
                continue
            converted[key] = _maybe_number(value)
        out.append(converted)
    return out


def _maybe_number(value: Any) -> Any:
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if text == "":
        return text
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        number = float(text)
    except ValueError:
        return value
    if number.is_integer() and not any(char in text for char in ".eE"):
        return int(number)
    return number


def _write_preflight(repo_root: Path, out: Path, instance_dirs: dict[str, Path]) -> None:
    preflight = out / "preflight"
    preflight.mkdir(parents=True, exist_ok=True)
    commands = {
        "git_status": ["git", "status", "--short"],
        "protected_diff": [
            "git",
            "diff",
            "--name-only",
            "--",
            "solver/src/setp_solver/cost.py",
            "solver/src/setp_solver/check.py",
            "solver/src/setp_solver/search/evaluation.py",
        ],
        "primary_algorithm": ["rg", "-n", "PRIMARY_ALGORITHM", "solver/src", "solver/tests"],
    }
    for name, cmd in commands.items():
        proc = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True, check=False)
        (preflight / f"{name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (preflight / f"{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    _write_json(preflight / "scale_instance_dirs.json", {name: str(path) for name, path in instance_dirs.items()})


def _read_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def _target_from_name(instance_name: str) -> int | None:
    try:
        return int(str(instance_name).split("-")[-1])
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ALNS scale-crush 150/200 comparisons.")
    parser.add_argument("stage", choices=["run", "stats"], default="run")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[4]))
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[4] / SCALE_CRUSH_DIR))
    parser.add_argument("--seeds", default="1-10")
    parser.add_argument("--eval-budget", type=int, default=FAIR_SA_EVAL_BUDGET)
    parser.add_argument("--max-runtime-seconds", type=float, default=FAIR_SA_MAX_RUNTIME_SECONDS)
    parser.add_argument("--algorithm", default="ALNS-Wouda")
    args = parser.parse_args(argv)
    if args.stage == "stats":
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        rows = [_instance_stats(Path(args.repo_root), name, rel_dir) for name, rel_dir in SCALE_INSTANCE_DIRS.items()]
        _write_csv(out / "instance_stats.csv", rows)
        print(f"GATE ALNS_SCALE_STATS {json.dumps({'rows': len(rows), 'path': str(out / 'instance_stats.csv')}, ensure_ascii=False)}")
        return 0
    result = run_scale_crush(
        args.repo_root,
        args.output_dir,
        seeds=_parse_seed_list(args.seeds),
        eval_budget=args.eval_budget,
        max_runtime_seconds=args.max_runtime_seconds,
        algorithm=args.algorithm,
    )
    print(f"GATE ALNS_SCALE_CRUSH {result['gate']} {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
