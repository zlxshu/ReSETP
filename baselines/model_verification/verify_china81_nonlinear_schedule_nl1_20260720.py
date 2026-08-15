#!/usr/bin/env python3
"""Close NL1: curve-aware solution records and physical multi-trip scheduling."""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "solver/src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.charging_curve import L100_CONTROL, NL90_MILD  # noqa: E402
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.prices import PriceParameters  # noqa: E402
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    CONTRACT_ID,
    NONLINEAR_CONTRACT_ID,
    build_multitrip_certificate,
    multitrip_certificate_from_dict,
    prepare_multitrip_solution,
    route_timing,
)
from setp_solver.solution import (  # noqa: E402
    Route,
    Solution,
    charging_action_from_dict,
)


OUT = (
    ROOT
    / "baselines/model_verification"
    / "china81_nonlinear_schedule_nl1_20260720"
)
SCHEDULE_SOURCE = ROOT / "solver/src/setp_solver/search/multitrip_schedule.py"
AUTHORIZED_CHANGED_PATHS = {
    "HANDOFF.md",
    "docs/handoff/china81_nonlinear_core_g1_contract_20260720.md",
    "docs/handoff/memory/MEMORY.md",
    "docs/handoff/memory/project-prd-execution-v2.md",
    "docs/handoff/model_change_approval_register_20260718.md",
    "solver/src/setp_solver/charging_curve.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/alns_crush.py",
    "solver/src/setp_solver/search/alns_crush_v2.py",
    "solver/src/setp_solver/search/alns_crush_v3.py",
    "solver/src/setp_solver/search/fairness.py",
    "solver/src/setp_solver/search/formal_runner.py",
    "solver/src/setp_solver/search/metaheuristic_baselines.py",
    "solver/src/setp_solver/search/multitrip_schedule.py",
    "solver/src/setp_solver/search/winner_restoration.py",
    "solver/src/setp_solver/solution.py",
    "solver/tests/test_charging_action_persistence.py",
    "solver/tests/test_nonlinear_multitrip_schedule_20260720.py",
    "baselines/model_verification/verify_china81_nonlinear_schedule_nl1_20260720.py",
    "baselines/model_verification/china81_nonlinear_schedule_nl1_20260720/development_incidents.md",
}
UNAUTHORIZED_PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "docs/paper_submission_final/RETIRED_paper_main.tex",
)
TARGET_TESTS = (
    "solver/tests/test_charging_curve.py",
    "solver/tests/test_charging_action_persistence.py",
    "solver/tests/test_nonlinear_multitrip_schedule_20260720.py",
    "solver/tests/test_multitrip_schedule.py",
    "solver/tests/test_dynamic_multitrip_schedule.py",
    "solver/tests/test_certificate_execution.py",
    "solver/tests/test_execution_accounting.py",
    "solver/tests/test_e3_v3_runner.py",
)
LEGACY_FORMULA_PATTERNS = {
    "energy_divided_by_depot_power": re.compile(
        r"(?:energy|charge_energy)[^\n]{0,100}/[^\n]{0,100}"
        r"depot_charge_power_kw"
    ),
    "gap_times_depot_power": re.compile(
        r"(?:gap|available)[^\n]{0,100}\*[^\n]{0,100}"
        r"depot_charge_power_kw"
    ),
    "depot_power_times_gap": re.compile(
        r"depot_charge_power_kw[^\n]{0,100}\*[^\n]{0,100}"
        r"(?:gap|available)"
    ),
}
TOL = 1e-7


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_command(command: list[str], *, env: dict[str, str] | None = None) -> dict[str, object]:
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
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def fixture(*, second_ready: float) -> Instance:
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
            ready_time=second_ready,
            due_time=second_ready + 3_000,
            service_time=100,
        ),
    ]
    matrix = [
        [0.0 if left == right else 1_000.0 for right in range(len(nodes))]
        for left in range(len(nodes))
    ]
    return Instance(nodes, matrix, num_cv=2, num_ev=2)


def routes() -> list[Route]:
    return [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]


