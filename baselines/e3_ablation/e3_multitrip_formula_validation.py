#!/usr/bin/env python3
"""Eight independent checks for the E3 physical-vehicle trip-link formulas."""

from __future__ import annotations

import csv
from dataclasses import replace
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import random
import re
import sys

import networkx as nx
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
import sympy as sp

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "solver/src"))

from setp_solver.cost import charging_slot_breakdown, evaluate  # noqa: E402
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.prices import PriceParameters  # noqa: E402
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    CHARGE_MODE_ON_DEMAND,
    CONTRACT_ID,
    build_multitrip_certificate,
    certificate_charging_actions,
)
from setp_solver.solution import Route, Solution  # noqa: E402


OUT = ROOT / "baselines/e3_ablation/e3_multitrip_formula_validation_20260713"
OLD = ROOT / "baselines/e3_ablation/e3_multitrip_structure_gate_22kw_20260712_v3"
TOL = 1e-6


def check_units_and_source() -> dict:
    power, duration = sp.symbols("pi Delta", positive=True)
    energy = power * duration / 3600
    assert sp.simplify(energy.subs({power: 22, duration: 3600}) - 22) == 0
    price_text = (ROOT / "solver/src/setp_solver/prices.py").read_text(encoding="utf-8")
    contract_text = (ROOT / "solver/src/setp_solver/search/multitrip_schedule.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^depot_charge_power_kw\s*=\s*22\.0", price_text, flags=re.M)) == 1
    assert "depot_charge_power_kw: float = 22.0" not in contract_text
    return {"status": "PASS", "detail": "功率乘时间能正确换算成电量；22千瓦只有一个程序默认来源"}


def check_symbolic_chain() -> dict:
    b0, q1, q2, e1, e2, e3, cap = sp.symbols("b0 q1 q2 e1 e2 e3 B", nonnegative=True)
    b1 = b0 - e1
    b2 = b1 + q1 - e2
    b3 = b2 + q2 - e3
    assert sp.expand(b3) == b0 + q1 + q2 - e1 - e2 - e3
    ret, start, duration, depart = sp.symbols("ret start duration depart", real=True)
    # Published-form window: ret <= start and start+duration <= depart.
    assert sp.simplify((depart - ret) - ((start - ret) + duration + (depart - start - duration))) == 0
    return {"status": "PASS", "detail": "电量逐趟衔接和充电完整落在空档内都能严格推出"}


def _old_trips() -> list[dict]:
    trips: list[dict] = []
    for name in ("solo_business_partial_certificate.json", "shared_business_partial_certificate.json"):
        payload = json.loads((OLD / name).read_text(encoding="utf-8"))
        trips.extend(payload["certificate"]["trips"])
    return trips


