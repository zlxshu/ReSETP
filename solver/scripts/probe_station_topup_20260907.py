"""离线上界探针：沿途公共站「顺路小补」最多能省多少（2026-09-07）。

用途
----
论文模型允许电动车在车场或任一公共站部分充电、可重复访问站；但求解器的充电修复层
（``solver/src/setp_solver/algorithms/resetp_alns/support/charging.py``）每趟只造两类
安排——「全部在车场补」与「车场只补到够开到某一个站、该站补足全部剩余里程」。实验里
公共站会话次数恒为 0。改造算法之前，先量一量「车场补大部分＋沿途某站小补一点」这件事
在现行价格、碳强度和路网下最多能给**已落盘的最优解**带来多大改善。

本脚本**只读**：不跑求解器、不改任何求解器代码、不写仓库以外的目录。它读已落盘的
``best_solution.json``，在每趟已有路线上枚举「客户 i 之后绕到公共站 s 补 Δ kWh 再去
下一站点 j」，把等量的车场补电按车场那笔充电的**实际时段价与碳强度**扣掉，算净收益，
取每趟最优，得到一个**宽松上界**。

上界为什么宽松（有意为之，宁可高估）
------------------------------------
* 只做粗时间窗校验：要求绕行增加的时间不超过「下一客户 due_time 减去按原路线到达
  下一客户的时刻」的松弛量，且站的服务窗口能容下充电；不重排后续行程、不检查后续
  客户的连锁迟到（另有一列 ``time_window_ok_downstream`` 专门补这一项）、
  不检查车场充电窗口是否会因电量减少而换时段。
* 车场那部分补电按其**实际选中时段**的价与碳折减（对站方案最有利的口径）。
* 允许车在站等待到当天任一更便宜/更干净的半小时槽再起充（只要还塞得进松弛），
  这是比派工要求更宽松的一档，为的是不把「没找到」错当成「不存在」。
* 绕出去的位置放宽到「车场出发弧」与「任一客户之后的弧」（派工只要求后者）。
* 每趟只允许一次顺路小补（多次只会更受服务费 0.4 元/kWh 的惩罚），所以每趟取最优一格。
* 绕行的行驶时间不计入任何成本（论文目标里行程时间本来就没有价格项）。

用法
----
    PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts' \
    .public-hgs-venv/bin/python3 solver/scripts/probe_station_topup_20260907.py \
        --out solver/reports/probe_station_topup_20260907

输出（CSV，写到 --out 目录）
----------------------------
* ``per_kwh_gap.csv``      每份日历下「把 1 kWh 从车场最便宜时段挪到公共站某小时」的
                           闭式差价、碳折减和盈亏平衡碳价（不含绕行）。
* ``trip_upper_bound.csv`` 每个解每趟的最优小补格（站、时刻、补电量、净收益、碳变化）。
* ``summary.csv``          每个目录一行的汇总。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parents[2]
for extra in ("solver/src", "third_party/setp_hgs_kernel", "models/src", "solver/scripts"):
    candidate = str(REPO / extra)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import importlib.util

from setp_solver.charging_action import _curve_aware_action
from setp_solver.cost import (
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    ev_instance_arc_energy_kwh,
)

_RUNNER_PATH = REPO / "solver/scripts/run_problem_hgs_private_technical.py"
_spec = importlib.util.spec_from_file_location("_probe_runner", _RUNNER_PATH)
_runner = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_runner)

FLEET_PARAMETER_CLASSES = _runner.FLEET_PARAMETER_CLASSES
_load_v3_suite_bundle = _runner._load_v3_suite_bundle

# 探针覆盖的目录；策略组合目录按派工要求只取前三次运行。
TARGETS: list[tuple[str, str, int | None]] = [
    ("beijing_P0.2", "solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS", None),
    ("beijing_P1.0", "solver/reports/grid2x2_v3_20260906/beijing/P=1.0/MTC-HGS", None),
    ("midday_P0.2", "solver/reports/grid2x2_v3_20260906/midday/P=0.2/MTC-HGS", None),
    ("midday_P1.0", "solver/reports/grid2x2_v3_20260906/midday/P=1.0/MTC-HGS", None),
    ("midday_subsidy", "solver/reports/policy_combos_20260907/midday_subsidy", 3),
]

REPLACE_FRACTIONS = (0.25, 0.50, 1.00)
_TOL = 1e-9


def _bundle_for(calendar_rel: str, package_root: Path, instance_id: str, premium: float):
    calendar_dir = REPO / Path(calendar_rel).parent
    bundle, _ = _load_v3_suite_bundle(
        REPO,
        package_root=package_root,
        instance_id=instance_id,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
        tariff_calendar_authority=calendar_dir,
        ev_daily_premium_cny=premium,
    )
    return bundle


def _price_of(prices, name: str) -> float:
    return float(getattr(prices, name))


def per_kwh_gap_rows(bundle, label: str, carbon_prices: tuple[float, ...]):
    """闭式：把 1 kWh 从车场最便宜时段挪到公共站第 h 小时的净代价。"""
    profile = bundle.time_profile
    rows = []
    slots = [
        (
            float(r["horizon_second_start"]),
            float(r["depot_energy_cny_per_kwh"]),
            float(r["public_total_cny_per_kwh"]),
            float(r["actual_gco2_per_kwh"]) / 1000.0,
        )
        for r in profile
    ]
    best_depot = min(slots, key=lambda s: s[1])
    for start_s, dep_price, pub_price, carbon in slots:
        d_cost = pub_price - best_depot[1]
        d_carbon = best_depot[3] - carbon  # 正数＝站更干净
        breakeven = (d_cost / d_carbon) if d_carbon > _TOL else float("inf")
        row = {
            "calendar": label,
            "station_slot_start_second": start_s,
            "station_hour": start_s / 3600.0,
            "cheapest_depot_slot_start_second": best_depot[0],
            "depot_price_cny_per_kwh": best_depot[1],
            "depot_carbon_kg_per_kwh": best_depot[3],
            "station_public_total_cny_per_kwh": pub_price,
            "station_carbon_kg_per_kwh": carbon,
            "delta_energy_cost_cny_per_kwh": d_cost,
            "carbon_saved_kg_per_kwh": d_carbon,
            "breakeven_carbon_price_cny_per_kg": breakeven,
        }
        for p in carbon_prices:
            row[f"net_gain_cny_per_kwh_at_P={p}"] = p * d_carbon - d_cost
        rows.append(row)
    return rows


def _walk_route(route, instance, prices, depart_second):
    """复刻修复层的行程时钟：返回每个位置的离开时刻与该弧的载重。"""
    node_lookup = instance.node_lookup
    seq = list(route["node_sequence"])
    targets = seq[1:]
    remaining = [n for n in targets if node_lookup[n].node_type.lower() == "c"]
    t = float(depart_second)
    out = []  # (from_id, to_id, load_kg, depart_from_second, arrive_to_second, depart_to_second)
    current = seq[0]
    for target in targets:
        load = sum(float(node_lookup[n].demand) for n in remaining)
        _, travel, _ = instance.arc_metrics(current, target, "ev", fallback_speed_mps=0.0)
        arrive = t + travel
        depart_target = max(arrive, float(node_lookup[target].ready_time)) + float(
            node_lookup[target].service_time
        )
        out.append((current, target, load, t, arrive, depart_target))
        if node_lookup[target].node_type.lower() == "c":
            remaining.remove(target)
        t = depart_target
        current = target
    return out


def probe_solution(sol_path: Path, bundle, carbon_price: float, run_label: str):
    instance = bundle.instance
    prices = bundle.prices
    profile = bundle.time_profile
    node_lookup = instance.node_lookup
    payload = json.loads(sol_path.read_text())
    prepared = payload["evaluation"]["prepared_solution"]
    clock = {row["route_id"]: row for row in payload["trip_clock"]}
    actions = prepared["charging_actions"]
    stations = [n for n in instance.nodes if n.node_type.lower() == "f"]
    ev_km_cost = instance.non_energy_distance_cost_per_km("ev", fallback=_price_of(prices, "c_km"))
    battery_cap = instance.battery_capacity_kwh(fallback=_price_of(prices, "B_battery_kwh"))

    rows = []
    for route in prepared["routes"]:
        if route["vehicle_type"] != "ev":
            continue
        rid = route["vehicle_id"]
        depot_actions = [
            a
            for a in actions
            if a["vehicle_id"] == rid
            and node_lookup[a["station_id"]].node_type.lower() == "d"
        ]
        if not depot_actions:
            continue
        da = depot_actions[0]
        depot_energy = float(da["energy_kwh"])
        if depot_energy <= _TOL:
            continue
        depot_action = _curve_aware_action(
            vehicle_id=rid,
            station_id=da["station_id"],
            start_energy_kwh=float(da["start_energy_kwh"]),
            energy_kwh=depot_energy,
            reference_power_kw=float(node_lookup[da["station_id"]].charge_power_kw),
            prices=prices,
            instance=instance,
        )
        depot_action = replace(
            depot_action, charge_start_second=float(da["charge_start_second"])
        )
        depot_cost = charging_action_electricity_cost(depot_action, instance, profile, prices)
        depot_co2 = charging_action_emissions_kg(depot_action, instance, profile, prices)
        depot_cost_per_kwh = depot_cost / depot_energy
        depot_co2_per_kwh = depot_co2 / depot_energy

        cl = clock.get(rid)
        if cl is None or cl.get("departure_second") is None:
            continue
        arcs = _walk_route(route, instance, prices, float(cl["departure_second"]))
        # 同一台车的下一趟出发时刻（用于核「本趟推迟会不会顶到下一趟」）
        next_trip_departure = None
        if "#T" in rid:
            veh, tidx = rid.rsplit("#T", 1)
            nxt = clock.get(f"{veh}#T{int(tidx) + 1}")
            if nxt is not None and nxt.get("departure_second") is not None:
                next_trip_departure = float(nxt["departure_second"])

        seq = list(route["node_sequence"])

        def downstream_ok(arc_index: int, depart_after_station: float) -> bool:
            """从插站弧的下游重走一遍，逐点核 due_time 与回场时刻。"""
            node_lookup_l = instance.node_lookup
            rest = seq[arc_index + 1 :]
            remaining_l = [
                n for n in rest if node_lookup_l[n].node_type.lower() == "c"
            ]
            t_l = depart_after_station
            cur = seq[arc_index]  # 逻辑上车已在站，用站->下一点单独处理
            first = True
            for idx, tgt in enumerate(rest):
                load_l = sum(float(node_lookup_l[n].demand) for n in remaining_l)
                src = station_id_for_walk if first else cur
                _, tr, _ = instance.arc_metrics(src, tgt, "ev", fallback_speed_mps=0.0)
                arrive_l = t_l + tr
                if arrive_l > float(node_lookup_l[tgt].due_time) + _TOL:
                    return False
                t_l = max(arrive_l, float(node_lookup_l[tgt].ready_time)) + float(
                    node_lookup_l[tgt].service_time
                )
                if node_lookup_l[tgt].node_type.lower() == "c":
                    remaining_l.remove(tgt)
                cur = tgt
                first = False
            return True

        best = None
        for arc_index, (from_id, to_id, load, depart_from, arrive_to, _dep_to) in enumerate(arcs):
            if node_lookup[from_id].node_type.lower() not in {"c", "d"}:
                continue  # 车场出发弧与任一客户之后的弧都允许绕出去
            d_direct, t_direct, _ = instance.arc_metrics(
                from_id, to_id, "ev", fallback_speed_mps=0.0
            )
            slack = float(node_lookup[to_id].due_time) - arrive_to
            for st in stations:
                d1, t1, _ = instance.arc_metrics(from_id, st.node_id, "ev", fallback_speed_mps=0.0)
                d2, t2, _ = instance.arc_metrics(st.node_id, to_id, "ev", fallback_speed_mps=0.0)
                detour_m = d1 + d2 - d_direct
                detour_s = t1 + t2 - t_direct
                if detour_m < -_TOL:
                    continue
                e1 = ev_instance_arc_energy_kwh(instance, from_id, st.node_id, load, prices)
                e2 = ev_instance_arc_energy_kwh(instance, st.node_id, to_id, load, prices)
                e_direct = ev_instance_arc_energy_kwh(instance, from_id, to_id, load, prices)
                detour_kwh = e1 + e2 - e_direct
                arrive_station = depart_from + t1
                if arrive_station < float(st.ready_time) - _TOL:
                    arrive_station = float(st.ready_time)
                for frac in REPLACE_FRACTIONS:
                    moved = depot_energy * frac
                    station_energy = moved + max(0.0, detour_kwh)
                    if station_energy > battery_cap + _TOL:
                        continue
                    act = _curve_aware_action(
                        vehicle_id=rid,
                        station_id=st.node_id,
                        start_energy_kwh=0.0,
                        energy_kwh=station_energy,
                        reference_power_kw=float(st.charge_power_kw),
                        prices=prices,
                        instance=instance,
                    )
                    occupancy_s = float(act.occupancy_minutes) * 60.0
                    # 允许在站等一段时间挑更便宜/更干净的时段：起充时刻可落在
                    # [到站时刻, 到站时刻 + 剩余松弛] 内的任一半小时槽起点。
                    latest_start = min(
                        float(st.due_time) - occupancy_s,
                        arrive_station + max(0.0, slack - detour_s - occupancy_s),
                    )
                    starts = [arrive_station]
                    if latest_start > arrive_station + _TOL:
                        step = 86400.0 / len(profile)
                        k = math.ceil(arrive_station / step)
                        while k * step <= latest_start + _TOL:
                            starts.append(k * step)
                            k += 1
                    best_start = None
                    for cand in starts:
                        a2 = replace(act, charge_start_second=cand)
                        c2 = charging_action_electricity_cost(a2, instance, profile, prices)
                        g2 = charging_action_emissions_kg(a2, instance, profile, prices)
                        score = c2 + carbon_price * g2
                        if best_start is None or score < best_start[0] - _TOL:
                            best_start = (score, cand, c2, g2)
                    _, charge_start, st_cost, st_co2 = best_start
                    act = replace(act, charge_start_second=charge_start)
                    a0 = replace(act, charge_start_second=arrive_station)
                    st_cost0 = charging_action_electricity_cost(a0, instance, profile, prices)
                    st_co20 = charging_action_emissions_kg(a0, instance, profile, prices)
                    tw_ok = (
                        detour_s + occupancy_s <= slack + _TOL
                        and charge_start + occupancy_s <= float(st.due_time) + _TOL
                        and charge_start >= arrive_station - _TOL
                    )
                    station_id_for_walk = st.node_id
                    tw_ok_down = tw_ok and downstream_ok(
                        arc_index, charge_start + occupancy_s
                    )
                    # 本趟被推迟的总时长；若同一台车后面还有趟，用它核会不会顶到下一趟。
                    added_s = detour_s + (charge_start - arrive_station) + occupancy_s
                    next_dep = next_trip_departure
                    pushes_next = (
                        next_dep is not None
                        and cl.get("return_second") is not None
                        and float(cl["return_second"]) + added_s > float(next_dep) + _TOL
                    )
                    gain_cost = (
                        moved * depot_cost_per_kwh
                        - st_cost
                        - detour_m / 1000.0 * ev_km_cost
                    )
                    co2_delta = st_co2 - moved * depot_co2_per_kwh  # 正数＝更脏
                    gain = gain_cost - carbon_price * co2_delta
                    gain_no_wait = (
                        moved * depot_cost_per_kwh
                        - st_cost0
                        - detour_m / 1000.0 * ev_km_cost
                        - carbon_price * (st_co20 - moved * depot_co2_per_kwh)
                    )
                    if best is None or (gain > best["gain_cny"] + _TOL):
                        best = {
                            "run": run_label,
                            "route_id": rid,
                            "after_customer": from_id,
                            "before_node": to_id,
                            "station_id": st.node_id,
                            "arrive_station_second": arrive_station,
                            "arrive_station_hour": (arrive_station % 86400.0) / 3600.0,
                            "charge_start_second": charge_start,
                            "charge_start_hour": (charge_start % 86400.0) / 3600.0,
                            "replace_fraction": frac,
                            "depot_energy_kwh": depot_energy,
                            "moved_kwh": moved,
                            "station_energy_kwh": station_energy,
                            "detour_m": detour_m,
                            "detour_seconds": detour_s,
                            "occupancy_seconds": occupancy_s,
                            "slack_to_next_due_seconds": slack,
                            "time_window_ok": tw_ok,
                            "time_window_ok_downstream": tw_ok_down,
                            "added_trip_seconds": added_s,
                            "pushes_next_trip": pushes_next,
                            "depot_cost_per_kwh": depot_cost_per_kwh,
                            "depot_carbon_kg_per_kwh": depot_co2_per_kwh,
                            "station_cost_cny": st_cost,
                            "station_carbon_kg": st_co2,
                            "detour_km_cost_cny": detour_m / 1000.0 * ev_km_cost,
                            "gain_money_only_cny": gain_cost,
                            "carbon_delta_kg": co2_delta,
                            "gain_cny": gain,
                            "wait_seconds": charge_start - arrive_station,
                            "gain_no_wait_cny": gain_no_wait,
                        }
        if best is not None:
            rows.append(best)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="solver/reports/probe_station_topup_20260907")
    args = ap.parse_args()
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)

    bundles: dict[tuple[str, str, float], object] = {}
    per_kwh: list[dict] = []
    trip_rows: list[dict] = []
    summary: list[dict] = []

    for label, rel, limit in TARGETS:
        base = REPO / rel
        run_dirs = sorted(p for p in base.glob("run_*") if p.is_dir())
        if limit is not None:
            run_dirs = run_dirs[:limit]
        rows_here: list[dict] = []
        n_trips = 0
        carbon_price = None
        calendar_rel = None
        for rd in run_dirs:
            sol = rd / "best_solution.json"
            meta = rd / "metadata.json"
            if not sol.is_file() or not meta.is_file():
                continue
            md = json.loads(meta.read_text())
            carbon_price = float(md["carbon_price_cny_per_kg"])
            calendar_rel = md["bundle_source_paths"]["tariff_carbon_calendar"]
            package_root = REPO / md["bundle_source_paths"]["suite"]
            instance_id = md["instance_id"]
            premium = float(md["effective_ev_daily_premium_cny"])
            key = (calendar_rel, instance_id, premium)
            if key not in bundles:
                bundles[key] = _bundle_for(calendar_rel, package_root, instance_id, premium)
                per_kwh.extend(
                    per_kwh_gap_rows(bundles[key], Path(calendar_rel).parent.name, (0.2, 1.0))
                )
            bundle = bundles[key]
            rr = probe_solution(sol, bundle, carbon_price, f"{label}/{rd.name}")
            rows_here.extend(rr)
            n_trips += len(rr)
        trip_rows.extend(rows_here)
        pos = [r for r in rows_here if r["gain_cny"] > 1e-6]
        pos_tw = [r for r in pos if r["time_window_ok"]]
        pos_down = [r for r in pos if r["time_window_ok_downstream"]]
        pos_clean = [r for r in pos_down if not r["pushes_next_trip"]]
        n_runs = len({r["run"] for r in rows_here}) or 1
        summary.append(
            {
                "target": label,
                "dir": rel,
                "calendar": calendar_rel,
                "carbon_price_cny_per_kg": carbon_price,
                "n_runs": n_runs,
                "n_ev_trips_with_depot_charge": len(rows_here),
                "share_trips_with_positive_bound": (len(pos) / len(rows_here)) if rows_here else 0.0,
                "share_trips_positive_and_tw_ok": (len(pos_tw) / len(rows_here)) if rows_here else 0.0,
                "n_trips_positive_and_downstream_tw_ok": len(pos_down),
                "n_trips_positive_downstream_ok_and_no_next_trip_push": len(pos_clean),
                "cost_upper_bound_no_next_trip_push_cny_per_solution": sum(
                    r["gain_cny"] for r in pos_clean
                )
                / (len({r["run"] for r in rows_here}) or 1),
                "cost_upper_bound_downstream_ok_cny_per_solution": sum(
                    r["gain_cny"] for r in pos_down
                )
                / (len({r["run"] for r in rows_here}) or 1),
                "mean_cost_upper_bound_cny_per_solution": sum(
                    r["gain_cny"] for r in pos
                )
                / n_runs,
                "mean_cost_upper_bound_tw_ok_cny_per_solution": sum(
                    r["gain_cny"] for r in pos_tw
                )
                / n_runs,
                "mean_carbon_upper_bound_kg_per_solution": sum(
                    -r["carbon_delta_kg"] for r in pos
                )
                / n_runs,
                "n_trips_positive_no_wait": sum(
                    1 for r in rows_here if r["gain_no_wait_cny"] > 1e-6
                ),
                "best_single_gain_cny": max((r["gain_cny"] for r in rows_here), default=0.0),
                "best_single_gain_no_wait_cny": max(
                    (r["gain_no_wait_cny"] for r in rows_here), default=0.0
                ),
                "max_wait_seconds_in_best_rows": max(
                    (r["wait_seconds"] for r in rows_here), default=0.0
                ),
                "best_gain_station": max(rows_here, key=lambda r: r["gain_cny"])["station_id"]
                if rows_here
                else "",
                "best_gain_arrive_hour": max(rows_here, key=lambda r: r["gain_cny"])[
                    "arrive_station_hour"
                ]
                if rows_here
                else "",
                "max_trip_gain_all_signs_cny": max(
                    (r["gain_cny"] for r in rows_here), default=0.0
                ),
            }
        )
        print(f"[{label}] runs={n_runs} trips={len(rows_here)} positive={len(pos)} "
              f"best={summary[-1]['best_single_gain_cny']:.4f} CNY")

    def _dump(path: Path, rows: list[dict]) -> None:
        if not rows:
            path.write_text("")
            return
        keys: list[str] = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)

    _dump(out / "per_kwh_gap.csv", per_kwh)
    _dump(out / "trip_upper_bound.csv", trip_rows)
    _dump(out / "summary.csv", summary)
    print(f"写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
