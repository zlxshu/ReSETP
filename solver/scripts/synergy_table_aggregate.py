#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate the paper's tab:synergy comparison (independent vs joint delivery)
from solver run directories, plus route-level (depot assignment) diagnostics.

Read-only. Never launches the solver. Field provenance follows
solver/reports/synergy_v6_20260908/SUMMARY.md sections 1-4.

Usage
-----
python3 solver/scripts/synergy_table_aggregate.py \
    --independent-root solver/reports/synergy_v6_20260908/independent \
    --joint-root       solver/reports/ablation_v6_20260906/MTC-HGS \
    [--reference-assignment PATH/orders.csv | --reference-from-independent] \
    [--usable-day-minutes 540] [--out out.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_CSV = (
    REPO_ROOT
    / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
    / "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/orders.csv"
)
EXPECTED_EV_PREMIUM = 100.0
RUN_DIR_RE = re.compile(r"^run_(\d+)$")

# (json key, markdown label, decimals, provenance)
MAIN_ROWS = [
    ("total_cost",       "总成本（元）",                 2, "breakdown.total_cost"),
    ("cost_fix",         "车辆启动成本（元）",           2, "breakdown.cost_fix"),
    ("cost_km",          "行驶成本（元）",               2, "breakdown.cost_km"),
    ("cost_fuel",        "油耗成本（元）",               2, "breakdown.cost_fuel"),
    ("cost_elec",        "充电成本（元）",               2, "breakdown.cost_elec"),
    ("cost_carbon",      "碳排放成本（元）",             2, "breakdown.cost_carbon"),
    ("distance_total_km","总距离（km）",                 2, "breakdown.distance_total/1000"),
    ("emissions_total",  "总排放（kgCO2e）",             2, "breakdown.E_total"),
    ("n_veh_total",      "启用车辆数",                   2, "breakdown.n_veh_cv+n_veh_ev"),
    ("n_veh_ev",         "其中电动车数",                 2, "breakdown.n_veh_ev"),
    ("n_veh_cv",         "其中燃油车数（派生）",         2, "breakdown.n_veh_cv"),
    ("n_trips",          "配送趟数",                     2, "len(prepared_solution.routes)"),
    ("energy_cost",      "能源支出（元，派生）",         2, "cost_fuel+cost_elec"),
    ("grid_intensity",   "充电加权电网碳强度（gCO2/kWh）",1, "ledger: ΣEV间接排放×1000/Σ充电量"),
]


# ----------------------------------------------------------------- utilities
def natural_run_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        raise SystemExit(f"[FATAL] not a directory: {root}")
    hits = []
    for child in sorted(root.iterdir()):
        m = RUN_DIR_RE.match(child.name)
        if m and child.is_dir():
            hits.append((int(m.group(1)), child))
    if not hits:
        raise SystemExit(f"[FATAL] no run_<n> subdirectories under {root}")
    return [p for _, p in sorted(hits)]


def load_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def fmt(value, decimals):
    if value is None:
        return "n/a"
    return f"{value:.{decimals}f}"


def pct_change(indep, joint):
    if indep in (None, 0) or joint is None:
        return None
    return (joint - indep) / indep * 100.0


# ----------------------------------------------------------------- per run
def read_run(run_dir: Path, usable_day_minutes: float) -> dict:
    """Everything the tables need from one run directory."""
    sol = load_json(run_dir / "best_solution.json")
    ledger = load_json(run_dir / "enterprise_ledger.json")
    meta = load_json(run_dir / "metadata.json")

    ev = sol["evaluation"]
    bd = ev["breakdown"]
    routes = ev["prepared_solution"]["routes"]

    metrics = {
        "total_cost": bd["total_cost"],
        "cost_fix": bd["cost_fix"],
        "cost_km": bd["cost_km"],
        "cost_fuel": bd["cost_fuel"],
        "cost_elec": bd["cost_elec"],
        "cost_carbon": bd["cost_carbon"],
        "distance_total_km": bd["distance_total"] / 1000.0,
        "emissions_total": bd["E_total"],
        "n_veh_total": bd["n_veh_cv"] + bd["n_veh_ev"],
        "n_veh_ev": bd["n_veh_ev"],
        "n_veh_cv": bd["n_veh_cv"],
        "n_trips": len(routes),
        "energy_cost": bd["cost_fuel"] + bd["cost_elec"],
    }

    # --- ledger rows -------------------------------------------------------
    rows = ledger["rows"]
    ledger_depot = {}
    ev_indirect = 0.0
    charged_kwh = 0.0
    for depot_id, row in rows.items():
        ledger_depot[depot_id] = {
            "customers_served": row["customers_served"],
            "cost_total": row["cost_total"],
            "vehicles_field": row.get("vehicles"),  # absent in schema v1
        }
        ev_indirect += row.get("ev_indirect_emissions_kg", 0.0)
        charged_kwh += row.get("depot_charging_kwh", 0.0) + row.get("station_charging_kwh", 0.0)
    metrics["grid_intensity"] = (ev_indirect * 1000.0 / charged_kwh) if charged_kwh > 0 else None

    # --- route level: customer -> serving depot, vehicles, trips ------------
    assignment = {}
    veh_ids_by_depot = defaultdict(set)
    duty_trips_by_depot = Counter()
    for duty in sol["individual"]["duties"]:
        depot_id = duty["home_depot_id"]
        trips = duty.get("trips") or []
        n_trips_with_customers = 0
        for trip in trips:
            cids = trip.get("customer_ids") or []
            if cids:
                n_trips_with_customers += 1
            for cid in cids:
                if cid in assignment and assignment[cid] != depot_id:
                    raise SystemExit(
                        f"[FATAL] {run_dir}: customer {cid} served from two depots"
                    )
                assignment[cid] = depot_id
        if n_trips_with_customers > 0:
            veh_ids_by_depot[depot_id].add(duty["physical_vehicle_id"])
            duty_trips_by_depot[depot_id] += n_trips_with_customers

    # busy minutes from trip_clock, grouped by home_depot_id
    busy_by_depot = defaultdict(float)
    clock_trips_by_depot = Counter()
    clock_veh_by_depot = defaultdict(set)
    for entry in sol.get("trip_clock") or []:
        depot_id = entry["home_depot_id"]
        busy_by_depot[depot_id] += (entry["return_second"] - entry["departure_second"]) / 60.0
        clock_trips_by_depot[depot_id] += 1
        clock_veh_by_depot[depot_id].add(entry["physical_vehicle_id"])

    depot_ids = sorted(set(rows) | set(veh_ids_by_depot) | set(busy_by_depot))
    depot_stats = {}
    for depot_id in depot_ids:
        vehicles = len(veh_ids_by_depot.get(depot_id, ()))
        busy = busy_by_depot.get(depot_id, 0.0)
        capacity = vehicles * usable_day_minutes
        depot_stats[depot_id] = {
            "customers_from_solution": sum(1 for d in assignment.values() if d == depot_id),
            "customers_from_ledger": ledger_depot.get(depot_id, {}).get("customers_served"),
            "cost_total_ledger": ledger_depot.get(depot_id, {}).get("cost_total"),
            "vehicles_used": vehicles,
            "trips": clock_trips_by_depot.get(depot_id, 0),
            "trips_from_duties": duty_trips_by_depot.get(depot_id, 0),
            "busy_minutes": busy,
            "capacity_minutes": capacity,
            "utilisation_pct": (busy / capacity * 100.0) if capacity else None,
        }

    # --- acceptance / consistency -----------------------------------------
    checks, failures = {}, []

    closure = meta.get("mechanism_closure", {})
    violations = closure.get("violations", None)
    checks["mechanism_off"] = meta.get("mechanism_off")
    checks["mechanism_closure_violations"] = violations
    checks["effective_charge_timing_policy"] = closure.get("effective_charge_timing_policy")
    checks["effective_ev_daily_premium_cny"] = meta.get("effective_ev_daily_premium_cny")
    if violations != []:
        failures.append(f"mechanism_closure.violations not empty: {violations!r}")
    forbidden = closure.get("forbidden_named_proposed_actions", {}) or {}
    for group, counts in forbidden.items():
        for action, n in (counts or {}).items():
            if n:
                failures.append(f"forbidden action fired: {group}.{action}={n}")
    if checks["effective_ev_daily_premium_cny"] != EXPECTED_EV_PREMIUM:
        failures.append(
            f"effective_ev_daily_premium_cny={checks['effective_ev_daily_premium_cny']!r}"
            f" != {EXPECTED_EV_PREMIUM}"
        )

    checks["evaluation_feasible"] = ev.get("feasible")
    if ev.get("feasible") is not True:
        failures.append(f"evaluation.feasible={ev.get('feasible')!r}")
    if ev.get("violations"):
        failures.append(f"evaluation.violations={ev.get('violations')!r}")

    raw_path = run_dir / "raw_runs.csv"
    if raw_path.exists():
        raw = list(csv.DictReader(raw_path.open(encoding="utf-8")))
        if raw:
            r0 = raw[0]
            checks["best_feasible"] = r0.get("best_feasible")
            checks["best_violations"] = r0.get("best_violations")
            checks["customers_served"] = r0.get("customers_served")
            checks["customers_total"] = r0.get("customers_total")
            checks["instance_id"] = r0.get("instance_id")
            if str(r0.get("best_feasible")).lower() != "true":
                failures.append(f"raw_runs.best_feasible={r0.get('best_feasible')!r}")
            if str(r0.get("best_violations")) not in ("0", "0.0"):
                failures.append(f"raw_runs.best_violations={r0.get('best_violations')!r}")
            if r0.get("customers_served") != r0.get("customers_total"):
                failures.append(
                    f"customers_served {r0.get('customers_served')} != total {r0.get('customers_total')}"
                )
    else:
        checks["best_feasible"] = None
        failures.append("raw_runs.csv missing (cannot check best_feasible)")
    checks.setdefault("instance_id", meta.get("instance_id"))

    # cross-source consistency (validates the new route-level machinery)
    for depot_id, st in depot_stats.items():
        led = st["customers_from_ledger"]
        if led is not None and led != st["customers_from_solution"]:
            failures.append(
                f"{depot_id}: ledger customers_served={led} != duties-derived "
                f"{st['customers_from_solution']}"
            )
    veh_from_duties = sum(st["vehicles_used"] for st in depot_stats.values())
    if veh_from_duties != metrics["n_veh_total"]:
        failures.append(
            f"vehicles from duties={veh_from_duties} != breakdown n_veh_cv+n_veh_ev="
            f"{metrics['n_veh_total']}"
        )
    trips_from_clock = sum(st["trips"] for st in depot_stats.values())
    if trips_from_clock != metrics["n_trips"]:
        failures.append(
            f"trip_clock rows={trips_from_clock} != len(prepared_solution.routes)="
            f"{metrics['n_trips']}"
        )
    if abs(ev.get("total_cost", bd["total_cost"]) - bd["total_cost"]) > 1e-6:
        failures.append(
            f"evaluation.total_cost={ev.get('total_cost')} != breakdown.total_cost={bd['total_cost']}"
        )
    parts = sum(metrics[k] for k in ("cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_carbon"))
    if abs(parts - metrics["total_cost"]) > 1e-6:
        failures.append(f"cost parts {parts} != total_cost {metrics['total_cost']}")

    return {
        "run": run_dir.name,
        "path": str(run_dir),
        "metrics": metrics,
        "depot_stats": depot_stats,
        "assignment": assignment,
        "checks": checks,
        "failures": failures,
    }


def read_arm(root: Path, usable_day_minutes: float) -> dict:
    runs = [read_run(d, usable_day_minutes) for d in natural_run_dirs(root)]
    means = {k: mean([r["metrics"][k] for r in runs]) for k, _, _, _ in MAIN_ROWS}
    depot_ids = sorted({d for r in runs for d in r["depot_stats"]})
    depot_means = {}
    for depot_id in depot_ids:
        sub = [r["depot_stats"].get(depot_id) for r in runs]
        sub = [s for s in sub if s]
        depot_means[depot_id] = {
            "customers": mean([s["customers_from_solution"] for s in sub]),
            "cost_total_ledger": mean([s["cost_total_ledger"] for s in sub]),
            "vehicles_used": mean([s["vehicles_used"] for s in sub]),
            "trips": mean([s["trips"] for s in sub]),
            "busy_minutes": mean([s["busy_minutes"] for s in sub]),
            "utilisation_pct": mean([s["utilisation_pct"] for s in sub]),
        }
    arm_failures = []
    off_values = {json.dumps(r["checks"]["mechanism_off"], sort_keys=True) for r in runs}
    if len(off_values) > 1:
        arm_failures.append(f"mechanism_off not homogeneous within arm: {sorted(off_values)}")
    inst = {r["checks"].get("instance_id") for r in runs}
    if len(inst) > 1:
        arm_failures.append(f"multiple instance_ids within arm: {sorted(map(str, inst))}")
    n_zero = sum(1 for r in runs if r["metrics"]["grid_intensity"] is None)
    return {
        "root": str(root),
        "n_runs": len(runs),
        "runs": runs,
        "means": means,
        "depot_ids": depot_ids,
        "depot_means": depot_means,
        "mechanism_off": runs[0]["checks"]["mechanism_off"],
        "instance_id": runs[0]["checks"].get("instance_id"),
        "grid_intensity_runs_without_charging": n_zero,
        "arm_failures": arm_failures,
    }


# ------------------------------------------------------- reference assignment
def reference_from_csv(path: Path) -> dict:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if not rows or "home_depot_id" not in rows[0] or "customer_id" not in rows[0]:
        raise SystemExit(f"[FATAL] {path} lacks customer_id/home_depot_id columns")
    return {r["customer_id"]: r["home_depot_id"] for r in rows}


def reference_from_arm(arm: dict) -> tuple[dict, bool]:
    votes = defaultdict(Counter)
    for run in arm["runs"]:
        for cid, depot in run["assignment"].items():
            votes[cid][depot] += 1
    ref, unanimous = {}, True
    for cid, counter in votes.items():
        depot, n = counter.most_common(1)[0]
        ref[cid] = depot
        if n != sum(counter.values()):
            unanimous = False
    return ref, unanimous


def diff_vs_reference(assignment: dict, reference: dict, small_depot: str) -> dict:
    moved = []
    to_small = from_small = 0
    pairs = Counter()
    for cid, depot in sorted(assignment.items()):
        ref = reference.get(cid)
        if ref is None or ref == depot:
            continue
        moved.append({"customer_id": cid, "reference_depot": ref, "actual_depot": depot})
        pairs[f"{ref}->{depot}"] += 1
        if depot == small_depot:
            to_small += 1
        elif ref == small_depot:
            from_small += 1
    return {
        "n_differ": len(moved),
        "customer_ids": [m["customer_id"] for m in moved],
        "moved": moved,
        "large_to_small": to_small,
        "small_to_large": from_small,
        "net_into_small": to_small - from_small,
        "pairs": dict(pairs),
    }


# ---------------------------------------------------------------- rendering
def short(depot_id: str) -> str:
    return depot_id.split("_")[-1]


def print_main_table(indep, joint):
    print("## 表一 独立配送 vs 联合配送（各 10 次运行均值）\n")
    print(f"- 独立配送来源：`{indep['root']}`（{indep['n_runs']} 次，mechanism_off={indep['mechanism_off']}）")
    print(f"- 联合配送来源：`{joint['root']}`（{joint['n_runs']} 次，mechanism_off={joint['mechanism_off']}）")
    print(f"- 变化幅度 = (联合 − 独立)/独立 × 100%\n")
    print("| 指标 | 独立配送 | 联合配送 | 变化幅度 | 取数 |")
    print("|---|---:|---:|---:|---|")
    for key, label, dec, prov in MAIN_ROWS:
        a, b = indep["means"][key], joint["means"][key]
        ch = pct_change(a, b)
        print(f"| {label} | {fmt(a, dec)} | {fmt(b, dec)} | "
              f"{('%+.2f%%' % ch) if ch is not None else 'n/a'} | {prov} |")
    depot_ids = sorted(set(indep["depot_ids"]) | set(joint["depot_ids"]))
    for depot_id in depot_ids:
        for field, label, dec, prov in (
            ("customers", "服务客户数", 2, "duties→home_depot_id（与账本 customers_served 已核一致）"),
            ("cost_total_ledger", "企业成本（元）", 5, "enterprise_ledger.cost_total"),
            ("vehicles_used", "启用车辆数", 2, "duties 中有趟次的 physical_vehicle_id 去重"),
        ):
            a = indep["depot_means"].get(depot_id, {}).get(field)
            b = joint["depot_means"].get(depot_id, {}).get(field)
            ch = pct_change(a, b)
            print(f"| 车场 {short(depot_id)} {label} | {fmt(a, dec)} | {fmt(b, dec)} | "
                  f"{('%+.2f%%' % ch) if ch is not None else 'n/a'} | {prov} |")
    print()


def print_route_tables(arms, reference, small_depot, large_depots, ref_desc, usable):
    print("## 表二 路线层：与参考归属的偏离\n")
    print(f"- 参考归属：{ref_desc}")
    print(f"- 小车场 = `{small_depot}`（参考归属客户最少）；"
          f"其余车场 = {', '.join('`%s`' % d for d in large_depots)}")
    print("- 「大→小」= 参考在大车场、实际由小车场服务；「小→大」反之。"
          "偏离数按集合对称差计（净变动 = 大→小 − 小→大）。\n")
    print("| 配送模式 | 运行 | 偏离客户数 | 大→小 | 小→大 | 净入小车场 | 偏离客户 |")
    print("|---|---|---:|---:|---:|---:|---|")
    for arm_name, arm in arms:
        for run in arm["runs"]:
            d = run["diff"]
            ids = ", ".join(d["customer_ids"]) or "—"
            print(f"| {arm_name} | {run['run']} | {d['n_differ']} | {d['large_to_small']} | "
                  f"{d['small_to_large']} | {d['net_into_small']:+d} | {ids} |")
    print()
    print("| 配送模式 | 偏离客户数均值 | 最小 | 最大 | 大→小均值 | 小→大均值 |")
    print("|---|---:|---:|---:|---:|---:|")
    for arm_name, arm in arms:
        vals = [r["diff"]["n_differ"] for r in arm["runs"]]
        print(f"| {arm_name} | {mean(vals):.2f} | {min(vals)} | {max(vals)} | "
              f"{mean([r['diff']['large_to_small'] for r in arm['runs']]):.2f} | "
              f"{mean([r['diff']['small_to_large'] for r in arm['runs']]):.2f} |")
    print()
    print(f"## 表三 路线层：每车场车辆、趟次与占用（可用工作日 {usable:.0f} 分钟）\n")
    print("| 配送模式 | 车场 | 启用车辆数 | 趟数 | 忙碌分钟 | 可用分钟(车辆×%.0f) | 占用率 |"
          % usable)
    print("|---|---|---:|---:|---:|---:|---:|")
    for arm_name, arm in arms:
        for depot_id in arm["depot_ids"]:
            m = arm["depot_means"][depot_id]
            cap = (m["vehicles_used"] or 0) * usable
            util = f"{m['utilisation_pct']:.1f}%" if m["utilisation_pct"] is not None else "n/a"
            print(f"| {arm_name} | {short(depot_id)} | {m['vehicles_used']:.2f} | {m['trips']:.2f} | "
                  f"{m['busy_minutes']:.1f} | {cap:.1f} | {util} |")
    print()


def print_acceptance(arms):
    print("## 零 验收检查（SUMMARY.md §1 口径）\n")
    print("| 配送模式 | 运行 | mechanism_off | violations | best_feasible | 电动车日溢价 | 结果 |")
    print("|---|---|---|---|---|---:|---|")
    failures = []
    for arm_name, arm in arms:
        for run in arm["runs"]:
            c = run["checks"]
            ok = "PASS" if not run["failures"] else "**FAIL**"
            print(f"| {arm_name} | {run['run']} | {json.dumps(c['mechanism_off'], ensure_ascii=False)} | "
                  f"{json.dumps(c['mechanism_closure_violations'], ensure_ascii=False)} | "
                  f"{c.get('best_feasible')} | {c.get('effective_ev_daily_premium_cny')} | {ok} |")
            for f in run["failures"]:
                failures.append(f"{arm_name}/{run['run']}: {f}")
        for f in arm["arm_failures"]:
            failures.append(f"{arm_name}: {f}")
        if arm["grid_intensity_runs_without_charging"]:
            print(f"\n注：{arm_name} 有 {arm['grid_intensity_runs_without_charging']} 次运行充电量为 0，"
                  f"其电网碳强度未参与均值。")
    print()
    return failures


# --------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--independent-root", required=True, type=Path)
    ap.add_argument("--joint-root", required=True, type=Path)
    ref = ap.add_mutually_exclusive_group()
    ref.add_argument("--reference-assignment", type=Path, default=None,
                     help=f"orders.csv 提供参考归属（默认 {DEFAULT_REFERENCE_CSV}）")
    ref.add_argument("--reference-from-independent", action="store_true",
                     help="改用独立配送各次运行的逐客户众数归属作为参考")
    ap.add_argument("--usable-day-minutes", type=float, default=540.0)
    ap.add_argument("--out", type=Path, default=None, help="JSON 落盘路径")
    args = ap.parse_args(argv)

    indep = read_arm(args.independent_root, args.usable_day_minutes)
    joint = read_arm(args.joint_root, args.usable_day_minutes)
    arms = [("独立配送", indep), ("联合配送", joint)]

    if args.reference_from_independent:
        reference, unanimous = reference_from_arm(indep)
        ref_desc = ("独立配送 %d 次运行的逐客户众数归属（%s）"
                    % (indep["n_runs"], "各次一致" if unanimous else "存在分歧，按众数"))
        ref_source = {"mode": "independent-modal", "unanimous": unanimous}
    else:
        path = args.reference_assignment or DEFAULT_REFERENCE_CSV
        reference = reference_from_csv(path)
        ref_desc = f"`{path}` 的 home_depot_id 列（就近归属）"
        ref_source = {"mode": "csv", "path": str(path)}

    counts = Counter(reference.values())
    small_depot = min(sorted(counts), key=lambda d: counts[d])
    large_depots = [d for d in sorted(counts) if d != small_depot]
    ref_source["counts"] = dict(counts)
    ref_source["small_depot"] = small_depot

    for _, arm in arms:
        for run in arm["runs"]:
            run["diff"] = diff_vs_reference(run["assignment"], reference, small_depot)
            missing = set(run["assignment"]) - set(reference)
            if missing:
                run["failures"].append(f"customers absent from reference: {sorted(missing)}")

    failures = print_acceptance(arms)
    if failures:
        print("=" * 72)
        print("ACCEPTANCE FAILED — 以下检查未通过，聚合结果不可用：")
        for f in failures:
            print("  * " + f)
        print("=" * 72)
        sys.exit(2)

    print_main_table(indep, joint)
    print_route_tables(arms, reference, small_depot, large_depots, ref_desc,
                       args.usable_day_minutes)

    if args.out:
        payload = {
            "schema": "resetp.synergy_table_aggregate.v1",
            "reference_assignment": ref_source,
            "usable_day_minutes": args.usable_day_minutes,
            "row_definitions": [
                {"key": k, "label": l, "decimals": d, "provenance": p} for k, l, d, p in MAIN_ROWS
            ],
            "arms": {
                arm_key: {
                    "root": arm["root"],
                    "n_runs": arm["n_runs"],
                    "instance_id": arm["instance_id"],
                    "mechanism_off": arm["mechanism_off"],
                    "means": arm["means"],
                    "depot_means": arm["depot_means"],
                    "runs": [
                        {
                            "run": r["run"],
                            "path": r["path"],
                            "metrics": r["metrics"],
                            "depot_stats": r["depot_stats"],
                            "assignment": r["assignment"],
                            "reference_diff": r["diff"],
                            "checks": r["checks"],
                        }
                        for r in arm["runs"]
                    ],
                }
                for arm_key, arm in (("independent", indep), ("joint", joint))
            },
            "change_pct": {
                k: pct_change(indep["means"][k], joint["means"][k]) for k, _, _, _ in MAIN_ROWS
            },
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"JSON 已写入：{args.out}")


if __name__ == "__main__":
    main()
