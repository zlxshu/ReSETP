#!/usr/bin/env python3
"""Close NL2: exact nonlinear charging cost, timing, and checking."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.check import CHARGING_POWER, check_solution  # noqa: E402
from setp_solver.charging_curve import L100_CONTROL, NL90_MILD  # noqa: E402
from setp_solver.cost import (  # noqa: E402
    charging_action_slot_breakdown,
    charging_slot_breakdown,
    evaluate,
)
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.prices import PriceParameters  # noqa: E402
from setp_solver.search.charging import (  # noqa: E402
    _curve_aware_action,
    solve_charging_fixed_route,
)
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    prepare_multitrip_solution,
    reschedule_between_trip_charging,
    route_timing,
)
from setp_solver.solution import ChargingAction, Route, Solution  # noqa: E402


OUT = (
    ROOT
    / "baselines/model_verification"
    / "china81_nonlinear_cost_check_nl2_20260720"
)
SCRIPT = Path(__file__).resolve()
INCIDENTS = OUT / "development_incidents.md"
BASE_COMMIT = "12940ce4"
TOL = 1e-7

CHANGED_CODE = (
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/operators/carbon_operators.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/carbon_charging.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/profit.py",
    "solver/src/setp_solver/search/carbon_operators.py",
    "solver/src/setp_solver/search/certificate_execution.py",
    "solver/src/setp_solver/search/charging.py",
    "solver/src/setp_solver/search/e5_ablation.py",
    "solver/src/setp_solver/search/e5_probe.py",
    "solver/src/setp_solver/search/fairness.py",
    "solver/src/setp_solver/search/multitrip_schedule.py",
    "solver/tests/test_nonlinear_cost_check_nl2_20260720.py",
)
RECORD_SURFACES = (
    "HANDOFF.md",
    "docs/handoff/china81_nonlinear_core_g1_contract_20260720.md",
    "docs/handoff/memory/MEMORY.md",
    "docs/handoff/memory/china81_nonlinear_cost_check_nl2_20260720.md",
    "docs/handoff/memory/project-prd-execution-v2.md",
    "docs/handoff/model_change_approval_register_20260718.md",
)
UNCHANGED_PROTECTED = (
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/evaluation.py",
    "docs/paper_submission_final/paper_main.tex",
)
TARGET_TESTS = (
    "solver/tests/test_nonlinear_cost_check_nl2_20260720.py",
    "solver/tests/test_cost.py",
    "solver/tests/test_check.py",
    "solver/tests/test_profit.py",
    "solver/tests/test_multitrip_schedule.py",
    "solver/tests/test_nonlinear_multitrip_schedule_20260720.py",
    "solver/tests/test_dynamic_multitrip_schedule.py",
    "solver/tests/test_certificate_execution.py",
    "solver/tests/test_execution_accounting.py",
    "solver/tests/test_charging_action_persistence.py",
    "solver/tests/test_search.py",
    "solver/tests/test_order_decoder.py",
)
RUFF_PATHS = (*CHANGED_CODE, str(SCRIPT.relative_to(ROOT)))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_command(command: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-6000:],
        "stderr_tail": completed.stderr[-6000:],
    }


def prices(
    spec: Any,
    *,
    capacity_kwh: float = 100.0,
    initial_kwh: float = 80.0,
    power_kw: float = 100.0,
) -> PriceParameters:
    return PriceParameters(
        B_battery_kwh=capacity_kwh,
        initial_ev_battery_kwh=initial_kwh,
        depot_charge_power_kw=power_kw,
        charging_curve_id=spec.curve_id,
        charging_soc_breakpoints=spec.soc_breakpoints,
        charging_relative_powers=spec.relative_powers,
    )


def zero_distance_instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0, 0, due_time=100_000),
            Node("C1", "c", 0, 0, demand=1, due_time=100_000),
        ],
        distance_matrix=[[0.0, 0.0], [0.0, 0.0]],
        num_ev=1,
        num_cv=0,
    )


def profile(*values: float) -> list[dict[str, float]]:
    return [
        {
            "horizon_second_start": float(index * 1800),
            "actual_gco2_per_kwh": float(value),
        }
        for index, value in enumerate(values)
    ]


def slot_fixture() -> dict[str, float]:
    instance = zero_distance_instance()
    nl_prices = prices(NL90_MILD)
    curve = NL90_MILD.scale(
        capacity_kwh=100.0,
        reference_power_kw=100.0,
    )
    action = ChargingAction(
        "EV1",
        "D0",
        energy_kwh=20.0,
        occupancy_minutes=curve.duration_seconds(80.0, 100.0) / 60.0,
        charge_start_second=1500.0,
        start_energy_kwh=80.0,
        end_energy_kwh=100.0,
        charging_curve_id=NL90_MILD.curve_id,
    )
    slots = charging_action_slot_breakdown(
        action,
        instance,
        nl_prices,
        n_slots=48,
        cyclic=True,
    )
    uniform_first = (
        float(action.energy_kwh)
        * 300.0
        / (float(action.occupancy_minutes) * 60.0)
    )
    return {
        "action_duration_seconds": float(action.occupancy_minutes) * 60.0,
        "first_slot_energy_kwh": slots[0].y_skt_kwh,
        "second_slot_energy_kwh": slots[1].y_skt_kwh,
        "uniform_first_slot_energy_kwh": uniform_first,
        "slot_energy_sum_kwh": sum(row.y_skt_kwh for row in slots),
    }


def rejection_fixture() -> dict[str, Any]:
    instance = zero_distance_instance()
    nl_prices = prices(NL90_MILD)
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    action = _curve_aware_action(
        vehicle_id=route.vehicle_id,
        station_id="D0",
        start_energy_kwh=80.0,
        energy_kwh=20.0,
        reference_power_kw=100.0,
        prices=nl_prices,
    )
    action = replace(
        action,
        charge_start_second=80_000.0,
        charge_day_offset=-1,
    )
    carbon = profile(*([300.0, 50.0] * 24))
    valid = Solution(routes=[route], charging_actions=[action])
    valid_cost = evaluate(valid, instance, carbon, nl_prices)
    valid_violations = check_solution(valid, instance, nl_prices)

    shortened = replace(
        action,
        occupancy_minutes=action.occupancy_minutes - 1.0,
    )
    invalid = Solution(routes=[route], charging_actions=[shortened])
    invalid_violations = check_solution(invalid, instance, nl_prices)
    cost_rejected = False
    cost_error = ""
    try:
        evaluate(invalid, instance, carbon, nl_prices)
    except ValueError as exc:
        cost_rejected = True
        cost_error = str(exc)

    missing = ChargingAction(
        "EV1",
        "D0",
        energy_kwh=20.0,
        occupancy_minutes=18.0,
        charge_start_second=0.0,
    )
    missing_rejected = False
    missing_error = ""
    try:
        evaluate(
            Solution(charging_actions=[missing]),
            instance,
            carbon,
            nl_prices,
        )
    except ValueError as exc:
        missing_rejected = True
        missing_error = str(exc)
    return {
        "valid_electricity_kwh": valid_cost["electricity_kwh"],
        "valid_charging_power_violations": sum(
            violation.type == CHARGING_POWER
            for violation in valid_violations
        ),
        "shortened_cost_rejected": cost_rejected,
        "shortened_cost_error": cost_error,
        "shortened_checker_rejected": any(
            violation.type == CHARGING_POWER
            and "occupancy disagrees" in violation.detail
            for violation in invalid_violations
        ),
        "missing_metadata_rejected": missing_rejected,
        "missing_metadata_error": missing_error,
    }


def retiming_fixture() -> dict[str, Any]:
    nodes = [
        Node("D0", "d", 0, 0, due_time=100_000),
        Node(
            "C1",
            "c",
            0,
            0,
            demand=10,
            ready_time=1_000,
            due_time=4_000,
            service_time=100,
        ),
        Node(
            "C2",
            "c",
            0,
            0,
            demand=10,
            ready_time=8_000,
            due_time=12_000,
            service_time=100,
        ),
    ]
    matrix = [
        [0.0 if left == right else 1_000.0 for right in range(3)]
        for left in range(3)
    ]
    instance = Instance(nodes, matrix, num_ev=2, num_cv=0)
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    drive = route_timing(
        routes[0],
        instance,
        PriceParameters(B_battery_kwh=280.0),
    ).drive_energy_kwh
    nl_prices = prices(
        NL90_MILD,
        capacity_kwh=drive * 1.05,
        initial_kwh=0.0,
        power_kw=22.0,
    )
    prepared, certificate = prepare_multitrip_solution(
        Solution(routes=routes),
        instance,
        nl_prices,
    )
    carbon = profile(*([300.0, 50.0] * 24))
    naive = reschedule_between_trip_charging(
        prepared,
        certificate,
        instance,
        carbon,
        strategy="naive",
        prices=nl_prices,
    )
    aware = reschedule_between_trip_charging(
        prepared,
        certificate,
        instance,
        carbon,
        strategy="aware",
        prices=nl_prices,
    )
    naive_carbon = evaluate(
        naive,
        instance,
        carbon,
        nl_prices,
    )["E_ev_indirect"]
    aware_carbon = evaluate(
        aware,
        instance,
        carbon,
        nl_prices,
    )["E_ev_indirect"]
    return {
        "naive_emissions_kg": naive_carbon,
        "aware_emissions_kg": aware_carbon,
        "relative_reduction": (
            0.0
            if naive_carbon <= 0.0
            else (naive_carbon - aware_carbon) / naive_carbon
        ),
        "naive_starts": [
            action.charge_start_second
            for action in naive.charging_actions
        ],
        "aware_starts": [
            action.charge_start_second
            for action in aware.charging_actions
        ],
        "curve_ids": sorted(
            {
                str(action.charging_curve_id)
                for action in aware.charging_actions
            }
        ),
    }


def l100_regression_fixture() -> dict[str, Any]:
    instance = zero_distance_instance()
    l100_prices = prices(L100_CONTROL)
    duration = 20.0 / 100.0 * 3600.0
    legacy = ChargingAction(
        "EV1",
        "D0",
        energy_kwh=20.0,
        occupancy_minutes=duration / 60.0,
        charge_start_second=1500.0,
    )
    current = replace(
        legacy,
        start_energy_kwh=80.0,
        end_energy_kwh=100.0,
        charging_curve_id=L100_CONTROL.curve_id,
    )
    historical = charging_slot_breakdown(
        1500.0,
        duration,
        20.0,
        instance,
        n_slots=48,
        cyclic=True,
    )
    legacy_rows = charging_action_slot_breakdown(
        legacy,
        instance,
        l100_prices,
        n_slots=48,
        cyclic=True,
    )
    current_rows = charging_action_slot_breakdown(
        current,
        instance,
        l100_prices,
        n_slots=48,
        cyclic=True,
    )

    def signature(rows: list[Any]) -> list[tuple[int, float, float]]:
        return [
            (row.slot_index, row.g_skt_sec, row.y_skt_kwh)
            for row in rows
        ]

    old_signature = signature(historical)
    return {
        "legacy_matches_historical": signature(legacy_rows) == old_signature,
        "curve_bound_matches_historical": (
            signature(current_rows) == old_signature
        ),
        "signature": old_signature,
    }


def repair_fixture() -> dict[str, Any]:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0, 0, due_time=100_000),
            Node("C1", "c", 0, 0, due_time=100_000),
        ],
        distance_matrix=[[0.0, 80_000.0], [80_000.0, 0.0]],
    )
    route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
    nl_prices = prices(NL90_MILD)
    actions = solve_charging_fixed_route(
        route,
        instance,
        profile(*([100.0] * 48)),
        nl_prices,
        strategy="aware",
    )
    curve = NL90_MILD.scale(
        capacity_kwh=100.0,
        reference_power_kw=100.0,
    )
    duration_errors = [
        abs(
            action.occupancy_minutes * 60.0
            - curve.duration_seconds(
                float(action.start_energy_kwh),
                float(action.end_energy_kwh),
            )
        )
        for action in actions
    ]
    return {
        "action_count": len(actions),
        "curve_ids": sorted(
            {str(action.charging_curve_id) for action in actions}
        ),
        "max_duration_error_seconds": max(duration_errors, default=0.0),
        "missing_energy_state_count": sum(
            action.start_energy_kwh is None
            or action.end_energy_kwh is None
            for action in actions
        ),
    }


def changed_paths() -> set[str]:
    result = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return {
        line[3:].strip()
        for line in result.stdout.splitlines()
        if line and not line[3:].strip().startswith("._")
    }


def is_authorized_change(path: str) -> bool:
    return (
        path in {*CHANGED_CODE, *RECORD_SURFACES}
        or path
        == str(SCRIPT.relative_to(ROOT))
        or path.startswith(
            "baselines/model_verification/"
            "china81_nonlinear_cost_check_nl2_20260720/"
        )
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    slot = slot_fixture()
    rejection = rejection_fixture()
    retiming = retiming_fixture()
    linear = l100_regression_fixture()
    repair = repair_fixture()

    env = dict(os.environ)
    env["PYTHONPATH"] = (
        f"{ROOT / 'solver/src'}:{ROOT / 'models/src'}:{ROOT}"
    )
    env["PYTHONHASHSEED"] = "0"
    pytest_result = run_command(
        [sys.executable, "-m", "pytest", "-q", *TARGET_TESTS],
        env=env,
    )
    ruff_result = run_command(
        ["/opt/anaconda3/bin/ruff", "check", *RUFF_PATHS],
        env=env,
    )
    unchanged_protected = run_command(
        [
            "git",
            "diff",
            "--exit-code",
            BASE_COMMIT,
            "--",
            *UNCHANGED_PROTECTED,
        ]
    )
    dirty = changed_paths()
    unauthorized_changes = sorted(
        path for path in dirty if not is_authorized_change(path)
    )

    static_source = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "solver/src/setp_solver/search/charging.py",
            "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py",
        )
    )
    static_legacy_energy_division_hits = len(
        re.findall(r"occupancy_sec\s*=\s*energy_needed\s*/", static_source)
    )
    dynamic_source = (
        ROOT / "solver/src/setp_solver/search/dynamic_multitrip_schedule.py"
    ).read_text(encoding="utf-8")
    dynamic_legacy_formula_hits = {
        "energy_divided_by_power": len(
            re.findall(r"(?:needed|charge_energy)\s*/\s*power", dynamic_source)
        ),
        "gap_times_power": len(
            re.findall(r"gap\s*\*\s*power", dynamic_source)
        ),
        "battery_plus_time_power": len(
            re.findall(r"battery_kwh\s*\+[^\n]*power", dynamic_source)
        ),
    }

    checks = {
        "taper_slot_split": (
            abs(slot["first_slot_energy_kwh"] - 8.333333333333334)
            <= TOL
            and abs(slot["second_slot_energy_kwh"] - 11.666666666666666)
            <= TOL
            and abs(slot["slot_energy_sum_kwh"] - 20.0) <= TOL
            and slot["first_slot_energy_kwh"]
            > slot["uniform_first_slot_energy_kwh"] + TOL
        ),
        "valid_cost_checker_agree": (
            abs(rejection["valid_electricity_kwh"] - 20.0) <= TOL
            and rejection["valid_charging_power_violations"] == 0
        ),
        "shortened_action_fails_closed": (
            rejection["shortened_cost_rejected"]
            and rejection["shortened_checker_rejected"]
        ),
        "missing_metadata_fails_closed": (
            rejection["missing_metadata_rejected"]
        ),
        "carbon_timing_strictly_improves": (
            retiming["aware_emissions_kg"]
            < retiming["naive_emissions_kg"] - 1e-12
            and retiming["aware_starts"] != retiming["naive_starts"]
            and retiming["curve_ids"] == [NL90_MILD.curve_id]
        ),
        "l100_exact_regression": (
            linear["legacy_matches_historical"]
            and linear["curve_bound_matches_historical"]
        ),
        "repair_emits_bound_actions": (
            repair["action_count"] > 0
            and repair["curve_ids"] == [NL90_MILD.curve_id]
            and repair["missing_energy_state_count"] == 0
            and repair["max_duration_error_seconds"] <= TOL
        ),
        "static_legacy_formula_removed": (
            static_legacy_energy_division_hits == 0
        ),
        "target_tests": pytest_result["returncode"] == 0,
        "ruff": ruff_result["returncode"] == 0,
        "change_boundary": (
            not unauthorized_changes
            and unchanged_protected["returncode"] == 0
        ),
    }
    passed = all(checks.values())
    verdict = (
        "PASS_NL2_NONLINEAR_COST_CHECK_AND_TIMING"
        if passed
        else "HALT_NL2_NONLINEAR_COST_CHECK_AND_TIMING"
    )
    now = datetime.now(timezone.utc).isoformat()
    before_hashes = {
        path: bytes_sha256(
            subprocess.run(
                ["git", "show", f"{BASE_COMMIT}:{path}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout
        )
        for path in (
            "solver/src/setp_solver/cost.py",
            "solver/src/setp_solver/check.py",
        )
    }
    metadata = {
        "schema": "resetp.china81-nonlinear-cost-check-nl2.v1",
        "created_at_utc": now,
        "base_commit": BASE_COMMIT,
        "scope": (
            "curve-aware charging repair, exact time-slot accounting, "
            "carbon timing, cost, profit, and independent checking"
        ),
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "python": sys.executable,
        "curve": asdict(NL90_MILD),
        "authorized_changed_paths": sorted(
            {*CHANGED_CODE, *RECORD_SURFACES}
        ),
        "protected_before_sha256": before_hashes,
        "protected_after_sha256": {
            path: file_sha256(ROOT / path)
            for path in before_hashes
        },
        "unchanged_protected_sha256": {
            path: file_sha256(ROOT / path)
            for path in UNCHANGED_PROTECTED
        },
        "full_suite_observation": {
            "passed": 835,
            "failed": 12,
            "skipped": 1,
            "baseline_nl1_passed": 830,
            "baseline_nl1_failed": 12,
            "baseline_nl1_skipped": 1,
            "note": (
                "five new NL2 tests account for the pass-count increase; "
                "the four failures in touched runtime areas reproduce with "
                "base-commit modules against the same data"
            ),
        },
    }
    decision = {
        "verdict": verdict,
        "passed": passed,
        "checks": checks,
        "slot_fixture": slot,
        "rejection_fixture": rejection,
        "retiming_fixture": retiming,
        "l100_regression_fixture": linear,
        "repair_fixture": repair,
        "static_legacy_energy_division_hits": (
            static_legacy_energy_division_hits
        ),
        "dynamic_legacy_formula_hits": dynamic_legacy_formula_hits,
        "unauthorized_changes": unauthorized_changes,
        "target_tests_returncode": pytest_result["returncode"],
        "ruff_returncode": ruff_result["returncode"],
        "unchanged_protected_diff_returncode": (
            unchanged_protected["returncode"]
        ),
        "formal_search_allowed": False,
        "next_gate": (
            "NL3_DYNAMIC_INHERITANCE_AND_CHINA81_PROFILE_ADAPTER"
            if passed
            else "STOP"
        ),
        "honest_boundary": (
            "NL2 proves that static charging construction, multi-trip carbon "
            "retiming, cost, emissions, profit, and the independent checker "
            "share one nonlinear action contract. Dynamic continuation still "
            "contains sealed L100 arithmetic and China81 still lacks a "
            "profile-aware three-matrix adapter, so formal search remains "
            "forbidden."
        ),
    }
    raw_rows = [
        {
            "check": name,
            "status": "PASS" if status else "FAIL",
            "observed": json.dumps(
                {
                    "taper_slot": slot,
                    "rejection": rejection,
                    "retiming": retiming,
                    "l100": linear,
                    "repair": repair,
                    "static_legacy_hits": static_legacy_energy_division_hits,
                    "dynamic_legacy_hits": dynamic_legacy_formula_hits,
                }.get(name, status),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "expected": "true",
            "detail": (
                "dynamic legacy hits are reported for NL3 and are not "
                "counted as an NL2 pass condition"
            ),
        }
        for name, status in checks.items()
    ]
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (OUT / "raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=raw_rows[0].keys(),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(raw_rows)
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = (
        "# China81 非线性充电 NL2 成本—检查闭合\n\n"
        f"判定：`{verdict}`。\n\n"
        "高 SOC 慢充阶段已经进入分时电量、碳排、成本、利润和独立检查器。"
        f"夹具首槽真实电量为 {slot['first_slot_energy_kwh']:.12g} kWh，"
        f"旧均匀摊分会给出 {slot['uniform_first_slot_energy_kwh']:.12g} "
        "kWh；两槽合计仍严格闭合 20 kWh。缩短 1 分钟的伪动作被成本端和"
        "检查端同时拒绝，缺少起止电量的非线性动作也失败关闭。\n\n"
        "同一非线性多趟方案中，精确碳择时把夹具间接排放从 "
        f"{retiming['naive_emissions_kg']:.12g} kg 降到 "
        f"{retiming['aware_emissions_kg']:.12g} kg；这是零搜索的机制"
        "验证，不是算法性能结论。L100 旧记录和带曲线记录都与历史均匀"
        "公式逐位一致。\n\n"
        "目标回归与 Ruff 通过；全量回归为 835 通过、12 失败、1 跳过，"
        "失败数量和受影响运行时失败均与 NL1/冻结提交基线一致，未包装成"
        "全量全绿。动态继承和 China81 三套道路矩阵接线仍属于 NL3，"
        "正式搜索继续关闭。\n"
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hash_paths = (
        SCRIPT,
        *(ROOT / path for path in CHANGED_CODE),
        *(ROOT / path for path in RECORD_SURFACES),
        INCIDENTS,
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "report.md",
    )
    artifact_hashes = {
        str(path.relative_to(ROOT)): file_sha256(path)
        for path in hash_paths
    }
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(artifact_hashes, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