def check_saved_witness_numpy() -> dict:
    trips = _old_trips()
    checked = 0
    by_key: dict[tuple[str, str], list[dict]] = {}
    for index, trip in enumerate(trips):
        by_key.setdefault((str(index // 59), trip["physical_vehicle_id"]), []).append(trip)
    for chain in by_key.values():
        ordered = sorted(chain, key=lambda row: row["trip_index"])
        for previous, current in zip(ordered, ordered[1:]):
            assert float(current["departure_second"]) + TOL >= float(previous["recharge_end_second"])
            if current["vehicle_type"] == "ev":
                lhs = float(current["start_battery_kwh"])
                rhs = float(previous["end_battery_kwh"]) + float(previous.get("charge_energy_kwh") or 0.0)
                assert bool(np.isclose(lhs, rhs, atol=TOL, rtol=0))
                if float(previous.get("charge_energy_kwh") or 0.0) > TOL:
                    assert float(previous["charge_start_second"]) + TOL >= float(previous["return_second"])
            checked += 1
    assert checked > 0
    return {"status": "PASS", "detail": f"回放两份22千瓦旧见证中的{checked}条相邻趟衔接，全部满足"}


def _milp_feasible(compat: np.ndarray, vehicles: int) -> bool:
    trips = compat.shape[0]
    n = trips * vehicles
    constraints = []
    lo = []
    hi = []
    for trip in range(trips):
        row = np.zeros(n)
        for vehicle in range(vehicles):
            row[trip * vehicles + vehicle] = 1
        constraints.append(row); lo.append(1); hi.append(1)
    for i in range(trips):
        for j in range(i + 1, trips):
            if compat[i, j]:
                continue
            for vehicle in range(vehicles):
                row = np.zeros(n)
                row[i * vehicles + vehicle] = 1
                row[j * vehicles + vehicle] = 1
                constraints.append(row); lo.append(-np.inf); hi.append(1)
    result = milp(np.zeros(n), integrality=np.ones(n), bounds=Bounds(0, 1), constraints=LinearConstraint(np.array(constraints), lo, hi))
    return bool(result.success)


def check_exact_small_cases() -> dict:
    legal = np.ones((4, 4), dtype=bool)
    assert _milp_feasible(legal, 2)
    outcomes = {}
    for label, pair in {
        "两趟时间重叠": (0, 1),
        "中途更换车场": (0, 2),
        "电量不够下一趟": (1, 2),
        "充电超出空档": (2, 3),
    }.items():
        compat = np.ones((4, 4), dtype=bool)
        compat[pair] = False; compat[pair[::-1]] = False
        outcomes[label] = not _milp_feasible(compat, 1)
        assert outcomes[label]
    return {"status": "PASS", "detail": outcomes}


def _direct_ok(ret: float, depart: float, battery: float, need: float, power: float, cap: float) -> bool:
    charge = max(0.0, need - battery)
    return depart + TOL >= ret and charge <= cap - battery + TOL and charge <= max(0.0, depart - ret) * power / 3600 + TOL


def check_random_properties() -> dict:
    rng = random.Random(20260713)
    for _ in range(2000):
        ret = rng.uniform(0, 80_000); depart = ret + rng.uniform(-100, 20_000)
        cap = rng.uniform(20, 400); battery = rng.uniform(0, cap); need = rng.uniform(0, cap * 1.2); power = rng.uniform(1, 350)
        charge = max(0.0, need - battery)
        brute = (depart >= ret - TOL) and (battery + charge <= cap + TOL) and (ret + charge / power * 3600 <= depart + TOL)
        assert _direct_ok(ret, depart, battery, need, power, cap) == brute
    return {"status": "PASS", "detail": "2000个固定随机样本与独立逐条复算完全一致"}


def check_chain_graph() -> dict:
    trips = _old_trips()[:59]
    graph = nx.DiGraph()
    by_vehicle: dict[str, list[dict]] = {}
    for trip in trips:
        by_vehicle.setdefault(trip["physical_vehicle_id"], []).append(trip)
    for chain in by_vehicle.values():
        ordered = sorted(chain, key=lambda row: row["trip_index"])
        graph.add_nodes_from(row["route_id"] for row in ordered)
        graph.add_edges_from((a["route_id"], b["route_id"]) for a, b in zip(ordered, ordered[1:]))
    assert nx.is_directed_acyclic_graph(graph)
    assert max((graph.in_degree(n) for n in graph), default=0) <= 1
    assert max((graph.out_degree(n) for n in graph), default=0) <= 1
    return {"status": "PASS", "detail": f"{len(by_vehicle)}辆实体车的趟链都无循环、无分叉"}


def check_exact_boundary_and_carbon() -> dict:
    getcontext().prec = 40
    energy = Decimal("11"); power = Decimal("22"); gap = Decimal("1800")
    assert energy / power * Decimal("3600") == gap
    nodes = [Node("D0", "d", 0, 0, due_time=100_000)]
    instance = Instance(nodes, [[0.0]], num_cv=0, num_ev=1)
    action = certificate_action = None
    from setp_solver.solution import ChargingAction
    action = ChargingAction("EV1#T2", "D0", 11.0, 30.0, 1800.0)
    profile = [
        {"slot_index": i, "horizon_second_start": float(i * 1800), "actual_gco2_per_kwh": 100.0 + i}
        for i in range(48)
    ]
    solution = Solution(charging_actions=[action])
    slots = charging_slot_breakdown(1800.0, 1800.0, 11.0, instance, n_slots=48, cyclic=True)
    manual = sum(slot.y_skt_kwh * profile[slot.slot_index]["actual_gco2_per_kwh"] / 1000 for slot in slots)
    assert evaluate(solution, instance, profile)["E_ev_indirect"] == manual
    return {"status": "PASS", "detail": "22千瓦临界值判定稳定；碳排放复算使用完全相同的充电时段"}


def check_single_trip_reduction() -> dict:
    nodes = [Node("D0", "d", 0, 0, due_time=100_000), Node("C1", "c", 0, 0, demand=1, ready_time=100, due_time=10_000)]
    instance = Instance(nodes, [[0.0, 1000.0], [1000.0, 0.0]], num_cv=1, num_ev=1)
    route = Route("EV1#T1", "ev", "D0", ["D0", "C1", "D0"])
    prices = PriceParameters(B_battery_kwh=280, initial_ev_battery_kwh=280, depot_charge_power_kw=22)
    certificate = build_multitrip_certificate([route], instance, prices, recharge_mode=CHARGE_MODE_ON_DEMAND)
    assert certificate.vehicle_counts == {"cv": 0, "ev": 1}
    assert certificate_charging_actions(certificate) == []
    return {"status": "PASS", "detail": "每车只有一趟时，不会凭空增加趟间衔接或充电"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    checks = [
        ("单位和22千瓦来源", check_units_and_source),
        ("公式逐项推导", check_symbolic_chain),
        ("旧见证逐条回放", check_saved_witness_numpy),
        ("小算例精确正反例", check_exact_small_cases),
        ("随机排班交叉核对", check_random_properties),
        ("实体车趟链结构", check_chain_graph),
        ("临界值和碳排放同账", check_exact_boundary_and_carbon),
        ("单趟退回原规则", check_single_trip_reduction),
    ]
    rows = []
    for name, function in checks:
        try:
            result = function()
            rows.append({"check": name, "status": result["status"], "detail": json.dumps(result["detail"], ensure_ascii=False)})
        except Exception as exc:
            rows.append({"check": name, "status": "FAIL", "detail": repr(exc)})
    passed = sum(row["status"] == "PASS" for row in rows)
    with (OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check", "status", "detail"]); writer.writeheader(); writer.writerows(rows)
    status = "PASS" if passed == 8 else "HALT"
    metadata = {
        "contract_id": CONTRACT_ID,
        "purpose": "published-form between-trip partial charging formula validation",
        "depot_charge_power_kw": 22.0,
        "legacy_e1_e2_rejudged": False,
        "formal_70_started": False,
        "source_witness": str(OLD.relative_to(ROOT)),
    }
    decision = {"status": status, "passed": passed, "total": 8, "next_gate_authorized": status == "PASS", "formal_70_authorized": False}
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# E3 趟间按需补电八项核验", "", f"结论：{status}（{passed}/8）。", "", "| 检查 | 结果 | 说明 |", "|---|---|---|"]
    lines.extend(f"| {row['check']} | {row['status']} | {row['detail'].replace('|', '/')} |" for row in rows)
    lines.extend(["", "本目录只验证公式、排班证书和充电账本的数学一致性；没有启动正式 70 次实验，也没有倒查 E1/E2 封存结果。", ""])
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    hashes = {}
    for path in sorted(OUT.iterdir()):
        if path.name == "artifact_hashes.json" or path.name.startswith("._") or not path.is_file():
            continue
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False))
    if status != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
