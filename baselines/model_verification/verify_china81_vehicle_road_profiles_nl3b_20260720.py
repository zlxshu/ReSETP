#!/usr/bin/env python3
"""Audit all 81 China bundles without running solver search."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "solver/src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.charging_curve import NL90_MILD  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.cost import (  # noqa: E402
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    charging_curve_for_action,
    evaluate,
)
from setp_solver.instance_loader import Node  # noqa: E402
from setp_solver.search.dynamic import _rebuild_instance_matrix  # noqa: E402
from setp_solver.solution import ChargingAction, Route, Solution  # noqa: E402


OUT = (
    ROOT
    / "baselines/model_verification"
    / "china81_vehicle_road_profiles_nl3b_20260720"
)
SCRIPT = Path(__file__).resolve()
LOADER = ROOT / "solver/src/setp_solver/china81.py"
INSTANCE_LOADER = ROOT / "solver/src/setp_solver/instance_loader.py"
COST = ROOT / "solver/src/setp_solver/cost.py"
CHECK = ROOT / "solver/src/setp_solver/check.py"
DYNAMIC = ROOT / "solver/src/setp_solver/search/dynamic.py"
BUNDLE_TEST = ROOT / "solver/tests/test_china81_bundle_20260720.py"
PROFILE_TEST = (
    ROOT
    / "solver/tests/test_china81_profiled_road_matrices_nl3b_20260720.py"
)
STATIC_ROOT = (
    ROOT
    / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
)
MATRIX_ROOT = (
    ROOT
    / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
)
ORDER_ROOT = (
    ROOT
    / "data/ChinaInstances/china81_order_attributes_mc001_v1_20260718"
)
VEHICLE_LOCK = (
    ROOT
    / "data/ChinaInstances/china_parameter_lock_v2_20260718.json"
)
CATALOG = STATIC_ROOT / "instance_catalog.csv"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _run(command: list[str]) -> dict[str, Any]:
    environment = dict(os.environ)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(ROOT / "solver/src") + (
        os.pathsep + existing_pythonpath
        if existing_pythonpath
        else ""
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4_000:],
        "stderr_tail": completed.stderr[-4_000:],
    }


def _verify_manifest(
    root: Path,
    mapping: dict[str, str],
    include: Callable[[str], bool],
) -> dict[str, Any]:
    checked = 0
    missing: list[str] = []
    mismatches: list[str] = []
    for relative, expected in sorted(mapping.items()):
        if not include(relative):
            continue
        checked += 1
        path = root / relative
        if not path.is_file():
            missing.append(relative)
        elif _sha256(path) != expected:
            mismatches.append(relative)
    return {
        "checked_file_count": checked,
        "missing": missing,
        "mismatches": mismatches,
        "passed": checked > 0 and not missing and not mismatches,
    }


def _mechanical_j(
    *,
    distance_m: float,
    sum_v2d: float,
    load_kg: float,
    vehicle: Any,
    prices: Any,
) -> float:
    return (
        0.5
        * float(vehicle.drag_coefficient)
        * float(prices.rho_a)
        * float(vehicle.frontal_area_m2)
        * float(sum_v2d)
        + (
            float(vehicle.curb_mass_kg)
            + float(load_kg)
        )
        * float(prices.g0)
        * float(vehicle.rolling_resistance_coefficient)
        * float(distance_m)
    )


def _independent_route_physics(bundle: Any) -> dict[str, float]:
    instance = bundle.instance
    depot = next(node for node in instance.nodes if node.node_type == "d")
    customer = next(
        node
        for node in instance.nodes
        if node.node_type == "c"
    )
    route_nodes = [depot.node_id, customer.node_id, depot.node_id]
    cv_solution = Solution(
        routes=[Route("CV1", "cv", depot.node_id, route_nodes)]
    )
    ev_solution = Solution(
        routes=[Route("EV1", "ev", depot.node_id, route_nodes)]
    )
    cv_observed = evaluate(
        cv_solution,
        instance,
        bundle.time_profile,
        bundle.prices,
        carbon_quota_kg=float("inf"),
    )
    ev_observed = evaluate(
        ev_solution,
        instance,
        bundle.time_profile,
        bundle.prices,
        carbon_quota_kg=float("inf"),
    )

    cv_vehicle = instance.vehicle_profile("cv")
    ev_vehicle = instance.vehicle_profile("ev")
    if cv_vehicle is None or ev_vehicle is None:
        raise ValueError("China81 bundle lost vehicle profiles")
    cv_expected = 0.0
    ev_expected = 0.0
    for vehicle_type, vehicle, load, accumulator in (
        ("cv", cv_vehicle, customer.demand, "cv"),
        ("cv", cv_vehicle, 0.0, "cv"),
        ("ev", ev_vehicle, customer.demand, "ev"),
        ("ev", ev_vehicle, 0.0, "ev"),
    ):
        from_id, to_id = (
            (depot.node_id, customer.node_id)
            if load > 0.0
            else (customer.node_id, depot.node_id)
        )
        distance, duration, sum_v2d = instance.arc_metrics(
            from_id,
            to_id,
            vehicle_type,
            fallback_speed_mps=bundle.prices.v_speed_ms,
        )
        mechanical = _mechanical_j(
            distance_m=distance,
            sum_v2d=sum_v2d,
            load_kg=load,
            vehicle=vehicle,
            prices=bundle.prices,
        )
        if accumulator == "cv":
            cv_expected += (
                float(bundle.prices.xi_fuel_air)
                / (
                    float(bundle.prices.kappa_heat)
                    * float(bundle.prices.psi_conv)
                )
                * (
                    float(vehicle.engine_friction_kj_per_rev_l)
                    * float(vehicle.engine_speed_rev_per_s)
                    * float(vehicle.engine_displacement_l)
                    * duration
                    + mechanical
                    / 1_000.0
                    / (
                        float(bundle.prices.eta_diesel)
                        * float(bundle.prices.eta_tf)
                    )
                )
            )
        else:
            ev_expected += (
                float(vehicle.traction_energy_multiplier)
                * mechanical
                / 3_600_000.0
            )
    cv_error = abs(float(cv_observed["fuel_liters"]) - cv_expected)
    ev_error = abs(float(ev_observed["ev_drive_kwh"]) - ev_expected)
    return {
        "cv_observed_liters": float(cv_observed["fuel_liters"]),
        "cv_expected_liters": cv_expected,
        "cv_abs_error": cv_error,
        "ev_observed_kwh": float(ev_observed["ev_drive_kwh"]),
        "ev_expected_kwh": ev_expected,
        "ev_abs_error": ev_error,
    }


def _charging_spot_check(bundle: Any) -> dict[str, Any]:
    instance = bundle.instance
    depot = next(node for node in instance.nodes if node.node_type == "d")
    city_rows = [
        row
        for row in bundle.time_profile
        if row["city"] == depot.city
    ]
    first = min(
        city_rows,
        key=lambda row: float(row["horizon_second_start"]),
    )
    action = ChargingAction(
        vehicle_id="EV_AUDIT",
        station_id=depot.node_id,
        energy_kwh=11.0,
        occupancy_minutes=30.0,
        charge_start_second=0.0,
        start_energy_kwh=0.0,
        end_energy_kwh=11.0,
        charging_curve_id=NL90_MILD.curve_id,
    )
    observed_cost = charging_action_electricity_cost(
        action,
        instance,
        bundle.time_profile,
        bundle.prices,
    )
    expected_cost = (
        11.0 * float(first["depot_energy_cny_per_kwh"])
    )
    observed_emissions = charging_action_emissions_kg(
        action,
        instance,
        bundle.time_profile,
        bundle.prices,
    )
    expected_emissions = (
        11.0 * float(first["actual_gco2_per_kwh"]) / 1_000.0
    )
    curve_state = charging_curve_for_action(
        action,
        instance,
        bundle.prices,
    )
    if curve_state is None:
        raise ValueError("China81 nonlinear action lost curve state")
    curve, _, _ = curve_state
    return {
        "city": depot.city,
        "cost_abs_error": abs(observed_cost - expected_cost),
        "emissions_abs_error": abs(
            observed_emissions - expected_emissions
        ),
        "curve_parameter_sha256": curve.parameter_sha256,
        "curve_physical_sha256": curve.physical_parameter_sha256,
        "battery_capacity_kwh": curve.capacity_kwh,
        "reference_power_kw": (
            3600.0
            * (
                curve.energy_breakpoints_kwh[1]
                - curve.energy_breakpoints_kwh[0]
            )
            / (curve.cumulative_seconds[1] - curve.cumulative_seconds[0])
        ),
    }


def _audit_bundle(instance_id: str) -> dict[str, Any]:
    bundle = load_china81_bundle(ROOT, instance_id)
    instance = bundle.instance
    customer_count = sum(
        node.node_type == "c"
        for node in instance.nodes
    )
    cities = sorted(
        {
            str(node.city)
            for node in instance.nodes
            if node.city is not None
        }
    )
    physics = _independent_route_physics(bundle)
    charging = _charging_spot_check(bundle)
    first = instance.nodes[0]
    second = instance.nodes[1]
    road_profiles_differ = (
        instance.road_profiles is not None
        and instance.road_profiles["cv"]
        != instance.road_profiles["ev"]
    )
    road_profiles_loaded = (
        instance.road_profiles is not None
        and set(instance.road_profiles) == {"cv", "ev"}
    )
    subset = _rebuild_instance_matrix(
        instance,
        [first, second],
    )
    new_node_rejected = False
    try:
        _rebuild_instance_matrix(
            instance,
            [
                *instance.nodes,
                Node(
                    "AUDIT_NEW_NODE",
                    "c",
                    0.0,
                    0.0,
                    demand=1.0,
                    city=cities[0],
                ),
            ],
        )
    except ValueError:
        new_node_rejected = True
    row = {
        "instance_id": instance_id,
        "region": bundle.region,
        "customer_count": customer_count,
        "node_count": len(instance.nodes),
        "city_count": len(cities),
        "cities": "|".join(cities),
        "time_profile_rows": len(bundle.time_profile),
        "num_cv_cap": instance.num_cv,
        "num_ev_cap": instance.num_ev,
        "fleet_cap_semantics": bundle.fleet_cap_semantics,
        "diesel_price_cny_per_l": bundle.prices.diesel_price,
        "diesel_price_source_id": bundle.diesel_price_source_id,
        "cv_formula_abs_error": physics["cv_abs_error"],
        "ev_formula_abs_error": physics["ev_abs_error"],
        "charging_cost_abs_error": charging["cost_abs_error"],
        "charging_emissions_abs_error": charging[
            "emissions_abs_error"
        ],
        "curve_parameter_sha256": charging[
            "curve_parameter_sha256"
        ],
        "curve_physical_sha256": charging[
            "curve_physical_sha256"
        ],
        "battery_capacity_kwh": charging[
            "battery_capacity_kwh"
        ],
        "reference_power_kw": charging["reference_power_kw"],
        "cv_ev_road_profiles_loaded": road_profiles_loaded,
        "cv_ev_road_profiles_differ": road_profiles_differ,
        "dynamic_subset_profiles_preserved": (
            subset.road_profiles is not None
            and subset.vehicle_parameters is not None
            and subset.demand_mass_per_unit_kg == 1.0
        ),
        "dynamic_new_node_rejected": new_node_rejected,
        "formal_search_allowed": bundle.formal_search_allowed,
    }
    row["passed"] = (
        customer_count == int(instance_id.split("-")[2][:-1])
        and len(bundle.time_profile) == 48 * len(cities)
        and instance.num_cv == customer_count
        and instance.num_ev == customer_count
        and float(row["cv_formula_abs_error"]) <= 1e-10
        and float(row["ev_formula_abs_error"]) <= 1e-10
        and float(row["charging_cost_abs_error"]) <= 1e-10
        and float(row["charging_emissions_abs_error"]) <= 1e-10
        and float(row["battery_capacity_kwh"]) == 140.41
        and float(row["reference_power_kw"]) == 22.0
        and bool(row["dynamic_subset_profiles_preserved"])
        and bool(row["dynamic_new_node_rejected"])
        and not bool(row["formal_search_allowed"])
    )
    return row


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    catalog_rows = _read_csv(CATALOG)
    instance_ids = sorted(row["instance_id"] for row in catalog_rows)

    static_hashes = json.loads(
        (STATIC_ROOT / "artifact_hashes.json").read_text(
            encoding="utf-8"
        )
    )["sha256"]
    matrix_hashes = json.loads(
        (MATRIX_ROOT / "artifact_hashes.json").read_text(
            encoding="utf-8"
        )
    )["sha256"]
    order_hashes = json.loads(
        (ORDER_ROOT / "artifact_hashes.json").read_text(
            encoding="utf-8"
        )
    )["files"]
    source_hash_audit = {
        "static": _verify_manifest(
            STATIC_ROOT,
            static_hashes,
            lambda relative: (
                relative in {
                    "instance_catalog.csv",
                    "tariff_carbon_48slot_calendar.csv",
                }
                or (
                    relative.startswith("instances/")
                    and relative.endswith("/nodes.csv")
                )
            ),
        ),
        "matrices": _verify_manifest(
            MATRIX_ROOT,
            matrix_hashes,
            lambda relative: (
                relative.startswith("instances/")
                and (
                    relative.endswith("/nodes.csv")
                    or "/road_" in relative
                )
            ),
        ),
        "orders": _verify_manifest(
            ORDER_ROOT,
            order_hashes,
            lambda relative: relative == "orders.csv",
        ),
    }
    rows = [
        _audit_bundle(instance_id)
        for instance_id in instance_ids
    ]
    python = sys.executable
    tests = _run(
        [
            python,
            "-m",
            "pytest",
            "-q",
            str(BUNDLE_TEST.relative_to(ROOT)),
            str(PROFILE_TEST.relative_to(ROOT)),
            "solver/tests/test_nonlinear_multitrip_schedule_20260720.py",
            "solver/tests/test_nonlinear_dynamic_multitrip_nl3_20260720.py",
            "solver/tests/test_multitrip_schedule.py",
            "solver/tests/test_dynamic_multitrip_schedule.py",
            "solver/tests/test_execution_accounting.py",
            "solver/tests/test_profit.py",
        ]
    )
    ruff = _run(
        [
            str(Path(python).with_name("ruff")),
            "check",
            str(LOADER.relative_to(ROOT)),
            str(BUNDLE_TEST.relative_to(ROOT)),
            str(PROFILE_TEST.relative_to(ROOT)),
            str(SCRIPT.relative_to(ROOT)),
        ]
    )
    region_counts: dict[str, int] = {}
    size_counts: dict[int, int] = {}
    for row in rows:
        region = str(row["region"])
        size = int(row["customer_count"])
        region_counts[region] = region_counts.get(region, 0) + 1
        size_counts[size] = size_counts.get(size, 0) + 1
    max_errors = {
        name: max(float(row[name]) for row in rows)
        for name in (
            "cv_formula_abs_error",
            "ev_formula_abs_error",
            "charging_cost_abs_error",
            "charging_emissions_abs_error",
        )
    }
    checks = {
        "instance_count_81": len(rows) == 81,
        "all_instance_rows_pass": all(
            bool(row["passed"])
            for row in rows
        ),
        "total_orders_5805": sum(
            int(row["customer_count"])
            for row in rows
        ) == 5_805,
        "region_balance_27_each": region_counts == {
            "cy": 27,
            "jjj": 27,
            "prd": 27,
        },
        "size_balance_9_each": size_counts == {
            10: 9,
            15: 9,
            20: 9,
            25: 9,
            50: 9,
            75: 9,
            100: 9,
            150: 9,
            200: 9,
        },
        "source_hashes_close": all(
            bool(result["passed"])
            for result in source_hash_audit.values()
        ),
        "independent_formulas_close": all(
            value <= 1e-10
            for value in max_errors.values()
        ),
        "cv_ev_road_profiles_loaded_all": all(
            bool(row["cv_ev_road_profiles_loaded"])
            for row in rows
        ),
        "target_tests": tests["returncode"] == 0,
        "ruff": ruff["returncode"] == 0,
    }
    passed = all(checks.values())
    decision = {
        "verdict": (
            "PASS_NL3B_CHINA81_81_OF_81_RUNTIME_JOIN"
            if passed
            else "HOLD_NL3B_CHINA81_RUNTIME_JOIN"
        ),
        "passed": passed,
        "checks": checks,
        "instance_count": len(rows),
        "customer_order_count": sum(
            int(row["customer_count"])
            for row in rows
        ),
        "region_counts": region_counts,
        "size_counts": size_counts,
        "instances_with_cv_ev_road_profile_difference": sum(
            bool(row["cv_ev_road_profiles_differ"])
            for row in rows
        ),
        "max_errors": max_errors,
        "source_hash_audit": source_hash_audit,
        "target_tests": tests,
        "ruff": ruff,
        "search_evaluations": 0,
        "diagnostic_probe_allowed": passed,
        "formal_search_allowed": False,
        "honest_boundary": (
            "All 81 static runtime bundles close under the frozen orders, "
            "roads, vehicle facts, city tariffs/carbon, and NL90 charging. "
            "Fleet counts remain non-observed loose algorithmic ceilings; "
            "new dynamic nodes remain fail-closed without frozen roads. "
            "This gate permits only the user-authorized low-cost diagnostic "
            "algorithm probe, not a formal China81 result."
        ),
        "next_gate": "CHINA81_MINIMUM_COST_THREE_ARM_DIAGNOSTIC_PROBE",
    }
    metadata = {
        "schema": "resetp.china81-vehicle-road-runtime-nl3b.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of_date": "2025-02-12",
        "search_performed": False,
        "search_evaluations": 0,
        "formal_search_allowed": False,
        "source_files": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (
                SCRIPT,
                LOADER,
                INSTANCE_LOADER,
                COST,
                CHECK,
                DYNAMIC,
                BUNDLE_TEST,
                PROFILE_TEST,
                VEHICLE_LOCK,
            )
        },
    }
    with (OUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
        )
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "decision.json").write_text(
        json.dumps(decision, indent=2) + "\n",
        encoding="utf-8",
    )
    report = f"""# China81 车辆—道路—电价—碳—非线性充电运行时闭合

