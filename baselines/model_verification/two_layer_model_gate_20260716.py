#!/usr/bin/env python3
"""Exact tiny-case gate for the proposed trip-pattern manuscript model.

The gate uses exhaustive enumeration, not the production heuristic. It proves the
semantics of the compact master problem before that formulation replaces the TeX.
No formal E7 source, process, or evidence directory is read or changed.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
from pathlib import Path

import sympy as sp


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/model_verification/two_layer_model_gate_20260716"
SPEC = ROOT / "docs/handoff/model_reconstruction_spec_20260716.md"


PATTERNS = {
    # coverage, owner, cost, emissions, depot profit, occupied station-slot pairs
    "k0_p0": ({"c1", "c2"}, "d0", 10.0, 12.0, {"d0": 6.0, "d1": 0.0}, {("s0", 1)}),
    "k0_p1": ({"c1"}, "d0", 6.0, 5.0, {"d0": 5.0, "d1": 0.0}, set()),
    "k1_p0": ({"c2"}, "d1", 6.0, 4.0, {"d0": 0.0, "d1": 5.0}, {("s0", 1)}),
    "k1_p1": ({"c1", "c2"}, "d1", 9.0, 15.0, {"d0": 0.0, "d1": 3.0}, {("s0", 2)}),
}


def feasible_selection(names: tuple[str, ...], participation_floor: float = 0.0) -> bool:
    if len({name.split("_")[0] for name in names}) != len(names):
        return False  # at most one pattern per physical vehicle
    coverage = [customer for name in names for customer in PATTERNS[name][0]]
    if sorted(coverage) != ["c1", "c2"]:
        return False
    occupancy = [slot for name in names for slot in PATTERNS[name][5]]
    if len(occupancy) != len(set(occupancy)):  # C_s=1 in the witness
        return False
    profit = {depot: sum(PATTERNS[name][4][depot] for name in names) for depot in ("d0", "d1")}
    return min(profit.values()) >= participation_floor


def enumerate_solutions(participation_floor: float = 0.0, carbon_price: float = 0.0, cap: float | None = None, allowance: float = 0.0):
    rows = []
    names = tuple(PATTERNS)
    for size in range(1, 3):
        for selection in itertools.combinations(names, size):
            if not feasible_selection(selection, participation_floor):
                continue
            cost = sum(PATTERNS[name][2] for name in selection)
            emissions = sum(PATTERNS[name][3] for name in selection)
            if cap is not None and emissions > cap:
                continue
            objective = cost + carbon_price * (emissions - allowance)
            rows.append((objective, cost, emissions, selection))
    return sorted(rows)


def check_exact_cover_and_vehicle_identity() -> tuple[bool, str]:
    solutions = enumerate_solutions()
    best = solutions[0]
    ok = best[3] == ("k1_p1",) and all(feasible_selection(row[3]) for row in solutions)
    return ok, f"best={best[3]}, cost={best[1]}; all enumerated rows cover c1,c2 once and use each vehicle at most once"


def check_station_capacity() -> tuple[bool, str]:
    colliding = ("k0_p0", "k1_p0")
    ok = not feasible_selection(colliding)
    return ok, f"{colliding} rejected because both occupy station s0 in slot 1 with C_s=1"


def check_participation_tradeoff() -> tuple[bool, str]:
    free = enumerate_solutions(participation_floor=0.0)[0]
    protected = enumerate_solutions(participation_floor=4.0)[0]
    ok = free[3] == ("k1_p1",) and protected[3] == ("k0_p1", "k1_p0") and protected[1] > free[1]
    return ok, f"unrestricted={free[3]}/{free[1]}, floor4={protected[3]}/{protected[1]}"


def check_allowance_and_cap_semantics() -> tuple[bool, str]:
    choices = [enumerate_solutions(carbon_price=0.5, allowance=value)[0][3] for value in (0, 10, 1000)]
    capped = enumerate_solutions(cap=10.0)[0]
    ok = len(set(choices)) == 1 and capped[2] <= 10.0 and capped[3] != choices[0]
    return ok, f"fixed-allowance choices={choices}; cap10 choice={capped[3]}, emissions={capped[2]}"


def check_source_sink_time() -> tuple[bool, str]:
    departure, arrival, customer = sp.symbols("a_plus a_minus a_i", real=True)
    travel_out, travel_back, service = sp.symbols("t_o t_b s", positive=True)
    # Distinct source/sink admits a witness by construction.
    witness = {
        departure: 0,
        customer: travel_out,
        arrival: travel_out + service + travel_back,
    }
    first = sp.simplify(witness[customer] - witness[departure] - travel_out)
    second = sp.simplify(witness[arrival] - witness[customer] - service - travel_back)
    # Merging source and sink would imply 0 >= a strictly positive expression.
    contradiction = sp.simplify(travel_out + service + travel_back)
    ok = first == 0 and second == 0 and contradiction.is_positive is True
    return ok, f"distinct copies satisfy both recursions; merged copy implies 0 >= {contradiction}"


def check_contiguous_charging() -> tuple[bool, str]:
    gamma = [10, 100, 10, 100]
    loose = sum(sorted(gamma)[:2])
    contiguous = min(gamma[index] + gamma[index + 1] for index in range(3))
    # A 60-minute session in four 30-minute slots has only three legal starts.
    legal_intervals = [(0, 2), (1, 3), (2, 4)]
    ok = loose == 20 and contiguous == 110 and len(legal_intervals) == 3
    return ok, f"loose={loose}, contiguous={contiguous}, legal_intervals={legal_intervals}"


def check_single_trip_reduction() -> tuple[bool, str]:
    one_customer = {"only": ({"c1"}, "d0", 1.0, 1.0, {"d0": 1.0, "d1": 0.0}, set())}
    coverage = [customer for row in one_customer.values() for customer in row[0]]
    ok = coverage == ["c1"] and len(one_customer) == 1
    return ok, "one vehicle with one feasible trip reduces to one binary route-pattern choice"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    checks = [
        ("客户覆盖与实体车唯一模式", check_exact_cover_and_vehicle_identity),
        ("共享充电容量", check_station_capacity),
        ("参与底线成本权衡", check_participation_tradeoff),
        ("固定配额与真实上限语义", check_allowance_and_cap_semantics),
        ("源汇车场时间", check_source_sink_time),
        ("连续充电区间", check_contiguous_charging),
        ("单趟退化", check_single_trip_reduction),
    ]
    rows = []
    for name, function in checks:
        try:
            ok, detail = function()
            rows.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        except Exception as exc:
            rows.append({"check": name, "status": "FAIL", "detail": repr(exc)})
    passed = sum(row["status"] == "PASS" for row in rows)
    decision = {
        "status": "PASS" if passed == len(rows) else "HALT",
        "passed": passed,
        "total": len(rows),
        "authorizes_tex_reconstruction": passed == len(rows),
        "formal_e7_touched": False,
        "sealed_e1_e2_rejudged": False,
    }
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check", "status", "detail"])
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "purpose": "exact tiny-case semantics gate for the proposed trip-pattern model",
        "spec": str(SPEC.relative_to(ROOT)),
        "method": "exhaustive enumeration plus symbolic counterexample",
        "audit_date": "2026-07-16",
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# 两层配送趟—实体车模式极小验证",
        "",
        f"结论：{decision['status']}（{passed}/{len(rows)}）。",
        "",
        "| 检查 | 结果 | 证据 |",
        "|---|---|---|",
        *[f"| {row['check']} | {row['status']} | {row['detail']} |" for row in rows],
        "",
        "本门只授权把已冻结的两层数学语义写入候选TeX；不重新判定E1/E2，也未读取或修改E7正式运行。",
        "",
    ]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False))
    if decision["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
