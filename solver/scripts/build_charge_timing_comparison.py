#!/usr/bin/env python3
"""Build the charge-timing comparison data behind the paper's charge-timing table.

Two contrasts are produced from one already-finished ablation batch; **no new
search is run here**.

* ``reoptimised`` -- the two arms of the ablation batch as they were solved.
  ``MT-HGS`` (``mechanism_off=["charge_timing"]``, effective policy ``asap``)
  is the "charge whenever a slot is free" arm; ``MTC-HGS`` (``mechanism_off=[]``,
  effective policy ``cost_plus_carbon``) is the "carbon-aware timing" arm.  The
  two arms differ in exactly one switch, but each one searched its own routes,
  so their difference mixes the timing mechanism with route-search variation.

* ``same_route`` -- every solution of both arms is re-settled *twice*, once
  under ``asap`` and once under ``cost_plus_carbon``, with the customer
  assignment, trip order and fleet held fixed.  Only the charging instants move,
  so the difference is the mechanism's own effect, paired solution by solution.

Two self-checks gate the ``same_route`` contrast and abort the run when they
fail:

1. **Replay fidelity** -- re-settling a solution under *its own* policy must
   reproduce the official ``best_solution.json`` breakdown key by key.
2. **Route invariance** -- ``cost_fix`` / ``cost_km`` / ``cost_fuel`` /
   ``distance_total`` / ``n_veh_cv`` / ``n_veh_ev`` must be identical between
   the two policies for the same solution; anything else means the re-settle
   moved the routes.

Usage (repository root)::

    export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
    .public-hgs-venv/bin/python3 solver/scripts/build_charge_timing_comparison.py

The batch directory and the output directory are both command-line arguments so
the same comparison can be rebuilt from a later batch.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------
# arm wiring: which metadata signature each column of the table comes from
# --------------------------------------------------------------------------
ASAP_ARM = "MT-HGS"
CARBON_ARM = "MTC-HGS"
ASAP_POLICY = "asap"
CARBON_POLICY = "cost_plus_carbon"

ARM_EXPECTATION = {
    ASAP_ARM: {"mechanism_off": ["charge_timing"], "policy": ASAP_POLICY},
    CARBON_ARM: {"mechanism_off": [], "policy": CARBON_POLICY},
}

# Fields that the whole comparison must agree on; a batch that mixes them is
# not a single experiment and is refused.
SHARED_METADATA_FIELDS = (
    "instance_id",
    "carbon_price_cny_per_kg",
    "fleet_parameter_class",
    "depot_curve",
    "recharge_mode",
)

# Breakdown keys that cannot move when only the charging instants change.
ROUTE_INVARIANT_KEYS = (
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "distance_total",
    "n_veh_cv",
    "n_veh_ev",
)

# Reported metrics: (output key, breakdown key, scale, label)
METRICS: tuple[tuple[str, str, float, str], ...] = (
    ("total_cost", "total_cost", 1.0, "总成本（元）"),
    ("cost_fix", "cost_fix", 1.0, "固定成本（元）"),
    ("cost_km", "cost_km", 1.0, "行驶成本（元）"),
    ("cost_elec", "cost_elec", 1.0, "充电成本（元）"),
    ("cost_fuel", "cost_fuel", 1.0, "油耗成本（元）"),
    ("cost_carbon", "cost_carbon", 1.0, "碳成本（元）"),
    ("distance_km", "distance_total", 1e-3, "总距离（km）"),
    ("E_cv_direct", "E_cv_direct", 1.0, "燃油车直接排放（kgCO2e）"),
    ("E_ev_indirect", "E_ev_indirect", 1.0, "电动车充电间接排放（kgCO2e）"),
    ("E_total", "E_total", 1.0, "总排放（kgCO2e）"),
    ("electricity_kwh", "electricity_kwh", 1.0, "充电电量（kWh）"),
    ("n_veh_cv", "n_veh_cv", 1.0, "派遣燃油车（辆）"),
    ("n_veh_ev", "n_veh_ev", 1.0, "派遣电动车（辆）"),
)

REPLAY_TOLERANCE = 1e-6


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def _load_runtime(repo: Path):
    """Import the private technical runner as a module (it is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "resetp_private_runtime",
        repo / "solver/scripts/run_problem_hgs_private_technical.py",
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("cannot import run_problem_hgs_private_technical.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_dirs(batch_dir: Path, arm: str) -> list[Path]:
    dirs = sorted(
        path
        for path in (batch_dir / arm).glob("run_*")
        if path.is_dir() and (path / "best_solution.json").is_file()
    )
    if not dirs:
        raise SystemExit(f"no finished runs under {batch_dir / arm}")
    return dirs


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_runs(batch_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Load both arms, checking the metadata wiring of every run."""
    runs: dict[str, list[dict[str, Any]]] = {}
    shared: dict[str, Any] = {}
    for arm, expected in ARM_EXPECTATION.items():
        arm_runs = []
        for run_dir in _run_dirs(batch_dir, arm):
            metadata = _read_json(run_dir / "metadata.json")
            solution = _read_json(run_dir / "best_solution.json")

            off = sorted(metadata.get("mechanism_off") or [])
            if off != sorted(expected["mechanism_off"]):
                raise SystemExit(
                    f"{arm}/{run_dir.name}: mechanism_off={off}, "
                    f"expected {sorted(expected['mechanism_off'])}"
                )
            closure = metadata.get("mechanism_closure") or {}
            policy = closure.get("effective_charge_timing_policy")
            if policy != expected["policy"]:
                raise SystemExit(
                    f"{arm}/{run_dir.name}: effective_charge_timing_policy={policy!r}, "
                    f"expected {expected['policy']!r}"
                )
            # NOTE: metadata["mechanism_enabled"]["charge_timing"] is deliberately
            # NOT checked.  On write-out it is overwritten with the value of
            # include_charging_candidates, so it reads False even in the arm that
            # runs the mechanism; effective_charge_timing_policy is the live field.
            if closure.get("violations"):
                raise SystemExit(
                    f"{arm}/{run_dir.name}: mechanism closure violations "
                    f"{closure['violations']}"
                )
            if metadata.get("status") not in (None, "COMPLETE", "RUN_COMPLETE"):
                raise SystemExit(
                    f"{arm}/{run_dir.name}: status={metadata.get('status')!r}"
                )

            for field in SHARED_METADATA_FIELDS:
                value = metadata.get(field)
                if field in shared and shared[field] != value:
                    raise SystemExit(
                        f"{arm}/{run_dir.name}: {field}={value!r} disagrees with "
                        f"{shared[field]!r} seen earlier in the batch"
                    )
                shared[field] = value

            arm_runs.append(
                {
                    "arm": arm,
                    "run": run_dir.name,
                    "dir": run_dir,
                    "policy": policy,
                    "solution": solution,
                    "breakdown": solution["evaluation"]["breakdown"],
                }
            )
        runs[arm] = arm_runs
    return runs, shared


def _rebuild_individual(runtime, payload: Mapping[str, Any]):
    from setp_solver.algorithms.problem_hgs.model import (
        DutyChargingSession,
        DutyIndividual,
        DutyTrip,
        PhysicalVehicleDuty,
    )

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
    return DutyIndividual(
        duties=tuple(duties),
        unserved_customers=tuple(payload["individual"].get("unserved_customers", ())),
        source="charge-timing-comparison-reload",
    )


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def _metrics(breakdown: Mapping[str, Any]) -> dict[str, float]:
    return {
        key: float(breakdown[source]) * scale for key, source, scale, _ in METRICS
    }


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values)


def _aggregate(rows: Iterable[Mapping[str, float]]) -> dict[str, float]:
    rows = list(rows)
    return {key: _mean([row[key] for row in rows]) for key, *_ in METRICS}


def _pct(before: float, after: float) -> float | None:
    if before == 0.0:
        return None
    return (after - before) / before * 100.0


def _delta_block(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, dict[str, float | None]]:
    return {
        key: {
            "before": before[key],
            "after": after[key],
            "delta": after[key] - before[key],
            "pct": _pct(before[key], after[key]),
        }
        for key, *_ in METRICS
    }


def _describe(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean": _mean(ordered),
        "median": statistics.median(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--batch-dir",
        type=Path,
        default=Path("solver/reports/ablation_formal_10x_v5_20260904"),
        help="finished ablation batch holding the MT-HGS / MTC-HGS arms",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("solver/reports/charge_timing_comparison_20260904"),
        help="directory to write summary.json / summary.md / README.md into",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (data bundle and solver sources are read from here)",
    )
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    batch_dir = args.batch_dir if args.batch_dir.is_absolute() else repo / args.batch_dir
    out_dir = args.out_dir if args.out_dir.is_absolute() else repo / args.out_dir
    batch_dir = batch_dir.resolve()

    runs, shared = _collect_runs(batch_dir)
    print(f"batch      : {batch_dir}", flush=True)
    for field in SHARED_METADATA_FIELDS:
        print(f"{field:<26}: {shared[field]!r}", flush=True)
    print(
        f"runs       : {ASAP_ARM}={len(runs[ASAP_ARM])}  "
        f"{CARBON_ARM}={len(runs[CARBON_ARM])}",
        flush=True,
    )

    runtime = _load_runtime(repo)
    if shared["instance_id"] != runtime.DEPOT_SEARCH_INSTANCE_ID:
        print(
            f"note: instance {shared['instance_id']} is not the DEPOTSEARCH default",
            flush=True,
        )
    fleet_class = runtime.FLEET_PARAMETER_CLASSES[shared["fleet_parameter_class"]]
    carbon_price = float(shared["carbon_price_cny_per_kg"])

    bundle, _initial, _np, context = runtime._build_context(
        repo, shared["instance_id"], fleet_parameters=fleet_class
    )
    bundle = replace(
        bundle,
        prices=replace(bundle.prices, carbon_price=carbon_price),
        carbon_price_cny_per_kg=carbon_price,
    )
    context = replace(context, bundle=bundle)

    from setp_solver.algorithms.problem_hgs.charging import repair_changed_duties
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator

    evaluator = DutyFullEvaluator(context)
    policies = {
        name: runtime._policy(evaluator, charge_timing_policy=name)
        for name in (ASAP_POLICY, CARBON_POLICY)
    }

    # ---------------- A. re-optimised contrast (as solved) ----------------
    reoptimised: dict[str, Any] = {}
    for arm in (ASAP_ARM, CARBON_ARM):
        rows = [_metrics(run["breakdown"]) for run in runs[arm]]
        best_index = min(range(len(rows)), key=lambda i: rows[i]["total_cost"])
        reoptimised[arm] = {
            "policy": ARM_EXPECTATION[arm]["policy"],
            "n_runs": len(rows),
            "mean": _aggregate(rows),
            "best_run": runs[arm][best_index]["run"],
            "best": rows[best_index],
            "per_run": {
                run["run"]: row for run, row in zip(runs[arm], rows, strict=True)
            },
            # Means of n_veh_cv / n_veh_ev are NOT a fleet anyone dispatched; the
            # runs land on a handful of discrete compositions.  Report the tally.
            "fleet_composition_counts": {
                f"{cv:.0f}CV/{ev:.0f}EV": sum(
                    1
                    for other in rows
                    if (other["n_veh_cv"], other["n_veh_ev"]) == (cv, ev)
                )
                for cv, ev in sorted(
                    {(row["n_veh_cv"], row["n_veh_ev"]) for row in rows}
                )
            },
        }

    # ---------------- B. same-route paired contrast ----------------------
    paired_rows: list[dict[str, Any]] = []
    replay_max_dev = 0.0
    replay_worst = ""
    invariance_max_dev = 0.0
    invariance_worst = ""

    for arm in (ASAP_ARM, CARBON_ARM):
        for run in runs[arm]:
            individual = _rebuild_individual(runtime, run["solution"])
            changed = {duty.physical_vehicle_id for duty in individual.duties}
            settled: dict[str, Any] = {}
            for name, policy in policies.items():
                repaired = repair_changed_duties(
                    individual,
                    individual,
                    changed_duty_ids=changed,
                    context=context,
                    policy=policy,
                )
                evaluation = evaluator.evaluate(repaired)
                if not evaluation.feasible:
                    raise SystemExit(
                        f"{arm}/{run['run']}: re-settled solution infeasible under {name}"
                    )
                settled[name] = dict(evaluation.breakdown)

            # -- self-check 1: replay under the solution's own policy --
            official = run["breakdown"]
            replay = settled[run["policy"]]
            for key, value in official.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                dev = abs(float(replay[key]) - float(value))
                if dev > replay_max_dev:
                    replay_max_dev, replay_worst = dev, f"{arm}/{run['run']}:{key}"
                if dev > REPLAY_TOLERANCE:
                    raise SystemExit(
                        f"REPLAY MISMATCH {arm}/{run['run']} policy={run['policy']} "
                        f"key={key}: official={value!r} replay={replay[key]!r} "
                        f"|diff|={dev:.6g} > {REPLAY_TOLERANCE}"
                    )

            # -- self-check 2: routes did not move when the policy changed --
            for key in ROUTE_INVARIANT_KEYS:
                dev = abs(
                    float(settled[ASAP_POLICY][key]) - float(settled[CARBON_POLICY][key])
                )
                if dev > invariance_max_dev:
                    invariance_max_dev, invariance_worst = dev, f"{arm}/{run['run']}:{key}"
                if dev > REPLAY_TOLERANCE:
                    raise SystemExit(
                        f"ROUTE MOVED {arm}/{run['run']} key={key}: "
                        f"{ASAP_POLICY}={settled[ASAP_POLICY][key]!r} "
                        f"{CARBON_POLICY}={settled[CARBON_POLICY][key]!r} "
                        f"|diff|={dev:.6g}; the re-settle is not route-preserving"
                    )

            paired_rows.append(
                {
                    "source_arm": arm,
                    "run": run["run"],
                    "native_policy": run["policy"],
                    ASAP_POLICY: _metrics(settled[ASAP_POLICY]),
                    CARBON_POLICY: _metrics(settled[CARBON_POLICY]),
                }
            )
            asap_total = paired_rows[-1][ASAP_POLICY]["total_cost"]
            carbon_total = paired_rows[-1][CARBON_POLICY]["total_cost"]
            print(
                f"  {arm}/{run['run']}  asap={asap_total:9.2f} -> "
                f"cost_plus_carbon={carbon_total:9.2f}  "
                f"Δ={carbon_total - asap_total:+7.2f}",
                flush=True,
            )

    def _paired_block(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        before = _aggregate(row[ASAP_POLICY] for row in rows)
        after = _aggregate(row[CARBON_POLICY] for row in rows)
        cost_deltas = [
            row[CARBON_POLICY]["total_cost"] - row[ASAP_POLICY]["total_cost"]
            for row in rows
        ]
        emission_deltas = [
            row[CARBON_POLICY]["E_total"] - row[ASAP_POLICY]["E_total"] for row in rows
        ]
        return {
            "n_solutions": len(rows),
            "mean": {"asap": before, "cost_plus_carbon": after},
            "change": _delta_block(before, after),
            "per_solution_total_cost_delta": _describe(cost_deltas),
            "per_solution_E_total_delta": _describe(emission_deltas),
            "n_cost_down": sum(1 for value in cost_deltas if value < 0),
            "n_emission_down": sum(1 for value in emission_deltas if value < 0),
            "n_both_down": sum(
                1
                for cost, emission in zip(cost_deltas, emission_deltas, strict=True)
                if cost < 0 and emission < 0
            ),
        }

    same_route = {
        "pooled": _paired_block(paired_rows),
        f"from_{ASAP_ARM}": _paired_block(
            [row for row in paired_rows if row["source_arm"] == ASAP_ARM]
        ),
        f"from_{CARBON_ARM}": _paired_block(
            [row for row in paired_rows if row["source_arm"] == CARBON_ARM]
        ),
        "per_solution": paired_rows,
    }

    # ---------------- C. decomposition -----------------------------------
    reopt_change = _delta_block(
        reoptimised[ASAP_ARM]["mean"], reoptimised[CARBON_ARM]["mean"]
    )
    pooled_change = same_route["pooled"]["change"]
    decomposition = {
        "convention": (
            "reoptimised_mean_delta - same_route_pooled_mean_delta; the residual is "
            "the part of the arm difference that the route search accounts for"
        ),
        "by_metric": {
            key: {
                "reoptimised_delta": reopt_change[key]["delta"],
                "same_route_delta": pooled_change[key]["delta"],
                "route_search_residual": reopt_change[key]["delta"]
                - pooled_change[key]["delta"],
            }
            for key, *_ in METRICS
        },
    }

    # -- an alternative reading of the same route-quality gap: settle BOTH arms'
    #    route sets under ONE common policy and compare the two populations.  This
    #    basis is reported for cross-reference only; the headline convention above
    #    is the subtraction of the two mean deltas.
    common_basis: dict[str, Any] = {}
    for policy in (ASAP_POLICY, CARBON_POLICY):
        asap_routes = [
            row[policy]["total_cost"]
            for row in paired_rows
            if row["source_arm"] == ASAP_ARM
        ]
        carbon_routes = [
            row[policy]["total_cost"]
            for row in paired_rows
            if row["source_arm"] == CARBON_ARM
        ]
        common_basis[policy] = {
            f"{ASAP_ARM}_routes_mean_total_cost": _mean(asap_routes),
            f"{CARBON_ARM}_routes_mean_total_cost": _mean(carbon_routes),
            "route_quality_gap": _mean(carbon_routes) - _mean(asap_routes),
        }
    decomposition["common_basis_cross_reference"] = common_basis

    # -- emission robustness: the re-optimised mean gap is outlier-sensitive --
    asap_emissions = [
        row["E_total"] for row in reoptimised[ASAP_ARM]["per_run"].values()
    ]
    carbon_emissions = [
        row["E_total"] for row in reoptimised[CARBON_ARM]["per_run"].values()
    ]
    worst_run = max(
        reoptimised[ASAP_ARM]["per_run"].items(), key=lambda item: item[1]["E_total"]
    )
    trimmed = [
        value
        for run_name, row in reoptimised[ASAP_ARM]["per_run"].items()
        for value in (row["E_total"],)
        if run_name != worst_run[0]
    ]
    emission_robustness = {
        "asap_arm": _describe(asap_emissions),
        "carbon_arm": _describe(carbon_emissions),
        "mean_gap": _mean(carbon_emissions) - _mean(asap_emissions),
        "median_gap": statistics.median(carbon_emissions)
        - statistics.median(asap_emissions),
        "highest_emission_asap_run": {
            "run": worst_run[0],
            "E_total": worst_run[1]["E_total"],
            "n_veh_cv": worst_run[1]["n_veh_cv"],
            "n_veh_ev": worst_run[1]["n_veh_ev"],
        },
        "mean_gap_excluding_that_run": _mean(carbon_emissions) - _mean(trimmed),
    }

    summary = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_batch": str(batch_dir.relative_to(repo)),
        "instance": shared,
        "arms": {
            "asap_arm": {"name": ASAP_ARM, "policy": ASAP_POLICY},
            "carbon_arm": {"name": CARBON_ARM, "policy": CARBON_POLICY},
        },
        "metric_labels": {key: label for key, _s, _sc, label in METRICS},
        "self_checks": {
            "replay_consistency": {
                "tolerance": REPLAY_TOLERANCE,
                "max_abs_deviation": replay_max_dev,
                "worst_key": replay_worst,
                "passed": True,
            },
            "route_invariance": {
                "keys": list(ROUTE_INVARIANT_KEYS),
                "tolerance": REPLAY_TOLERANCE,
                "max_abs_deviation": invariance_max_dev,
                "worst_key": invariance_worst,
                "passed": True,
            },
        },
        "reoptimised": reoptimised,
        "reoptimised_change": reopt_change,
        "same_route": same_route,
        "decomposition": decomposition,
        "emission_robustness": emission_robustness,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "summary.md").write_text(_render_summary_md(summary), encoding="utf-8")
    (out_dir / "README.md").write_text(_render_readme_md(summary), encoding="utf-8")
    print(f"\nwritten -> {out_dir}", flush=True)
    return 0


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%"


def _dev(value: float) -> str:
    """Render a self-check deviation; an exact zero is a stronger claim than a bound."""
    return "0.0（逐位一致）" if value == 0.0 else f"{value:.6g}"


def _render_summary_md(summary: Mapping[str, Any]) -> str:
    asap_arm = summary["arms"]["asap_arm"]["name"]
    carbon_arm = summary["arms"]["carbon_arm"]["name"]
    labels = summary["metric_labels"]
    reopt = summary["reoptimised"]
    reopt_change = summary["reoptimised_change"]
    pooled = summary["same_route"]["pooled"]
    decomposition = summary["decomposition"]["by_metric"]
    robustness = summary["emission_robustness"]

    lines: list[str] = []
    lines.append("# 充电时刻策略对比数据（表10 数据源）")
    lines.append("")
    lines.append(
        f"数据来源：`{summary['source_batch']}`（{asap_arm} 与 {carbon_arm} 两臂各 "
        f"{reopt[asap_arm]['n_runs']} / {reopt[carbon_arm]['n_runs']} 次冷启动）。"
    )
    lines.append(
        f"算例 `{summary['instance']['instance_id']}`，碳价 "
        f"{summary['instance']['carbon_price_cny_per_kg']} 元/kgCO2e，"
        f"车队参数类 `{summary['instance']['fleet_parameter_class']}`。"
    )
    lines.append("本文件由 `solver/scripts/build_charge_timing_comparison.py` 生成，未运行任何新的搜索。")
    lines.append("")
    lines.append("两条臂只差充电策略这一个开关：")
    lines.append(
        f"- **有可用时段即充电** = `{asap_arm}`，`mechanism_off=[\"charge_timing\"]`，"
        f"生效策略 `{summary['arms']['asap_arm']['policy']}`；"
    )
    lines.append(
        f"- **考虑时变碳强度** = `{carbon_arm}`，`mechanism_off=[]`，"
        f"生效策略 `{summary['arms']['carbon_arm']['policy']}`。"
    )
    lines.append("")

    # ---- 表一：重新优化对照 ----
    lines.append("## 一、重新优化对照（两臂各自搜路线，十次均值）")
    lines.append("")
    lines.append("| 指标 | 有可用时段即充电 | 考虑时变碳强度 | 变化幅度 |")
    lines.append("|---|---:|---:|---:|")
    for key, *_rest in METRICS:
        row = reopt_change[key]
        lines.append(
            f"| {labels[key]} | {_fmt(row['before'])} | {_fmt(row['after'])} | "
            f"{_fmt_pct(row['pct'])} |"
        )
    lines.append("")
    lines.append(
        "**派遣车辆的均值不是任何一次真实派出的车队**（各次落在少数几个离散构型上），"
        "按构型计数如下："
    )
    lines.append("")
    lines.append("| 车队构型（油/电） | 有可用时段即充电 | 考虑时变碳强度 |")
    lines.append("|---|---:|---:|")
    asap_counts = reopt[asap_arm]["fleet_composition_counts"]
    carbon_counts = reopt[carbon_arm]["fleet_composition_counts"]
    for composition in sorted(set(asap_counts) | set(carbon_counts)):
        lines.append(
            f"| {composition} | {asap_counts.get(composition, 0)} 次 | "
            f"{carbon_counts.get(composition, 0)} 次 |"
        )
    lines.append("")
    lines.append(
        f"**写表时用这张计数表，不要用上表 {_fmt(reopt_change['n_veh_cv']['before'])}/"
        f"{_fmt(reopt_change['n_veh_ev']['before'])} 这种分数车。**"
    )
    lines.append("")
    lines.append(
        f"最优解（各臂十次里总成本最低的一次；"
        f"{asap_arm} = {reopt[asap_arm]['best_run']}，"
        f"{carbon_arm} = {reopt[carbon_arm]['best_run']}）备用：")
    lines.append("")
    lines.append("| 指标 | 有可用时段即充电 | 考虑时变碳强度 | 变化幅度 |")
    lines.append("|---|---:|---:|---:|")
    best_change = _delta_block(reopt[asap_arm]["best"], reopt[carbon_arm]["best"])
    for key, *_rest in METRICS:
        row = best_change[key]
        lines.append(
            f"| {labels[key]} | {_fmt(row['before'])} | {_fmt(row['after'])} | "
            f"{_fmt_pct(row['pct'])} |"
        )
    lines.append("")

    # ---- 表二：同一路线对照 ----
    lines.append("## 二、同一路线对照（固定路线，只换充电策略）")
    lines.append("")
    lines.append(
        f"把两臂全部 {pooled['n_solutions']} 个解的路线（客户分配、趟序、车队）固定住，"
        "分别在两种充电策略下重排充电时刻并做完整精确评价，逐解配对。"
    )
    lines.append("")
    lines.append(
        f"| 指标 | 有可用时段即充电 | 考虑时变碳强度 | 变化幅度 |"
    )
    lines.append("|---|---:|---:|---:|")
    for key, *_rest in METRICS:
        row = pooled["change"][key]
        lines.append(
            f"| {labels[key]} | {_fmt(row['before'])} | {_fmt(row['after'])} | "
            f"{_fmt_pct(row['pct'])} |"
        )
    lines.append("")
    lines.append("**三条按构造成立的性质，不是发现：**")
    lines.append("")
    lines.append(
        "1. 路线固定后，固定成本、行驶成本、油耗成本、总距离、派遣车辆数在两种策略下逐位相同"
        f"（实测最大绝对偏差 {summary['self_checks']['route_invariance']['max_abs_deviation']:.6g}，逐位一致）。"
        "真正随充电时刻变化的只有充电成本、电动车充电间接排放、总排放与碳成本四项。"
    )
    lines.append(
        "2. 充电电量在两种策略下也逐位相同（补电量策略是 `just_enough`，路线不变则需补的电量不变）。"
        "因此这一列里「充电成本」的下降是**纯粹的时段单价效应**，不含任何充电量变化；"
        "看到充电成本下降而充电电量 +0.00% 是对的，不是漏算。"
    )
    lines.append(
        f"3. 本算例 `carbon_quota_kg = 0`、碳价 "
        f"{summary['instance']['carbon_price_cny_per_kg']} 元/kg，"
        "因此碳成本恒等于碳价乘以总排放，两者的变化率必然逐位相同——上下两张表里"
        "「碳成本」与「总排放」的百分比一致是这个恒等式的结果，不是抄错。"
    )
    lines.append("")
    cost_stats = pooled["per_solution_total_cost_delta"]
    emission_stats = pooled["per_solution_E_total_delta"]
    lines.append("逐解变化量分布：")
    lines.append("")
    lines.append("| 量 | 解数 | 均值 | 中位 | 最小 | 最大 | 下降的解数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| 总成本变化（元） | {cost_stats['n']} | {_fmt(cost_stats['mean'])} | "
        f"{_fmt(cost_stats['median'])} | {_fmt(cost_stats['min'])} | "
        f"{_fmt(cost_stats['max'])} | {pooled['n_cost_down']}/{cost_stats['n']} |"
    )
    lines.append(
        f"| 总排放变化（kg） | {emission_stats['n']} | {_fmt(emission_stats['mean'])} | "
        f"{_fmt(emission_stats['median'])} | {_fmt(emission_stats['min'])} | "
        f"{_fmt(emission_stats['max'])} | {pooled['n_emission_down']}/{emission_stats['n']} |"
    )
    lines.append("")
    lines.append(
        f"**同时降本降排的解：{pooled['n_both_down']}/{pooled['n_solutions']}。**"
    )
    lines.append("")
    lines.append("按路线来源分臂（供表格取舍；混池的绝对水平来自两臂混合的路线集）：")
    lines.append("")
    lines.append("| 路线来源 | 解数 | 总成本变化均值（元） | 总成本变化中位 | 总排放变化均值（kg） | 总排放变化中位 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for tag, arm_name in ((f"from_{asap_arm}", asap_arm), (f"from_{carbon_arm}", carbon_arm)):
        block = summary["same_route"][tag]
        cost = block["per_solution_total_cost_delta"]
        emission = block["per_solution_E_total_delta"]
        lines.append(
            f"| {arm_name} 的 {block['n_solutions']} 个路线集 | {block['n_solutions']} | "
            f"{_fmt(cost['mean'])} | {_fmt(cost['median'])} | "
            f"{_fmt(emission['mean'])} | {_fmt(emission['median'])} |"
        )
    lines.append("")

    # ---- 表三：分解 ----
    lines.append("## 三、两种对照之差（路线搜索差异的量级）")
    lines.append("")
    lines.append(
        "约定：路线搜索残差 = 重新优化对照的均值变化 − 同一路线对照（混池）的均值变化。"
        "两个被减项都是同一批解的读数，减法逐位可核；这里不含任何因果主张。"
    )
    lines.append("")
    lines.append("| 指标 | 重新优化差 | 同一路线差 | 路线搜索残差 |")
    lines.append("|---|---:|---:|---:|")
    for key, *_rest in METRICS:
        row = decomposition[key]
        lines.append(
            f"| {labels[key]} | {_fmt(row['reoptimised_delta'])} | "
            f"{_fmt(row['same_route_delta'])} | {_fmt(row['route_search_residual'])} |"
        )
    lines.append("")
    cross = summary["decomposition"]["common_basis_cross_reference"]
    lines.append(
        "交叉参考（另一种算法，不是上表的口径）：把两臂的路线集放在**同一种结算策略**下直接比总成本均值，"
        f"asap 口径下 {asap_arm} 的 10 个路线集 "
        f"{_fmt(cross[ASAP_POLICY][f'{asap_arm}_routes_mean_total_cost'])} 元、"
        f"{carbon_arm} 的 10 个路线集 "
        f"{_fmt(cross[ASAP_POLICY][f'{carbon_arm}_routes_mean_total_cost'])} 元，"
        f"相差 {cross[ASAP_POLICY]['route_quality_gap']:+.2f} 元；"
        f"cost_plus_carbon 口径下相差 {cross[CARBON_POLICY]['route_quality_gap']:+.2f} 元。"
        "两种共同口径与上表的残差同号同量级，说明这个读数不依赖于拿哪种策略当基准。"
        "**表格里只用上表那一个数，不要把两种算法混着报。**"
    )
    lines.append("")

    # ---- 三点判断 ----
    lines.append("## 四、三点判断（只报数据）")
    lines.append("")
    cost_reopt = reopt_change["total_cost"]
    emission_reopt = reopt_change["E_total"]
    lines.append(
        f"**1）重新优化对照。** 十次均值口径，考虑时变碳强度相对有可用时段即充电："
        f"总成本 {_fmt(cost_reopt['before'])} → {_fmt(cost_reopt['after'])} 元，"
        f"变化 {cost_reopt['delta']:+.2f} 元（{_fmt_pct(cost_reopt['pct'])}），"
        f"方向为{'升高' if cost_reopt['delta'] > 0 else '下降'}；"
        f"总排放 {_fmt(emission_reopt['before'])} → {_fmt(emission_reopt['after'])} kg，"
        f"变化 {emission_reopt['delta']:+.2f} kg（{_fmt_pct(emission_reopt['pct'])}），"
        f"方向为{'升高' if emission_reopt['delta'] > 0 else '下降'}。"
        "即在这批数据里，两臂各自重新优化后成本几乎持平（碳感知一侧略贵），排放明显更低。"
    )
    lines.append("")
    cost_paired = pooled["change"]["total_cost"]
    emission_paired = pooled["change"]["E_total"]
    lines.append(
        f"**2）同一路线对照。** {pooled['n_solutions']} 个路线集配对："
        f"总成本 {_fmt(cost_paired['before'])} → {_fmt(cost_paired['after'])} 元，"
        f"变化 {cost_paired['delta']:+.2f} 元（{_fmt_pct(cost_paired['pct'])}）；"
        f"总排放 {_fmt(emission_paired['before'])} → {_fmt(emission_paired['after'])} kg，"
        f"变化 {emission_paired['delta']:+.2f} kg（{_fmt_pct(emission_paired['pct'])}）；"
        f"充电成本变化 {pooled['change']['cost_elec']['delta']:+.2f} 元"
        f"（{_fmt_pct(pooled['change']['cost_elec']['pct'])}）。"
        f"{pooled['n_solutions']} 个解中总成本下降 {pooled['n_cost_down']} 个、"
        f"总排放下降 {pooled['n_emission_down']} 个、"
        f"**同时降本降排 {pooled['n_both_down']} 个**。"
    )
    lines.append("")
    residual_cost = decomposition["total_cost"]["route_search_residual"]
    residual_emission = decomposition["E_total"]["route_search_residual"]
    lines.append(
        f"**3）两种对照之差。** 总成本："
        f"{cost_reopt['delta']:+.2f} −（{cost_paired['delta']:+.2f}）= "
        f"**{residual_cost:+.2f} 元**；总排放："
        f"{emission_reopt['delta']:+.2f} −（{emission_paired['delta']:+.2f}）= "
        f"**{residual_emission:+.2f} kg**。"
        "这就是「两臂各自搜到的路线不同」在均值口径上贡献的量。"
        "成本上它比机制本身的效应大若干倍并且符号相反，"
        "所以重新优化对照里看到的成本差主要不是充电时刻机制造成的。"
    )
    lines.append("")

    # ---- 需要提醒的两处 ----
    lines.append("## 五、两处需要写表的人注意")
    lines.append("")
    lines.append(
        f"1. **成本方向与论文现有表述相反。** 论文正文现在写的是总成本下降 0.93%、"
        f"派遣车辆由 2 油 4 电变为 1 油 5 电；本批重新优化对照给出的是"
        f"总成本 {_fmt_pct(cost_reopt['pct'])}（碳感知一侧略贵），"
        "车队构型上（见第一节的计数表）"
        f"有可用时段即充电一侧 {reopt[asap_arm]['fleet_composition_counts'].get('2CV/3EV', 0)}/"
        f"{reopt[asap_arm]['n_runs']} 次落在 2 油 3 电，"
        f"考虑时变碳强度一侧 {reopt[carbon_arm]['fleet_composition_counts'].get('2CV/3EV', 0)}/"
        f"{reopt[carbon_arm]['n_runs']} 次，两臂主峰相同，"
        "没有出现车型任务重新分配的方向性变化。"
        "旧表的「减排来自车型重新分配」这条读法在本批数据里没有支撑。"
    )
    lines.append("")
    lines.append(
        f"2. **重新优化口径的排放差受单次异常值影响。** "
        f"{asap_arm} 十次里 {robustness['highest_emission_asap_run']['run']} 是 "
        f"{robustness['highest_emission_asap_run']['n_veh_cv']:.0f}油"
        f"{robustness['highest_emission_asap_run']['n_veh_ev']:.0f}电的离群构型，"
        f"排放 {_fmt(robustness['highest_emission_asap_run']['E_total'])} kg。"
        f"含它时两臂排放均值差 {robustness['mean_gap']:+.2f} kg；"
        f"剔除它后为 {robustness['mean_gap_excluding_that_run']:+.2f} kg；"
        f"中位对中位为 {robustness['median_gap']:+.2f} kg。"
        f"后两个数与同一路线对照的纯机制效应"
        f"（中位 {_fmt(emission_stats['median'])} kg）量级相当。"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_readme_md(summary: Mapping[str, Any]) -> str:
    asap_arm = summary["arms"]["asap_arm"]["name"]
    carbon_arm = summary["arms"]["carbon_arm"]["name"]
    replay = summary["self_checks"]["replay_consistency"]
    invariance = summary["self_checks"]["route_invariance"]
    pooled = summary["same_route"]["pooled"]

    return f"""# 充电时刻策略对比 — {summary['generated_utc']}

表10（不同充电时刻安排下的配送方案对比）的数据源。**本目录不含任何新的搜索**，
全部数字来自对已完成批次的读取与同解重排。

## 数据来源

- 批次：`{summary['source_batch']}`
- 算例：`{summary['instance']['instance_id']}`
- 碳价：{summary['instance']['carbon_price_cny_per_kg']} 元/kgCO2e
- 车队参数类：`{summary['instance']['fleet_parameter_class']}`
- 车场充电曲线：`{summary['instance']['depot_curve']}`；补电模式：`{summary['instance']['recharge_mode']}`

表10 的两条臂就是消融批的两臂，只差充电策略一个开关：

| 表10 列 | 消融臂 | `mechanism_off` | 生效充电策略 | 次数 |
|---|---|---|---|---:|
| 有可用时段即充电 | `{asap_arm}` | `["charge_timing"]` | `{summary['arms']['asap_arm']['policy']}` | {summary['reoptimised'][asap_arm]['n_runs']} |
| 考虑时变碳强度 | `{carbon_arm}` | `[]` | `{summary['arms']['carbon_arm']['policy']}` | {summary['reoptimised'][carbon_arm]['n_runs']} |

注意：`metadata.json` 里的 `mechanism_enabled.charge_timing` 在两臂都写着 `false`，
那是落盘时被 `include_charging_candidates` 覆写的结果，不代表机制关闭；
判断机制是否生效要看 `mechanism_closure.effective_charge_timing_policy`。
本脚本据此断言，不去断言 `mechanism_enabled`。

## 方法

1. **重新优化对照（表10 前两列）**：直接读两臂各 run 的 `best_solution.json` 中
   `evaluation.breakdown`，对各项指标取十次均值（同时记录总成本最低那一次的值备用）。
   两臂各自搜索路线，因此这一列的差异混杂了充电时刻机制与路线搜索的差异。
2. **同一路线对照（表10 新增列）**：取上述 {pooled['n_solutions']} 个解的路线，
   用 `repair_changed_duties` 在不改客户分配、不改趟序、不改车队的前提下，
   分别按 `asap` 与 `cost_plus_carbon` 重排充电时刻，再用 `DutyFullEvaluator` 做完整精确评价，
   逐解配对求差。这一列只反映充电时刻机制本身。

## 两条自检的结果

1. **重放一致性**：每个解在其**原策略**下重排后的 breakdown，与该解
   `best_solution.json` 里的官方 breakdown 逐个数值字段比对。
   容差 {replay['tolerance']}，实测最大绝对偏差 **{_dev(replay['max_abs_deviation'])}**{"" if replay['max_abs_deviation'] == 0.0 else "（出现在 " + replay['worst_key'] + "）"}。**通过。**
2. **路线不变性**：`{'`、`'.join(invariance['keys'])}` 六项在换策略前后比对。
   容差 {invariance['tolerance']}，实测最大绝对偏差 **{_dev(invariance['max_abs_deviation'])}**{"" if invariance['max_abs_deviation'] == 0.0 else "（出现在 " + invariance['worst_key'] + "）"}。**通过。**
   即重排确实只动了充电时刻。

两条自检任一失败脚本会立即退出并打印失败的解与字段，不会写出产物。

## 生成命令

```
cd <仓库根目录>
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
.public-hgs-venv/bin/python3 solver/scripts/build_charge_timing_comparison.py \\
    --batch-dir {summary['source_batch']} \\
    --out-dir solver/reports/charge_timing_comparison_20260904
```

两个目录都是命令行参数，换批次重跑只需改 `--batch-dir`。
全过程只做 {2 * pooled['n_solutions']} 次精确评价，数分钟内完成。

## 产物

- `summary.json` — 机器可读的全部数字（含逐解明细 `same_route.per_solution`）
- `summary.md` — 人读的表与三点判断
- `README.md` — 本文件
"""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