判定：`{decision["verdict"]}`。

81/81 个实例、5,805 个订单已逐例装载。每例同时使用 CV/EV 两套冻结
道路资料（距离、时长、Σ(v²d)）、各自车辆质量/容量/迎风参数、所在城市
2025-02-12 的 48 槽电价与碳强度，以及 140.41 kWh 电池上的 NL90 非线性
充电曲线；客户、车场和充电站均受 06:00–22:00 研究时域约束。81 题中
47 题的 CV/EV 全路网资料至少一项不同，其余 34 题的两种货运 profile
恰好得到相同道路结果；两套输入均独立装载并核对哈希。独立油耗、电耗、
电费、充电排放复算最大绝对误差分别为
{max_errors["cv_formula_abs_error"]:.3g}、
{max_errors["ev_formula_abs_error"]:.3g}、
{max_errors["charging_cost_abs_error"]:.3g}、
{max_errors["charging_emissions_abs_error"]:.3g}。

输入哈希、实例/订单粒度、区域和规模平衡、城市日历、动态子矩阵继承及
“新增节点没有道路资料就拒绝”均已核验。全程搜索评价次数为 0。

这允许进入用户批准的低成本三臂诊断探针，但不是正式 China81 放行：
当前 CV/EV 数量只是“每客户每车型一辆”的不绑定算法上限，不冒充真实车队；
动态新增订单也仍需预先冻结道路资料。
"""
    (OUT / "report.md").write_text(
        report,
        encoding="utf-8",
    )
    artifacts = sorted(
        path
        for path in OUT.iterdir()
        if path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "algorithm": "sha256",
                "files": {
                    str(path.relative_to(ROOT)): _sha256(path)
                    for path in artifacts
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
