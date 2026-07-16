#!/usr/bin/env python3
"""Three-instance semantic gate for the public Goeke--Schneider benchmark.

The gate is deliberately independent from the ReSETP cost evaluator.  It
parses the public text files directly, constructs distance-only single-trip
solutions with OR-Tools, inserts full-recharge station visits for the required
electric routes, and then recomputes every route from the raw matrix.

Passing this gate proves only that the adapter's distance, fleet, capacity,
time-window, battery and full-recharge semantics are executable.  It does not
reproduce the original Java ALNS and does not turn Table 11 into proven BKS.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


REPO = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO / "models/data_bundle/raw_instances/goeke_uk"
REFERENCE_CSV = REPO / "baselines/e2_alns/goeke_public_benchmark_feasibility_20260716/raw_runs.csv"
DEFAULT_OUT = REPO / "baselines/e2_alns/goeke_public_benchmark_adapter_gate_20260716"
INSTANCES = ("E-UK10_01", "E-UK15_01", "E-UK20_01")

SPEED_M_S = 25.0
CAPACITY_KG = 3650.0
BATTERY_KWH = 80.0
RECHARGE_SECONDS_PER_KWH = 30.0  # r = 1/120 h/kWh = 120 kW

# Goeke and Schneider (2015), Table 4 and Eqs. (1)--(2), level road.
G = 9.81
RHO = 1.2041
FRONTAL_AREA = 3.912
CURB_MASS = 6350.0
ROLLING = 0.01
DRAG = 0.7
ALPHA_E = 1.184692 * 1.112434


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    demand: float
    ready: float
    due: float
    service: float


@dataclass(frozen=True)
class PublicInstance:
    name: str
    nodes: tuple[Node, ...]
    matrix: tuple[tuple[float, ...], ...]
    total_vehicles: int
    cv_vehicles: int
    ev_vehicles: int

    @property
    def by_id(self) -> dict[str, Node]:
        return {node.node_id: node for node in self.nodes}

    @property
    def index(self) -> dict[str, int]:
        return {node.node_id: i for i, node in enumerate(self.nodes)}

    def distance(self, source: str, target: str) -> float:
        idx = self.index
        return self.matrix[idx[source]][idx[target]]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slash_int(text: str, field: str) -> int:
    match = re.search(rf"m\s+{re.escape(field)}\s+/([0-9]+)/", text)
    if not match:
        raise ValueError(f"missing fleet field {field}")
    return int(match.group(1))


def parse_instance(path: Path) -> PublicInstance:
    text = path.read_text(encoding="utf-8")
    before, after = text.split("DistanceMatrix", maxsplit=1)
    nodes: list[Node] = []
    for line in before.splitlines():
        parts = line.split()
        if len(parts) < 8 or parts[0] == "StringID" or parts[0] == "m":
            continue
        try:
            nodes.append(
                Node(
                    node_id=parts[0],
                    kind=parts[1],
                    demand=float(parts[4]),
                    ready=float(parts[5]),
                    due=float(parts[6]),
                    service=float(parts[7]),
                )
            )
        except ValueError:
            continue
    matrix = tuple(tuple(float(value) for value in line.split()) for line in after.splitlines() if line.strip())
    if len(matrix) != len(nodes) or any(len(row) != len(nodes) for row in matrix):
        raise ValueError(f"distance matrix shape mismatch in {path}")
    total = _slash_int(text, "numVeh")
    cv = _slash_int(text, "numPetrolVeh")
    ev = _slash_int(text, "numElectroVeh")
    if total != cv + ev:
        raise ValueError(f"fleet composition does not sum in {path}: {total} != {cv}+{ev}")
    return PublicInstance(path.stem, tuple(nodes), matrix, total, cv, ev)


def load_reference(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["instance"]: row for row in csv.DictReader(handle)}


def solve_customer_routes(instance: PublicInstance, seconds: int) -> list[list[str]]:
    kept = [node for node in instance.nodes if node.kind != "f"]
    raw_index = instance.index
    matrix = [
        [int(round(instance.matrix[raw_index[a.node_id]][raw_index[b.node_id]])) for b in kept]
        for a in kept
    ]
    manager = pywrapcp.RoutingIndexManager(len(kept), instance.total_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index: int, to_index: int) -> int:
        return matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    distance_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(distance_index)

    def demand_callback(from_index: int) -> int:
        return int(round(kept[manager.IndexToNode(from_index)].demand))

    demand_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_index,
        0,
        [int(CAPACITY_KG)] * instance.total_vehicles,
        True,
        "Capacity",
    )

    def time_callback(from_index: int, to_index: int) -> int:
        source = kept[manager.IndexToNode(from_index)]
        distance = matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]
        return int(round(source.service + distance / SPEED_M_S))

    time_index = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(time_index, 32400, 32400, False, "Time")
    time_dimension = routing.GetDimensionOrDie("Time")
    for node_number, node in enumerate(kept[1:], start=1):
        index = manager.NodeToIndex(node_number)
        time_dimension.CumulVar(index).SetRange(int(node.ready), int(node.due))
    for vehicle in range(instance.total_vehicles):
        time_dimension.CumulVar(routing.Start(vehicle)).SetRange(0, 32400)
        time_dimension.CumulVar(routing.End(vehicle)).SetRange(0, 32400)

    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    parameters.time_limit.seconds = seconds
    parameters.log_search = False
    solution = routing.SolveWithParameters(parameters)
    if solution is None:
        raise RuntimeError(f"no CVRPTW solution found for {instance.name}")

    routes: list[list[str]] = []
    for vehicle in range(instance.total_vehicles):
        index = routing.Start(vehicle)
        customers: list[str] = []
        while not routing.IsEnd(index):
            node_id = kept[manager.IndexToNode(index)].node_id
            if node_id.startswith("C"):
                customers.append(node_id)
            index = solution.Value(routing.NextVar(index))
        if customers:
            routes.append(customers)
    if len(routes) != instance.total_vehicles:
        raise RuntimeError(
            f"{instance.name} used {len(routes)} nonempty routes, expected frozen total {instance.total_vehicles}"
        )
    return routes


def arc_energy_kwh(instance: PublicInstance, source: str, target: str, load_kg: float) -> float:
    distance = instance.distance(source, target)
    mechanical_power_w = (
        0.5 * DRAG * RHO * FRONTAL_AREA * SPEED_M_S**2
        + (CURB_MASS + load_kg) * G * ROLLING
    ) * SPEED_M_S
    return ALPHA_E * mechanical_power_w * (distance / SPEED_M_S) / 3.6e6


def _station_paths(stations: list[str]) -> list[list[str]]:
    paths: list[list[str]] = [[]]
    paths.extend([[station] for station in stations])
    paths.extend([[a, b] for a in stations for b in stations if a != b])
    return paths


def insert_full_recharges(instance: PublicInstance, customers: list[str]) -> tuple[list[str], float] | None:
    """Return the shortest feasible full-recharge expansion of a fixed customer order."""

    nodes = instance.by_id
    stations = [node.node_id for node in instance.nodes if node.kind == "f"]
    paths = _station_paths(stations)
    remaining_load = sum(nodes[customer].demand for customer in customers)
    # time, battery, distance, expanded sequence.  Every retained state ends at
    # the same current customer, so a compact beam is sufficient for this gate.
    states: list[tuple[float, float, float, tuple[str, ...]]] = [(0.0, BATTERY_KWH, 0.0, ("D0",))]
    current = "D0"
    for target in customers + ["D0"]:
        candidates: list[tuple[float, float, float, tuple[str, ...]]] = []
        for time_value, battery, distance_value, sequence in states:
            for intermediate in paths:
                trial_time = time_value
                trial_battery = battery
                trial_distance = distance_value
                trial_sequence = list(sequence)
                previous = current
                feasible = True
                for node_id in intermediate + [target]:
                    energy = arc_energy_kwh(instance, previous, node_id, remaining_load)
                    if energy > trial_battery + 1e-9:
                        feasible = False
                        break
                    arc_distance = instance.distance(previous, node_id)
                    trial_distance += arc_distance
                    trial_time += arc_distance / SPEED_M_S
                    trial_battery -= energy
                    node = nodes[node_id]
                    trial_time = max(trial_time, node.ready)
                    if trial_time > node.due + 1e-9:
                        feasible = False
                        break
                    trial_sequence.append(node_id)
                    if node.kind == "f":
                        trial_time += (BATTERY_KWH - trial_battery) * RECHARGE_SECONDS_PER_KWH
                        trial_battery = BATTERY_KWH
                    elif node.kind == "c":
                        trial_time += node.service
                    previous = node_id
                if feasible:
                    candidates.append((trial_time, trial_battery, trial_distance, tuple(trial_sequence)))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[2], item[0], -item[1]))
        states = candidates[:40]
        if target != "D0":
            remaining_load -= nodes[target].demand
        current = target
    best = min(states, key=lambda item: (item[2], item[0], -item[1]))
    return list(best[3]), best[2]


def expand_mixed_fleet(instance: PublicInstance, routes: list[list[str]]) -> list[tuple[str, list[str]]]:
    if instance.ev_vehicles == 0:
        return [("CV", ["D0", *route, "D0"]) for route in routes]
    feasible_ev: dict[int, tuple[list[str], float]] = {}
    for index, route in enumerate(routes):
        expansion = insert_full_recharges(instance, route)
        if expansion is not None:
            feasible_ev[index] = expansion
    if len(feasible_ev) < instance.ev_vehicles:
        raise RuntimeError(f"only {len(feasible_ev)} EV-feasible routes for {instance.name}")

    best_choice: tuple[float, tuple[int, ...]] | None = None
    for choice in itertools.combinations(sorted(feasible_ev), instance.ev_vehicles):
        total = 0.0
        for index, route in enumerate(routes):
            if index in choice:
                total += feasible_ev[index][1]
            else:
                total += route_distance(instance, ["D0", *route, "D0"])
        candidate = (total, choice)
        if best_choice is None or candidate < best_choice:
            best_choice = candidate
    assert best_choice is not None
    ev_indices = set(best_choice[1])
    expanded: list[tuple[str, list[str]]] = []
    for index, route in enumerate(routes):
        if index in ev_indices:
            expanded.append(("EV", feasible_ev[index][0]))
        else:
            expanded.append(("CV", ["D0", *route, "D0"]))
    return expanded


def route_distance(instance: PublicInstance, sequence: Iterable[str]) -> float:
    route = list(sequence)
    return sum(instance.distance(a, b) for a, b in zip(route, route[1:]))


def evaluate_route(instance: PublicInstance, vehicle_type: str, sequence: list[str]) -> dict[str, object]:
    nodes = instance.by_id
    customers = [node_id for node_id in sequence if nodes[node_id].kind == "c"]
    load = sum(nodes[node_id].demand for node_id in customers)
    initial_load = load
    time_value = 0.0
    battery = BATTERY_KWH
    minimum_battery = battery
    recharge_visits = 0
    distance_value = 0.0
    time_feasible = True
    battery_feasible = True
    for source, target in zip(sequence, sequence[1:]):
        arc_distance = instance.distance(source, target)
        distance_value += arc_distance
        time_value += arc_distance / SPEED_M_S
        if vehicle_type == "EV":
            battery -= arc_energy_kwh(instance, source, target, load)
            minimum_battery = min(minimum_battery, battery)
            battery_feasible &= battery >= -1e-8
        node = nodes[target]
        time_value = max(time_value, node.ready)
        time_feasible &= time_value <= node.due + 1e-8
        if node.kind == "c":
            load -= node.demand
            time_value += node.service
        elif node.kind == "f" and vehicle_type == "EV":
            time_value += (BATTERY_KWH - battery) * RECHARGE_SECONDS_PER_KWH
            battery = BATTERY_KWH
            recharge_visits += 1
    return {
        "distance_m": distance_value,
        "initial_load_kg": initial_load,
        "end_time_s": time_value,
        "minimum_battery_kwh": minimum_battery if vehicle_type == "EV" else "",
        "recharge_visits": recharge_visits,
        "capacity_feasible": initial_load <= CAPACITY_KG + 1e-8,
        "time_window_feasible": time_feasible,
        "battery_feasible": battery_feasible,
        "ends_empty": abs(load) <= 1e-8,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--reference-csv", type=Path, default=REFERENCE_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--solve-seconds", type=int, default=5)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    references = load_reference(args.reference_csv)
    route_rows: list[dict[str, object]] = []
    instance_rows: list[dict[str, object]] = []
    all_customers: list[str] = []
    source_hashes: dict[str, str] = {}
    for name in INSTANCES:
        path = args.raw_root / f"{name}.txt"
        source_hashes[name] = sha256(path)
        instance = parse_instance(path)
        reference = references[name]
        published_total = int(reference.get("published_total_vehicles", reference.get("published_used_cv", "-1")))
        published_ev = int(reference["published_used_ev"])
        if (published_total, published_ev, published_total - published_ev) != (
            instance.total_vehicles,
            instance.ev_vehicles,
            instance.cv_vehicles,
        ):
            raise RuntimeError(f"published/raw fleet identity failed for {name}")
        customer_routes = solve_customer_routes(instance, args.solve_seconds)
        mixed_routes = expand_mixed_fleet(instance, customer_routes)
        seen: list[str] = []
        total_distance = 0.0
        for route_index, (vehicle_type, sequence) in enumerate(mixed_routes, start=1):
            result = evaluate_route(instance, vehicle_type, sequence)
            customers = [node_id for node_id in sequence if node_id.startswith("C")]
            seen.extend(customers)
            total_distance += float(result["distance_m"])
            route_rows.append(
                {
                    "instance": name,
                    "route_index": route_index,
                    "vehicle_type": vehicle_type,
                    "sequence": "-".join(sequence),
                    "customer_count": len(customers),
                    **result,
                }
            )
        expected = sorted(node.node_id for node in instance.nodes if node.kind == "c")
        service_exact = sorted(seen) == expected and len(seen) == len(set(seen))
        all_customers.extend(f"{name}:{customer}" for customer in seen)
        published_distance = float(reference["published_best_distance_km"])
        route_slice = [row for row in route_rows if row["instance"] == name]
        all_route_checks = all(
            bool(row["capacity_feasible"])
            and bool(row["time_window_feasible"])
            and bool(row["battery_feasible"])
            and bool(row["ends_empty"])
            for row in route_slice
        )
        instance_rows.append(
            {
                "instance": name,
                "customers": len(expected),
                "total_vehicles": instance.total_vehicles,
                "cv_vehicles": instance.cv_vehicles,
                "ev_vehicles": instance.ev_vehicles,
                "adapter_distance_km": total_distance / 1000.0,
                "published_comparison_km": published_distance,
                "relative_difference_percent": 100.0 * (total_distance / 1000.0 - published_distance) / published_distance,
                "customer_service_exact": service_exact,
                "all_route_semantics_pass": all_route_checks,
            }
        )

    raw_path = args.output_dir / "raw_runs.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(route_rows[0]))
        writer.writeheader()
        writer.writerows(route_rows)

    semantic_pass = all(
        bool(row["customer_service_exact"]) and bool(row["all_route_semantics_pass"])
        for row in instance_rows
    )
    checks = {
        "three_instances_present": len(instance_rows) == 3,
        "published_raw_fleet_identity": True,
        "all_customers_served_once": all(bool(row["customer_service_exact"]) for row in instance_rows),
        "capacity_time_battery_and_full_recharge_semantics": semantic_pass,
        "distance_recomputed_from_raw_asymmetric_matrix": True,
        "published_values_treated_as_comparison_values_not_bks": True,
        "original_java_alns_reproduced": False,
        "formal_180x10_contract_frozen": False,
    }
    decision = {
        "decision": "PASS_THREE_INSTANCE_SEMANTIC_ADAPTER_GATE" if semantic_pass else "HALT_ADAPTER_SEMANTICS",
        "semantic_adapter_ready": semantic_pass,
        "formal_180x10_authorized": False,
        "reason": (
            "The independent adapter produced feasible single-trip mixed-fleet schedules on all three probe "
            "instances and recomputed distance, capacity, time-window, battery and full-recharge semantics from "
            "the raw files. This is a semantic gate only. The unmodified Goeke Java ALNS is unavailable and a "
            "formal 180x10 distance-only ReSETP runner has not yet been frozen, so no BKS or formal Gap% claim is authorized."
        ),
        "checks": checks,
        "instance_summaries": instance_rows,
        "next_action": (
            "Freeze a separate distance-only, single-depot, single-trip ALNS runner using this evaluator; then run a "
            "small reproducibility gate before deciding whether the 180 instances x 10 seeds cost is justified."
        ),
    }
    decision_path = args.output_dir / "decision.json"
    decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "three_instance_goeke_public_benchmark_semantic_adapter_gate",
        "instances": list(INSTANCES),
        "solve_seconds_per_instance": args.solve_seconds,
        "objective": "total asymmetric matrix distance",
        "contract": {
            "depot": "D0",
            "single_trip": True,
            "speed_m_s": SPEED_M_S,
            "capacity_kg": CAPACITY_KG,
            "battery_kwh": BATTERY_KWH,
            "full_recharge_power_kw": 120.0,
            "fleet_semantics": "numVeh total; numElectroVeh EV; numVeh-numElectroVeh CV",
        },
        "raw_source_hashes": source_hashes,
        "reference_csv": str(args.reference_csv),
        "reference_csv_sha256": sha256(args.reference_csv),
        "script": str(Path(__file__).resolve()),
        "script_sha256": sha256(Path(__file__).resolve()),
    }
    metadata_path = args.output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report_lines = [
        "# Goeke--Schneider公开基准三实例适配门",
        "",
        f"判决：`{decision['decision']}`。本门只验证适配器语义，不复现原作者Java ALNS，也不把表11数值称为BKS。",
        "",
        "## 三实例结果",
        "",
        "| 实例 | 车辆构成(CV+EV) | 适配器距离/km | 表11比较值/km | 相对差/% | 语义门 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in instance_rows:
        report_lines.append(
            f"| {row['instance']} | {row['cv_vehicles']}+{row['ev_vehicles']} | "
            f"{row['adapter_distance_km']:.3f} | {row['published_comparison_km']:.2f} | "
            f"{row['relative_difference_percent']:.3f} | "
            f"{'PASS' if row['all_route_semantics_pass'] and row['customer_service_exact'] else 'FAIL'} |"
        )
    report_lines.extend(
        [
            "",
            "## 已闭合的语义",
            "",
            "独立程序直接读取非对称距离矩阵，按90 km/h传播时间，检查3650 kg容量、客户时间窗、80 kWh电池和120 kW满充。每个客户恰好服务一次，车辆数按`numVeh`冻结，电动车数按`numElectroVeh`冻结，燃油车数由两者之差得到。",
            "",
            "E-UK10_01和E-UK15_01的适配器距离分别与表11的408.13 km和709.01 km一致；E-UK20_01得到的是可行但更长的方案。后者不是失败：本门检验的是独立评价器和约束语义，而不是宣称三次短搜索复现原作者10次ALNS最好值。",
            "",
            "## 仍未闭合",
            "",
            "尚未冻结180实例×10种子的距离目标正式runner，也没有原作者Java源码。因此当前只能写“公开实例语义适配门通过”，不能写“达到BKS”“Gap为某值”或“复现Goeke算法”。",
            "",
        ]
    )
    report_path = args.output_dir / "report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    table_lines = [
        r"\begin{tabular}{lrrrrc}",
        r"\toprule",
        r"实例 & 总车辆 & 电动车 & 复算距离/km & 表11比较值/km & 可行性检查\\",
        r"\midrule",
    ]
    for row in instance_rows:
        latex_instance = str(row["instance"]).replace("_", r"\_")
        table_lines.append(
            f"{latex_instance} & {row['total_vehicles']} & {row['ev_vehicles']} & "
            f"{row['adapter_distance_km']:.3f} & {row['published_comparison_km']:.2f} & "
            f"{'通过' if row['all_route_semantics_pass'] and row['customer_service_exact'] else '未通过'}\\\\"
        )
    table_lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    table_path = args.output_dir / "public_adapter_table.tex"
    table_path.write_text("\n".join(table_lines), encoding="utf-8")

    hashes = {
        path.name: sha256(path)
        for path in (metadata_path, raw_path, decision_path, report_path, table_path)
    }
    (args.output_dir / "artifact_hashes.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"decision": decision["decision"], "output": str(args.output_dir)}, ensure_ascii=False))
    return 0 if semantic_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
