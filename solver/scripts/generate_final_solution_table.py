"""Regenerate the paper's final-route table (表6) from one formal solution.

Every cell is recomputed from the physics ledger (per-arc energy, per-session
slot pricing); the script refuses to emit rows unless the column sums match
the run's official breakdown within tolerance.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import importlib.util
spec = importlib.util.spec_from_file_location("rt", Path(__file__).parent / "run_problem_hgs_private_technical.py")
rt = importlib.util.module_from_spec(spec); sys.modules["rt"] = rt; spec.loader.exec_module(rt)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver import cost as C
import setp_solver.search.multitrip_schedule as MTS

RUN = Path(sys.argv[1] if len(sys.argv) > 1 else
           "solver/reports/ablation_v6_20260906/MTC-HGS/run_07")
OUT = Path("docs/paper_v2/generated_tables/final_solution_trip_rows.tex")
DEPOT_LABEL = {"D_OSM_WAY_1003511503": "D1", "D_OSM_WAY_1071205721": "D2"}
# 单位碳价：默认取论文基准 0.20 元/kgCO2e，可由第二个命令行参数覆盖。
CARBON_PRICE = float(sys.argv[2]) if len(sys.argv) > 2 else 0.20
DIESEL_EF = 2.6419028944

bundle, _, _, ctx = rt._build_context(Path("."), rt.DEPOT_SEARCH_INSTANCE_ID,
    fleet_parameters=rt.FLEET_PARAMETER_CLASSES["endogenous"])
payload = json.load(open(RUN / "best_solution.json"))
official = payload["evaluation"]["breakdown"]
sol = solution_from_dict(payload["evaluation"]["prepared_solution"])
inst = bundle.instance
prices = bundle.prices
node_lookup = {n.node_id: n for n in inst.nodes}

cert = MTS.build_multitrip_certificate(list(sol.routes), inst, prices,
    charging_actions=list(sol.charging_actions))
trip_clock = {tr.route_id: (tr.departure_second, tr.return_second) for tr in cert.trips}

actions_by_route = {}
for a in sol.charging_actions:
    actions_by_route.setdefault(a.vehicle_id, []).append(a)

def physical_id(rid):
    return rid.split("#")[0]

first_trip_of = {}
for r in sol.routes:
    p = physical_id(r.vehicle_id)
    t = int(r.vehicle_id.split("#T")[1]) if "#T" in r.vehicle_id else 1
    if p not in first_trip_of or t < first_trip_of[p]:
        first_trip_of[p] = t

rows = []
tot = dict(dist=0.0, cost=0.0, hours=0.0, fuel=0.0, kwh=0.0, em=0.0, cust=0)
for r in sorted(sol.routes, key=lambda x: (physical_id(x.vehicle_id), x.vehicle_id)):
    e = C._evaluate_route(r, inst, node_lookup, prices)
    km = e.distance_m / 1000.0
    drive_s = 0.0
    for fr, to in zip(r.node_sequence, r.node_sequence[1:]):
        _, ts, _ = inst.arc_metrics(fr, to, r.vehicle_type, fallback_speed_mps=0.0)
        drive_s += ts
    serv_s = sum(getattr(node_lookup[n], "service_time", 0.0) or 0.0
                 for n in r.node_sequence[1:-1])
    hours = drive_s / 3600.0
    fuel = e.fuel_liters
    acts = actions_by_route.get(r.vehicle_id, [])
    kwh = sum(a.energy_kwh for a in acts)
    elec_cost = 0.0
    em_charge = 0.0
    for a in acts:
        rows_p = C.time_profile_rows_for_node(inst, a.station_id, bundle.time_profile)
        ns = len(rows_p)
        bd = C.charging_action_slot_breakdown(a, inst, prices, n_slots=ns)
        for s in bd:
            row = rows_p[s.slot_index % ns]
            elec_cost += s.y_skt_kwh * float(row["depot_energy_cny_per_kwh"])
            em_charge += s.y_skt_kwh * float(row["actual_gco2_per_kwh"])/1000.0
    diesel = C.diesel_price_for_route(r, inst, prices) if fuel > 0 else 0.0
    em = fuel * DIESEL_EF + em_charge
    per_km = 0.78 if r.vehicle_type == "cv" else 0.9145
    fixed = 0.0
    p = physical_id(r.vehicle_id)
    tno = int(r.vehicle_id.split("#T")[1]) if "#T" in r.vehicle_id else 1
    if tno == first_trip_of[p]:
        fixed = float(inst.vehicle_fixed_cost_per_day(r.vehicle_type, fallback=float(prices.vehicle_fixed_cost)))
    trip_cost = per_km * km + fuel * diesel + elec_cost + fixed + em * CARBON_PRICE
    demand = sum(node_lookup[n].demand for n in r.node_sequence[1:-1] if node_lookup[n].node_type.lower() == "c")
    cap = 1735.0 if r.vehicle_type == "cv" else 1700.0
    custs = [n for n in r.node_sequence[1:-1] if node_lookup[n].node_type.lower() == "c"]
    seq = [DEPOT_LABEL.get(r.node_sequence[0], r.node_sequence[0])] + \
          [str(int(c[1:])) if c.startswith("C") else c for c in r.node_sequence[1:-1]] + \
          [DEPOT_LABEL.get(r.node_sequence[-1], r.node_sequence[-1])]
    rows.append([r.vehicle_type, p, seq, km, trip_cost, hours, fuel, kwh, em, len(custs), demand / cap * 100.0])
    tot["dist"] += km; tot["cost"] += trip_cost; tot["hours"] += hours
    tot["fuel"] += fuel; tot["kwh"] += kwh; tot["em"] += em; tot["cust"] += len(custs)

checks = [
    ("总成本", tot["cost"], official["total_cost"], 1.0),
    ("总距离km", tot["dist"], official["distance_total"] / 1000.0, 0.5),
    ("油耗L", tot["fuel"], official["fuel_liters"], 0.2),
    ("电量kWh", tot["kwh"], official["electricity_kwh"], 0.2),
    ("排放kg", tot["em"], official["E_total"], 0.5),
    ("时间h", tot["hours"], official["route_time_hours"], 0.3),
]
bad = [(n, a, b) for n, a, b, tol in checks if abs(a - b) > tol]
for n, a, b, tol in checks:
    print(f"对账 {n}: 行和{a:.2f} vs 官方{b:.2f}")
if bad:
    print("对账失败，拒绝出表:", bad); sys.exit(2)

# 车辆标签：车型（燃/电）+ 同车型内的车辆序号 + 该车的趟序号，行序即 (物理车, 趟) 序。
TYPE_LABEL = {"cv": "燃", "ev": "电"}
veh_index, type_count, trip_count = {}, {}, {}
for row in rows:
    vtype, phys = row[0], row[1]
    label = TYPE_LABEL.get(vtype, vtype)
    if phys not in veh_index:
        type_count[label] = type_count.get(label, 0) + 1
        veh_index[phys] = type_count[label]
    trip_count[phys] = trip_count.get(phys, 0) + 1
    row[0] = f"{label}{veh_index[phys]}-{trip_count[phys]}"

lines = []
for tag, _phys, seq, km, cost, hours, fuel, kwh, em, n, load in rows:
    lines.append(f"{tag}: [{','.join(seq)}] & {km:.2f} & {cost:.2f} & {hours:.2f} & {fuel:.2f} & {kwh:.2f} & {em:.2f} & {n} & {load:.2f} \\\\")
lines.append(f"\\multicolumn{{1}}{{@{{}}l}}{{合计}} & {tot['dist']:.2f} & {tot['cost']:.2f} & {tot['hours']:.2f} & {tot['fuel']:.2f} & {tot['kwh']:.2f} & {tot['em']:.2f} & {tot['cust']} & --- \\\\")
lines.append("\\bottomrule")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"已写 {OUT}，{len(rows)} 趟")
