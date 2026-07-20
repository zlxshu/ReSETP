#!/usr/bin/env python3
"""Seal NL3a: nonlinear charging in exact-asset dynamic continuation."""

from __future__ import annotations

import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "solver/src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.charging_curve import L100_CONTROL, NL90_MILD  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.instance_loader import Instance, Node  # noqa: E402
from setp_solver.prices import PriceParameters  # noqa: E402
from setp_solver.search.dynamic_multitrip_schedule import (  # noqa: E402
    DynamicAssetState,
    cut_dynamic_certificate_at_trigger,
    prepare_dynamic_multitrip_solution,
    reschedule_dynamic_charging,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.solution import Route, Solution  # noqa: E402


OUT = (
    ROOT
    / "baselines/model_verification"
    / "china81_nonlinear_dynamic_nl3a_20260720"
)
SCRIPT = Path(__file__).resolve()
DYNAMIC_SOURCE = (
    ROOT
    / "solver/src/setp_solver/search/dynamic_multitrip_schedule.py"
)
TEST = (
    ROOT
    / "solver/tests/test_nonlinear_dynamic_multitrip_nl3_20260720.py"
)
TARGET_TESTS = (
    "solver/tests/test_nonlinear_dynamic_multitrip_nl3_20260720.py",
    "solver/tests/test_dynamic_multitrip_schedule.py",
    "solver/tests/test_nonlinear_multitrip_schedule_20260720.py",
    "solver/tests/test_nonlinear_cost_check_nl2_20260720.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _instance() -> Instance:
    nodes = [
        Node("D0", "d", 0, 0, ready_time=0, due_time=30_000),
        Node(
            "C1",
            "c",
            1,
            0,
            demand=1,
            ready_time=6_000,
            due_time=7_000,
        ),
        Node(
            "C2",
            "c",
            2,
            0,
            demand=1,
            ready_time=14_000,
            due_time=15_000,
        ),
    ]
    return Instance(
        nodes,
        [
            [0.0, 1_000.0, 1_000.0],
            [1_000.0, 0.0, 1_000.0],
            [1_000.0, 1_000.0, 0.0],
        ],
        num_cv=0,
        num_ev=1,
    )


def _prices(spec: Any) -> PriceParameters:
    return PriceParameters(
        B_battery_kwh=20.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
        charging_curve_id=spec.curve_id,
        charging_soc_breakpoints=spec.soc_breakpoints,
        charging_relative_powers=spec.relative_powers,
    )


def _fixture(spec: Any = NL90_MILD):
    state = DynamicAssetState(
        "EV_D0_7",
        "ev",
        "D0",
        1_000.0,
        0.0,
        3,
    )
    source = Solution(
        routes=[
            Route("open-a", "ev", "D0", ["D0", "C1", "D0"]),
            Route("open-b", "ev", "D0", ["D0", "C2", "D0"]),
        ]
    )
    prepared, certificate = prepare_dynamic_multitrip_solution(
        source,
        _instance(),
        _prices(spec),
        asset_states={state.physical_vehicle_id: state},
        stage_start_second=1_000.0,
    )
    return state, prepared, certificate


def _dynamic_fixture() -> dict[str, Any]:
    state, prepared, certificate = _fixture()
    curve = NL90_MILD.scale(
        capacity_kwh=20.0,
        reference_power_kw=22.0,
    )
    duration_errors = [
        abs(
            float(action.occupancy_minutes) * 60.0
            - curve.duration_seconds(
                float(action.start_energy_kwh),
                float(action.end_energy_kwh),
            )
        )
        for action in prepared.charging_actions
    ]
    first = prepared.charging_actions[0]
    shortened_rejected = False
    try:
        validate_dynamic_multitrip_certificate(
            replace(
                prepared,
                charging_actions=[
                    replace(
                        first,
                        occupancy_minutes=first.occupancy_minutes - 1.0,
                    ),
                    *prepared.charging_actions[1:],
                ],
            ),
            certificate,
            _instance(),
            _prices(NL90_MILD),
            asset_states={state.physical_vehicle_id: state},
            stage_start_second=1_000.0,
        )
    except ValueError:
        shortened_rejected = True
    missing_rejected = False
    try:
        validate_dynamic_multitrip_certificate(
            replace(
                prepared,
                charging_actions=[
                    replace(
                        first,
                        start_energy_kwh=None,
                        end_energy_kwh=None,
                        charging_curve_id=None,
                    ),
                    *prepared.charging_actions[1:],
                ],
            ),
            certificate,
            _instance(),
            _prices(NL90_MILD),
            asset_states={state.physical_vehicle_id: state},
            stage_start_second=1_000.0,
        )
    except ValueError:
        missing_rejected = True
    return {
        "action_count": len(prepared.charging_actions),
        "curve_id": certificate.charging_curve_id,
        "curve_sha256": certificate.charging_curve_parameter_sha256,
        "max_duration_error_seconds": max(duration_errors, default=0.0),
        "missing_energy_state_count": sum(
            action.start_energy_kwh is None
            or action.end_energy_kwh is None
            for action in prepared.charging_actions
        ),
        "shortened_action_rejected": shortened_rejected,
        "missing_metadata_rejected": missing_rejected,
    }


def _retiming_fixture() -> dict[str, Any]:
    state, prepared, certificate = _fixture()
    profile = [
        {
            "time_index": index,
            "horizon_second_start": float(index * 1_800),
            "actual_gco2_per_kwh": 800.0 if index < 3 else 50.0,
            "forecast_gco2_per_kwh": 800.0 if index < 3 else 50.0,
        }
        for index in range(48)
    ]
    kwargs = {
        "asset_states": {state.physical_vehicle_id: state},
        "stage_start_second": 1_000.0,
    }
    naive, _, _ = reschedule_dynamic_charging(
        prepared,
        certificate,
        _instance(),
        profile,
        _prices(NL90_MILD),
        strategy="naive",
        **kwargs,
    )
    aware, aware_certificate, stats = reschedule_dynamic_charging(
        prepared,
        certificate,
        _instance(),
        profile,
        _prices(NL90_MILD),
        strategy="aware",
        **kwargs,
    )
    naive_emissions = evaluate(
        naive,
        _instance(),
        profile,
        _prices(NL90_MILD),
        carbon_quota_kg=float("inf"),
    )["E_ev_indirect"]
    aware_emissions = evaluate(
        aware,
        _instance(),
        profile,
        _prices(NL90_MILD),
        carbon_quota_kg=float("inf"),
    )["E_ev_indirect"]
    first_action = aware.charging_actions[0]
    trigger = (
        float(first_action.charge_start_second)
        + float(first_action.occupancy_minutes) * 30.0
    )
    cut = cut_dynamic_certificate_at_trigger(
        aware,
        aware_certificate,
        _instance(),
        _prices(NL90_MILD),
        inherited_asset_states={state.physical_vehicle_id: state},
        previous_stage_start_second=1_000.0,
        trigger_second=trigger,
    )
    return {
        "naive_emissions_kg": naive_emissions,
        "aware_emissions_kg": aware_emissions,
        "relative_reduction": (
            (naive_emissions - aware_emissions) / naive_emissions
            if naive_emissions > 0.0
            else 0.0
        ),
        "moved_action_count": stats["moved_action_count"],
        "cut_locked_action_count": len(cut.locked_charging_actions),
        "cut_release_second": cut.asset_states[
            state.physical_vehicle_id
        ].available_second,
    }


def _linear_fixture() -> dict[str, Any]:
    _, prepared, certificate = _fixture(L100_CONTROL)
    errors = [
        abs(
            float(action.occupancy_minutes) * 60.0
            - float(action.energy_kwh) / 22.0 * 3_600.0
        )
        for action in prepared.charging_actions
    ]
    return {
        "curve_id": certificate.charging_curve_id,
        "max_legacy_duration_error_seconds": max(errors, default=0.0),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    dynamic = _dynamic_fixture()
    retiming = _retiming_fixture()
    linear = _linear_fixture()
    source_text = DYNAMIC_SOURCE.read_text(encoding="utf-8")
    forbidden_hits = {
        "energy_divided_by_power": len(
            re.findall(r"(?:needed|charge_energy)\s*/\s*power", source_text)
        ),
        "gap_times_power": len(
            re.findall(r"gap\s*\*\s*power", source_text)
        ),
        "battery_plus_time_power": len(
            re.findall(r"battery.*\+\s*.*power", source_text)
        ),
        "legacy_carbon_helper": source_text.count(
            "_lowest_carbon_gap_start"
        ),
    }
    python = sys.executable
    tests = _run(
        [
            python,
            "-m",
            "pytest",
            "-q",
            *TARGET_TESTS,
        ]
    )
    ruff = _run(
        [
            str(Path(python).with_name("ruff")),
            "check",
            str(DYNAMIC_SOURCE.relative_to(ROOT)),
            str(TEST.relative_to(ROOT)),
            str(SCRIPT.relative_to(ROOT)),
        ]
    )
    checks = {
        "curve_bound_actions": (
            dynamic["action_count"] > 0
            and dynamic["curve_id"] == NL90_MILD.curve_id
            and dynamic["curve_sha256"] == NL90_MILD.parameter_sha256
            and dynamic["missing_energy_state_count"] == 0
            and dynamic["max_duration_error_seconds"] <= 1e-9
        ),
        "tampering_fails_closed": (
            dynamic["shortened_action_rejected"]
            and dynamic["missing_metadata_rejected"]
        ),
        "exact_carbon_retiming_improves": (
            retiming["moved_action_count"] >= 1
            and retiming["aware_emissions_kg"]
            < retiming["naive_emissions_kg"]
        ),
        "dynamic_cut_closes": retiming["cut_locked_action_count"] >= 1,
        "l100_regression": (
            linear["curve_id"] == L100_CONTROL.curve_id
            and linear["max_legacy_duration_error_seconds"] <= 1e-9
        ),
        "legacy_formula_hits_zero": all(
            value == 0 for value in forbidden_hits.values()
        ),
        "target_tests": tests["returncode"] == 0,
        "ruff": ruff["returncode"] == 0,
    }
    passed = all(checks.values())
    decision = {
        "verdict": (
            "PASS_NL3A_NONLINEAR_DYNAMIC_INHERITANCE"
            if passed
            else "HOLD_NL3A_NONLINEAR_DYNAMIC_INHERITANCE"
        ),
        "passed": passed,
        "checks": checks,
        "dynamic_fixture": dynamic,
        "retiming_fixture": retiming,
        "l100_regression_fixture": linear,
        "legacy_formula_hits": forbidden_hits,
        "target_tests": tests,
        "ruff": ruff,
        "formal_search_allowed": False,
        "next_gate": "NL3B_CHINA81_CV_EV_THREE_MATRIX_ADAPTER",
        "honest_boundary": (
            "NL3a closes nonlinear charging in dynamic exact-asset "
            "continuation. China81 CV/EV distance-duration-sum(v^2 d) "
            "matrices are not yet wired into route clocks and energy, so "
            "formal search remains forbidden."
        ),
    }
    metadata = {
        "schema": "resetp.china81-nonlinear-dynamic-nl3a.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "search_performed": False,
        "formal_search_allowed": False,
        "source_files": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (DYNAMIC_SOURCE, TEST, SCRIPT)
        },
    }
    rows = [
        {
            "check": key,
            "passed": str(value).lower(),
            "value": json.dumps(
                (
                    dynamic
                    if key.startswith(("curve", "tampering"))
                    else retiming
                    if key.startswith(("exact", "dynamic_cut"))
                    else linear
                    if key == "l100_regression"
                    else forbidden_hits
                    if key == "legacy_formula_hits_zero"
                    else tests
                    if key == "target_tests"
                    else ruff
                ),
                sort_keys=True,
            ),
        }
        for key, value in checks.items()
    ]
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "decision.json").write_text(
        json.dumps(decision, indent=2) + "\n",
        encoding="utf-8",
    )
    with (OUT / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("check", "passed", "value"),
        )
        writer.writeheader()
        writer.writerows(rows)
    report = f"""# China81 非线性充电 NL3a 动态继承闭合

判定：`{decision["verdict"]}`。

动态调度不再用“电量 ÷ 固定功率”估算充电。候选筛选、最终电池账、
动作时长、低碳择时和动态切割现在共用 NL0–NL2 的同一条充电曲线。
本夹具生成 {dynamic["action_count"]} 个带曲线身份证和起止电量的动作，
最大独立复算时长误差为 {dynamic["max_duration_error_seconds"]:.3g} 秒；
缩短动作和删除非线性元数据都会失败关闭。

精确动态低碳择时把夹具间接排放从
{retiming["naive_emissions_kg"]:.12g} kg 降到
{retiming["aware_emissions_kg"]:.12g} kg。这是零搜索的机制接线验证，
不是算法性能结论。L100 旧线性时长回归误差为
{linear["max_legacy_duration_error_seconds"]:.3g} 秒。

China81 的 CV/EV 两类车辆、每类距离/时长/Σ(v²d) 三矩阵尚未进入
正式路线时钟和能耗，因此正式搜索继续关闭。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    artifact_files = sorted(
        path
        for path in OUT.iterdir()
        if path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    hashes = {
        "algorithm": "sha256",
        "files": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in artifact_files
        },
    }
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(hashes, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