def prices(spec: object, *, capacity_kwh: float) -> PriceParameters:
    return PriceParameters(
        B_battery_kwh=capacity_kwh,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
        charging_curve_id=spec.curve_id,
        charging_soc_breakpoints=spec.soc_breakpoints,
        charging_relative_powers=spec.relative_powers,
    )


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
        path in AUTHORIZED_CHANGED_PATHS
        or path.startswith(
            "baselines/model_verification/"
            "china81_nonlinear_schedule_nl1_20260720/"
        )
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    test_instance = fixture(second_ready=1_373.0)
    test_routes = routes()
    control = PriceParameters(B_battery_kwh=280.0)
    drive = route_timing(test_routes[0], test_instance, control).drive_energy_kwh
    capacity = drive * 1.05
    linear_prices = prices(L100_CONTROL, capacity_kwh=capacity)
    nonlinear_prices = prices(NL90_MILD, capacity_kwh=capacity)
    linear_certificate = build_multitrip_certificate(
        test_routes,
        test_instance,
        linear_prices,
    )
    nonlinear_certificate = build_multitrip_certificate(
        test_routes,
        test_instance,
        nonlinear_prices,
    )

    roomy_instance = fixture(second_ready=6_000.0)
    linear_prepared, linear_prepared_certificate = prepare_multitrip_solution(
        Solution(routes=test_routes),
        roomy_instance,
        linear_prices,
    )
    nonlinear_prepared, nonlinear_prepared_certificate = (
        prepare_multitrip_solution(
            Solution(routes=test_routes),
            roomy_instance,
            nonlinear_prices,
        )
    )

    linear_duration_errors = [
        abs(
            action.occupancy_minutes * 60.0
            - action.energy_kwh / linear_prices.depot_charge_power_kw * 3600.0
        )
        for action in linear_prepared.charging_actions
    ]
    nonlinear_curve = NL90_MILD.scale(
        capacity_kwh=capacity,
        reference_power_kw=nonlinear_prices.depot_charge_power_kw,
    )
    nonlinear_duration_errors = [
        abs(
            action.occupancy_minutes * 60.0
            - nonlinear_curve.duration_seconds(
                float(action.start_energy_kwh),
                float(action.end_energy_kwh),
            )
        )
        for action in nonlinear_prepared.charging_actions
    ]
    nonlinear_energy_errors = [
        abs(
            action.energy_kwh
            - (
                float(action.end_energy_kwh)
                - float(action.start_energy_kwh)
            )
        )
        for action in nonlinear_prepared.charging_actions
    ]
    action_roundtrip_failures = sum(
        charging_action_from_dict(asdict(action)) != action
        for action in nonlinear_prepared.charging_actions
    )
    certificate_roundtrip_failures = int(
        multitrip_certificate_from_dict(
            nonlinear_prepared_certificate.as_dict()
        )
        != nonlinear_prepared_certificate
    )
    old_action = charging_action_from_dict(
        {
            "vehicle_id": "EV_legacy",
            "station_id": "D0",
            "energy_kwh": 10.0,
            "occupancy_minutes": 20.0,
            "charge_start_second": 1_000.0,
            "charge_day_offset": 0,
        }
    )
    legacy_action_compatible = (
        old_action.start_energy_kwh is None
        and old_action.end_energy_kwh is None
        and old_action.charging_curve_id is None
    )

    schedule_text = SCHEDULE_SOURCE.read_text(encoding="utf-8")
    formula_hits = {
        name: len(pattern.findall(schedule_text))
        for name, pattern in LEGACY_FORMULA_PATTERNS.items()
    }
    dirty = changed_paths()
    unauthorized_changes = sorted(
        path for path in dirty if not is_authorized_change(path)
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT / 'solver/src'}:{ROOT / 'models/src'}:{ROOT}"
    env["PYTHONHASHSEED"] = "0"
    pytest_result = run_command(
        [sys.executable, "-m", "pytest", "-q", *TARGET_TESTS],
        env=env,
    )
    ruff_result = run_command(
        [
            "/opt/anaconda3/bin/ruff",
            "check",
            "solver/src/setp_solver/charging_curve.py",
            "solver/src/setp_solver/prices.py",
            "solver/src/setp_solver/solution.py",
            "solver/src/setp_solver/search/multitrip_schedule.py",
            "solver/tests/test_charging_action_persistence.py",
            "solver/tests/test_nonlinear_multitrip_schedule_20260720.py",
            str(Path(__file__).relative_to(ROOT)),
        ]
    )
    protected_diff = run_command(
        ["git", "diff", "--exit-code", "--", *UNAUTHORIZED_PROTECTED]
    )

    summary = {
        "linear_physical_vehicle_count": linear_certificate.vehicle_counts["ev"],
        "nonlinear_physical_vehicle_count": nonlinear_certificate.vehicle_counts["ev"],
        "expected_linear_contract": linear_certificate.contract_id == CONTRACT_ID,
        "expected_nonlinear_contract": (
            nonlinear_certificate.contract_id == NONLINEAR_CONTRACT_ID
        ),
        "nonlinear_curve_id": nonlinear_certificate.charging_curve_id,
        "nonlinear_curve_parameter_sha256": (
            nonlinear_certificate.charging_curve_parameter_sha256
        ),
        "linear_action_count": len(linear_prepared.charging_actions),
        "nonlinear_action_count": len(nonlinear_prepared.charging_actions),
        "max_linear_duration_error_seconds": max(
            linear_duration_errors, default=0.0
        ),
        "max_nonlinear_duration_error_seconds": max(
            nonlinear_duration_errors, default=0.0
        ),
        "max_nonlinear_energy_error_kwh": max(
            nonlinear_energy_errors, default=0.0
        ),
        "action_roundtrip_failures": action_roundtrip_failures,
        "certificate_roundtrip_failures": certificate_roundtrip_failures,
        "legacy_action_compatible": legacy_action_compatible,
        "legacy_formula_hits": formula_hits,
        "unauthorized_changes": unauthorized_changes,
        "target_tests_returncode": pytest_result["returncode"],
        "ruff_returncode": ruff_result["returncode"],
        "unauthorized_protected_diff_returncode": protected_diff["returncode"],
    }
    passed = all(
        (
            summary["linear_physical_vehicle_count"] == 1,
            summary["nonlinear_physical_vehicle_count"] == 2,
            summary["expected_linear_contract"],
            summary["expected_nonlinear_contract"],
            summary["nonlinear_curve_id"] == NL90_MILD.curve_id,
            summary["nonlinear_curve_parameter_sha256"]
            == NL90_MILD.parameter_sha256,
            summary["linear_action_count"] > 0,
            summary["nonlinear_action_count"] > 0,
            summary["max_linear_duration_error_seconds"] <= TOL,
            summary["max_nonlinear_duration_error_seconds"] <= TOL,
            summary["max_nonlinear_energy_error_kwh"] <= TOL,
            summary["action_roundtrip_failures"] == 0,
            summary["certificate_roundtrip_failures"] == 0,
            summary["legacy_action_compatible"],
            not any(formula_hits.values()),
            not unauthorized_changes,
            pytest_result["returncode"] == 0,
            ruff_result["returncode"] == 0,
            protected_diff["returncode"] == 0,
            linear_prepared_certificate.contract_id == CONTRACT_ID,
            nonlinear_prepared_certificate.contract_id
            == NONLINEAR_CONTRACT_ID,
        )
    )
    verdict = (
        "PASS_NL1_CURVE_AWARE_MULTITRIP_SCHEDULE"
        if passed
        else "HALT_NL1_CURVE_AWARE_MULTITRIP_SCHEDULE"
    )
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "schema": "resetp.china81-nonlinear-schedule-nl1.v1",
        "created_at_utc": now,
        "scope": "solution persistence and curve-aware physical multi-trip schedule",
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "python": sys.executable,
        "curve": asdict(NL90_MILD),
        "authorized_changed_paths": sorted(AUTHORIZED_CHANGED_PATHS),
        "protected_hashes": {
            path: file_sha256(ROOT / path)
            for path in (*UNAUTHORIZED_PROTECTED, "solver/src/setp_solver/prices.py")
        },
    }
    decision = {
        "verdict": verdict,
        "passed": passed,
        **summary,
        "formal_search_allowed": False,
        "next_gate": (
            "NL2_COST_CHECK_AND_CHARGING_TIMING_CLOSURE"
            if passed
            else "STOP"
        ),
        "honest_boundary": (
            "NL1 proves that new charging actions and physical multi-trip "
            "schedules carry one frozen curve identity, exact energy states, "
            "and curve-derived occupancy while old linear records remain "
            "readable. Cost, carbon, independent checking, profile-aware "
            "China81 input adaptation, and algorithm performance are not yet "
            "closed."
        ),
    }
    raw_rows = [
        {
            "check": "short_gap_physics",
            "status": (
                "PASS"
                if linear_certificate.vehicle_counts["ev"] == 1
                and nonlinear_certificate.vehicle_counts["ev"] == 2
                else "FAIL"
            ),
            "observed": (
                f"L100={linear_certificate.vehicle_counts['ev']};"
                f"NL90={nonlinear_certificate.vehicle_counts['ev']}"
            ),
            "expected": "L100=1;NL90=2",
            "detail": "same two routes; nonlinear taper alone requires one extra vehicle",
        },
        {
            "check": "curve_identity_and_hash",
            "status": (
                "PASS"
                if nonlinear_certificate.charging_curve_id == NL90_MILD.curve_id
                and nonlinear_certificate.charging_curve_parameter_sha256
                == NL90_MILD.parameter_sha256
                else "FAIL"
            ),
            "observed": nonlinear_certificate.charging_curve_parameter_sha256,
            "expected": NL90_MILD.parameter_sha256,
            "detail": nonlinear_certificate.charging_curve_id,
        },
        {
            "check": "action_energy_duration_and_roundtrip",
            "status": (
                "PASS"
                if max(nonlinear_duration_errors, default=0.0) <= TOL
                and max(nonlinear_energy_errors, default=0.0) <= TOL
                and action_roundtrip_failures == 0
                else "FAIL"
            ),
            "observed": (
                f"duration={max(nonlinear_duration_errors, default=0.0):.12g};"
                f"energy={max(nonlinear_energy_errors, default=0.0):.12g};"
                f"roundtrip={action_roundtrip_failures}"
            ),
            "expected": "all<=1e-7;roundtrip=0",
            "detail": f"actions={len(nonlinear_prepared.charging_actions)}",
        },
        {
            "check": "linear_degeneracy",
            "status": (
                "PASS"
                if max(linear_duration_errors, default=0.0) <= TOL
                else "FAIL"
            ),
            "observed": max(linear_duration_errors, default=0.0),
            "expected": f"<={TOL}",
            "detail": f"actions={len(linear_prepared.charging_actions)}",
        },
        {
            "check": "legacy_formula_scan",
            "status": "PASS" if not any(formula_hits.values()) else "FAIL",
            "observed": json.dumps(formula_hits, sort_keys=True),
            "expected": "all zero",
            "detail": str(SCHEDULE_SOURCE.relative_to(ROOT)),
        },
        {
            "check": "target_tests",
            "status": "PASS" if pytest_result["returncode"] == 0 else "FAIL",
            "observed": pytest_result["returncode"],
            "expected": 0,
            "detail": str(pytest_result["stdout_tail"]),
        },
        {
            "check": "ruff",
            "status": "PASS" if ruff_result["returncode"] == 0 else "FAIL",
            "observed": ruff_result["returncode"],
            "expected": 0,
            "detail": str(ruff_result["stdout_tail"]),
        },
        {
            "check": "change_boundary",
            "status": (
                "PASS"
                if not unauthorized_changes
                and protected_diff["returncode"] == 0
                else "FAIL"
            ),
            "observed": json.dumps(unauthorized_changes),
            "expected": "[]",
            "detail": "cost/check/evaluation/TeX unchanged during NL1",
        },
    ]
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
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
        "# China81 非线性充电 NL1 接线验证\n\n"
        f"判定：`{verdict}`。\n\n"
        "同一组两趟 EV 路线在恒功率曲线下需要 "
        f"{linear_certificate.vehicle_counts['ev']} 辆实体车，在 NL90 "
        f"曲线下需要 {nonlinear_certificate.vehicle_counts['ev']} 辆。"
        "这证明非线性曲线已经进入排程结果，而不是只留在报告里。\n\n"
        f"新动作 {len(nonlinear_prepared.charging_actions)} 条，起止电量、"
        "曲线身份、持续时间和 JSON 往返均闭合；最大非线性持续时间误差 "
        f"{max(nonlinear_duration_errors, default=0.0):.12g} 秒，最大电量误差 "
        f"{max(nonlinear_energy_errors, default=0.0):.12g} kWh。恒功率控制最大"
        f"漂移 {max(linear_duration_errors, default=0.0):.12g} 秒。\n\n"
        "本门没有运行搜索。成本、碳排、独立检查器和 China81 三套道路"
        "矩阵仍未闭合，因此仍不允许宣称 China81 可正式比较算法。\n"
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hash_paths = (
        Path(__file__),
        ROOT / "solver/src/setp_solver/charging_curve.py",
        ROOT / "solver/src/setp_solver/prices.py",
        ROOT / "solver/src/setp_solver/solution.py",
        SCHEDULE_SOURCE,
        ROOT / "solver/tests/test_charging_action_persistence.py",
        ROOT / "solver/tests/test_nonlinear_multitrip_schedule_20260720.py",
        ROOT / "docs/handoff/china81_nonlinear_core_g1_contract_20260720.md",
        OUT / "development_incidents.md",
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "report.md",
    )
    artifact_hashes = {
        str(path.relative_to(ROOT)): file_sha256(path) for path in hash_paths
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
