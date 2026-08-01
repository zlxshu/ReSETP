#!/usr/bin/env python3
"""Replay sealed E2/E4/E6 saved solutions through the *current* scorer.

This is an explicitly non-formal compatibility diagnostic.  It never invokes
search, never changes an input, and writes only a new five-piece diagnostic
package.  Its narrow question is whether the current E5 default additions
(zero route-time price and no station-copy nodes in these saved instances)
change the old legalities, total costs, or selected score components.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEFAULT_OUTPUT = HERE / "saved_solution_replay_20260801"
E2 = REPO / "baselines/algorithm_prototypes/china81_vs_opensource_20260727"
E2_ARCHIVE = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724/full_gate"
)
E4 = REPO / "baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801"
E6 = (
    REPO
    / "baselines/china_e3_e7/e6_contractor_participation_20260801"
    / "formal_e6a_panel_20260801"
)
TOLERANCE = 1.0e-6
E2_LOCKED_CHINA81_SHA256 = "df082b6a0e108aa5462b74048fcca7a63fdb7eaafb9e61f2dcdd787e3d9fcedd"
E2_LOCKED_CHINA81_COMMIT = "e99901854ee10af77d42c3e5e152ef79a806c8d1"
E2_LOCKED_BATTERY_KWH = 140.41
E2_LOCKED_CHARGING_CURVE_SHA256 = "158cc9f9e50645692bfb0ceb218745e3c73d58dd5a6e44282a0bda7f0edfec70"
E2_ROOT_CAUSE_CODE = "E2_LOCKED_140_41KWH_VS_CURRENT_77_28KWH_CONTRACT_DRIFT"
KEY_METRICS = (
    "total_cost",
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "E_cv_direct",
    "E_ev_indirect",
    "E_total",
    "distance_total",
    "electricity_kwh",
    "n_veh_cv",
    "n_veh_ev",
)

for path in (REPO, REPO / "solver/src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.charging_curve import spec_from_parameters
from setp_solver.solution import (
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else ["experiment", "status", "halt_reason"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", ())],
        charging_actions=[
            charging_action_from_dict(row)
            for row in payload.get("charging_actions", ())
        ],
        cross_site_services=[
            CrossSiteService(**row) for row in payload.get("cross_site_services", ())
        ],
    )


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def base_row(
    *,
    experiment: str,
    source_path: Path | None,
    instance_id: str = "",
    seed: int | str = "",
    arm: str = "",
    expected_objective: float | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "experiment": experiment,
        "source_solution": "" if source_path is None else str(source_path.relative_to(REPO)),
        "instance_id": instance_id,
        "seed": seed,
        "arm_or_mode_or_coalition": arm,
        "expected_objective": "" if expected_objective is None else expected_objective,
        "current_objective": "",
        "objective_abs_delta": "",
        "current_legal": "",
        "current_violation_count": "",
        "saved_violation_count": "",
        "current_cost_time": "",
        "current_route_time_hours": "",
        "compared_metric_count": 0,
        "mismatch_metrics": "",
        "status": "",
        "halt_reason": "",
    }
    for metric in KEY_METRICS:
        row[f"saved_{metric}"] = ""
        row[f"current_{metric}"] = ""
        row[f"delta_{metric}"] = ""
    row.update(
        {
            "root_cause_code": "",
            "locked_china81_sha256": "",
            "locked_china81_commit": "",
            "locked_battery_kwh": "",
            "current_battery_kwh": "",
            "locked_charging_curve_sha256": "",
            "old_curve_action_count": "",
            "old_curve_max_duration_abs_error_seconds": "",
            "current_curve_max_duration_abs_error_seconds": "",
            "root_cause_not_e5": "",
        }
    )
    return row


def compare(
    row: dict[str, Any],
    *,
    saved_breakdown: dict[str, Any],
    current_breakdown: dict[str, Any],
    expected_objective: float,
    current_objective: float,
    violations: list[Any],
    saved_violation_count: int,
) -> None:
    mismatch: list[str] = []
    row["current_objective"] = current_objective
    row["objective_abs_delta"] = abs(current_objective - expected_objective)
    row["current_legal"] = not violations
    row["current_violation_count"] = len(violations)
    row["saved_violation_count"] = saved_violation_count
    row["current_cost_time"] = float(current_breakdown.get("cost_time", 0.0))
    row["current_route_time_hours"] = float(
        current_breakdown.get("route_time_hours", 0.0)
    )
    if abs(current_objective - expected_objective) > TOLERANCE:
        mismatch.append("objective")
    if abs(float(current_breakdown.get("cost_time", 0.0))) > TOLERANCE:
        mismatch.append("current_cost_time_nonzero")
    for metric in KEY_METRICS:
        saved = number(saved_breakdown.get(metric))
        current = number(current_breakdown.get(metric))
        if saved is None or current is None:
            continue
        delta = current - saved
        row[f"saved_{metric}"] = saved
        row[f"current_{metric}"] = current
        row[f"delta_{metric}"] = delta
        row["compared_metric_count"] += 1
        if abs(delta) > TOLERANCE:
            mismatch.append(metric)
    row["mismatch_metrics"] = ";".join(mismatch)
    row["status"] = (
        "PASS_CURRENT_REPLAY_EQUIVALENT"
        if not violations and not mismatch
        else "FAIL_CURRENT_REPLAY_MISMATCH"
    )


def replay_e2() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_rows = json.loads((E2 / "raw_runs.json").read_text(encoding="utf-8"))
    expected = {
        (str(item["instance_id"]), int(item["seed"]), str(item["arm"])): item
        for item in raw_rows
    }
    bundles: dict[str, Any] = {}

    def locked_contract_evidence(bundle: Any, solution: Solution) -> dict[str, Any]:
        """Prove the six E2 halts are a frozen battery-contract drift, not E5."""

        locked_source = subprocess.run(
            [
                "git",
                "show",
                f"{E2_LOCKED_CHINA81_COMMIT}:solver/src/setp_solver/china81.py",
            ],
            cwd=REPO,
            check=True,
            capture_output=True,
        ).stdout
        if sha256(REPO / "solver/src/setp_solver/charging_curve.py") != E2_LOCKED_CHARGING_CURVE_SHA256:
            raise RuntimeError("locked E2 charging_curve.py differs from current curve kernel")
        if hashlib.sha256(locked_source).hexdigest() != E2_LOCKED_CHINA81_SHA256:
            raise RuntimeError("locked E2 china81.py Git blob hash differs from metadata")
        if not re.search(rb"battery_kwh=140\.41", locked_source):
            raise RuntimeError("locked E2 china81.py does not contain the 140.41 kWh EV contract")

        current_capacity = bundle.instance.battery_capacity_kwh(
            fallback=bundle.prices.B_battery_kwh
        )
        if abs(current_capacity - 77.28) > TOLERANCE:
            raise RuntimeError(
                f"current E2 replay bundle has unexpected battery capacity {current_capacity}"
            )
        nodes = {node.node_id: node for node in bundle.instance.nodes}
        spec = spec_from_parameters(bundle.prices)
        rows: list[dict[str, float | str]] = []
        for action in solution.charging_actions:
            if action.start_energy_kwh is None or action.end_energy_kwh is None:
                continue
            station = nodes.get(action.station_id)
            if station is None:
                raise RuntimeError(f"saved action has unknown station {action.station_id!r}")
            power_kw = (
                float(bundle.prices.depot_charge_power_kw)
                if station.node_type.lower() == "d"
                else float(station.charge_power_kw)
            )
            old_duration = spec.scale(
                capacity_kwh=E2_LOCKED_BATTERY_KWH,
                reference_power_kw=power_kw,
            ).duration_seconds(float(action.start_energy_kwh), float(action.end_energy_kwh))
            current_duration = spec.scale(
                capacity_kwh=current_capacity,
                reference_power_kw=power_kw,
            ).duration_seconds(float(action.start_energy_kwh), float(action.end_energy_kwh))
            recorded_duration = float(action.occupancy_minutes) * 60.0
            if abs(current_duration - recorded_duration) > TOLERANCE:
                rows.append(
                    {
                        "vehicle_id": action.vehicle_id,
                        "station_id": action.station_id,
                        "recorded_duration_seconds": recorded_duration,
                        "old_curve_duration_seconds": old_duration,
                        "current_curve_duration_seconds": current_duration,
                        "old_curve_abs_error_seconds": abs(old_duration - recorded_duration),
                        "current_curve_abs_error_seconds": abs(
                            current_duration - recorded_duration
                        ),
                    }
                )
        if not rows or any(item["old_curve_abs_error_seconds"] > TOLERANCE for item in rows):
            raise RuntimeError("E2 halt does not reduce to the locked battery contract")
        return {
            "root_cause_code": E2_ROOT_CAUSE_CODE,
            "locked_china81_sha256": E2_LOCKED_CHINA81_SHA256,
            "locked_china81_commit": E2_LOCKED_CHINA81_COMMIT,
            "locked_battery_kwh": E2_LOCKED_BATTERY_KWH,
            "current_battery_kwh": current_capacity,
            "locked_charging_curve_sha256": E2_LOCKED_CHARGING_CURVE_SHA256,
            "action_count": len(rows),
            "old_curve_max_duration_abs_error_seconds": max(
                item["old_curve_abs_error_seconds"] for item in rows
            ),
            "current_curve_max_duration_abs_error_seconds": max(
                item["current_curve_abs_error_seconds"] for item in rows
            ),
            "not_attributed_to_e5": True,
        }

    def replay(
        path: Path, instance_id: str, seed: int, arm: str, payload: dict[str, Any]
    ) -> None:
        source = expected.get((instance_id, seed, arm))
        expected_cost = None if source is None else number(source.get("final_cost"))
        row = base_row(
            experiment="E2",
            source_path=path,
            instance_id=instance_id,
            seed=seed,
            arm=arm,
            expected_objective=expected_cost,
        )
        try:
            if expected_cost is None:
                raise RuntimeError("no matching E2 raw-ledger row")
            if instance_id not in bundles:
                bundles[instance_id] = load_china81_bundle(REPO, instance_id)
            bundle = bundles[instance_id]
            current, breakdown, violations = exact_china81_score(
                load_solution(payload), bundle
            )
            compare(
                row,
                saved_breakdown={},
                current_breakdown=breakdown,
                expected_objective=expected_cost,
                current_objective=float(current),
                violations=violations,
                saved_violation_count=0,
            )
        except Exception as exc:  # A diagnostic HALT must retain this source row.
            row["status"] = "HALT_INPUT_OR_INTERFACE_UNRECONSTRUCTABLE"
            row["halt_reason"] = f"{type(exc).__name__}: {exc}"
            if "occupancy disagrees with the charging curve" in str(exc):
                try:
                    evidence = locked_contract_evidence(bundle, load_solution(payload))
                    row.update(
                        {
                            "root_cause_code": evidence["root_cause_code"],
                            "locked_china81_sha256": evidence["locked_china81_sha256"],
                            "locked_china81_commit": evidence["locked_china81_commit"],
                            "locked_battery_kwh": evidence["locked_battery_kwh"],
                            "current_battery_kwh": evidence["current_battery_kwh"],
                            "locked_charging_curve_sha256": evidence[
                                "locked_charging_curve_sha256"
                            ],
                            "old_curve_action_count": evidence["action_count"],
                            "old_curve_max_duration_abs_error_seconds": evidence[
                                "old_curve_max_duration_abs_error_seconds"
                            ],
                            "current_curve_max_duration_abs_error_seconds": evidence[
                                "current_curve_max_duration_abs_error_seconds"
                            ],
                            "root_cause_not_e5": evidence["not_attributed_to_e5"],
                        }
                    )
                except Exception as root_exc:
                    row["halt_reason"] += f"; root-cause verification failed: {type(root_exc).__name__}: {root_exc}"
        rows.append(row)

    for path in sorted(E2.glob("tasks/*/solution_witness.json")):
        instance_id, seed_token, arm = path.parent.name.rsplit("__", 2)
        payload = json.loads(path.read_text(encoding="utf-8"))
        replay(path, instance_id, int(seed_token.removeprefix("seed")), arm, payload)

    labels = {"HGS-F": "F", "HGS-E": "E", "HGS-M": "M", "MV-HGS-SP": "MV"}
    for path in sorted(E2_ARCHIVE.glob("tasks/*/solution_witnesses.json")):
        _, instance_id, seed_token = path.parent.name.rsplit("__", 2)
        payloads = json.loads(path.read_text(encoding="utf-8"))
        for label, payload in sorted(payloads.items()):
            if label not in labels:
                continue
            replay(
                path,
                instance_id,
                int(seed_token.removeprefix("seed")),
                labels[label],
                payload,
            )
    return rows


def replay_e4() -> list[dict[str, Any]]:
    from baselines.china_e3_e7.e4_joint_routing_20260801 import run_probe
    from baselines.china_e3_e7.e4_joint_routing_20260801.joint_soc_wrapper import (
        register_objective,
        score_fixed_solution,
    )

    rows: list[dict[str, Any]] = []
    bundles: dict[str, Any] = {}
    for path in sorted(E4.glob("*/solutions/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        instance_id = str(payload["instance_id"])
        row = base_row(
            experiment="E4",
            source_path=path,
            instance_id=instance_id,
            seed=int(payload["seed"]),
            arm=str(payload["objective_mode"]),
            expected_objective=float(payload["final_objective"]),
        )
        try:
            if instance_id not in bundles:
                bundles[instance_id] = run_probe.load_bundle(instance_id)
            bundle = bundles[instance_id]
            register_objective(bundle, str(payload["objective_mode"]))
            current = score_fixed_solution(
                load_solution(payload["solution"]), bundle, validate_full=True
            )
            compare(
                row,
                saved_breakdown=dict(payload["breakdown"]),
                current_breakdown=dict(current.breakdown),
                expected_objective=float(payload["final_objective"]),
                current_objective=float(current.objective),
                violations=list(current.violations),
                saved_violation_count=0,
            )
        except Exception as exc:
            row["status"] = "HALT_INPUT_OR_INTERFACE_UNRECONSTRUCTABLE"
            row["halt_reason"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows


def replay_e6() -> list[dict[str, Any]]:
    e6_dir = REPO / "baselines/china_e3_e7/e6_contractor_participation_20260801"
    if str(e6_dir) not in sys.path:
        sys.path.insert(0, str(e6_dir))
    from baselines.china_e3_e7.e6_contractor_participation_20260801 import (
        run_pilot06_direct_15 as pilot,
    )

    rows: list[dict[str, Any]] = []
    bases: dict[tuple[str, str], Any] = {}
    for path in sorted(E6.glob("units/*/seed_*/solutions/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        # solution file: units/<instance>/seed_##/solutions/<coalition>.json
        unit = path.parents[1]
        metadata = json.loads((unit / "metadata.json").read_text(encoding="utf-8"))
        instance_id = str(payload["instance_id"])
        mapping_sha = str(metadata["mapping_sha256"])
        coalition = tuple(str(member) for member in payload["coalition"])
        row = base_row(
            experiment="E6",
            source_path=path,
            instance_id=instance_id,
            seed=int(payload["seed"]),
            arm="+".join(coalition),
            expected_objective=float(payload["objective_cny"]),
        )
        try:
            key = (instance_id, mapping_sha)
            if key not in bases:
                bases[key] = pilot.load_base(
                    instance_id, expected_mapping_sha256=mapping_sha
                )[0]
            base = bases[key]
            bundle = pilot.subset_bundle(base, coalition)
            current, breakdown, violations = exact_china81_score(
                load_solution(payload["solution"]), bundle
            )
            compare(
                row,
                saved_breakdown=dict(payload["breakdown"]),
                current_breakdown=breakdown,
                expected_objective=float(payload["objective_cny"]),
                current_objective=float(current),
                violations=violations,
                saved_violation_count=len(payload.get("violations", ())),
            )
        except Exception as exc:
            row["status"] = "HALT_INPUT_OR_INTERFACE_UNRECONSTRUCTABLE"
            row["halt_reason"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows


def e3_not_checkable_row() -> dict[str, Any]:
    row = base_row(experiment="E3", source_path=None)
    row["status"] = "NOT_CHECKABLE_NO_COMPLETE_SAVED_SOLUTIONS"
    row["halt_reason"] = (
        "formal E3 aggregate retains metrics and hashes, not complete solution JSON"
    )
    return row


def output_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }


def run(output: Path, scopes: tuple[str, ...]) -> int:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing diagnostic: {output}")
    output.mkdir(parents=True)
    replayers: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "E2": replay_e2,
        "E4": replay_e4,
        "E6": replay_e6,
    }
    rows: list[dict[str, Any]] = [e3_not_checkable_row()]
    for scope in scopes:
        rows.extend(replayers[scope]())
    rows.sort(
        key=lambda row: (
            row["experiment"],
            row["instance_id"],
            str(row["seed"]),
            row["arm_or_mode_or_coalition"],
        )
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    replay_rows = [row for row in rows if row["experiment"] in scopes]
    failed = [row for row in replay_rows if row["status"] != "PASS_CURRENT_REPLAY_EQUIVALENT"]
    e2_root_cause_rows = [
        row for row in rows if row["root_cause_code"] == E2_ROOT_CAUSE_CODE
    ]
    e2_root_cause = {
        "code": E2_ROOT_CAUSE_CODE,
        "not_attributed_to_e5": True,
        "halt_solution_count": len(e2_root_cause_rows),
        "locked_china81_sha256": E2_LOCKED_CHINA81_SHA256,
        "locked_china81_commit": E2_LOCKED_CHINA81_COMMIT,
        "locked_battery_kwh": E2_LOCKED_BATTERY_KWH,
        "current_battery_kwh": (
            None
            if not e2_root_cause_rows
            else float(e2_root_cause_rows[0]["current_battery_kwh"])
        ),
        "locked_charging_curve_sha256": E2_LOCKED_CHARGING_CURVE_SHA256,
        "old_curve_max_duration_abs_error_seconds": max(
            (float(row["old_curve_max_duration_abs_error_seconds"]) for row in e2_root_cause_rows),
            default=None,
        ),
        "current_curve_min_duration_abs_error_seconds": min(
            (float(row["current_curve_max_duration_abs_error_seconds"]) for row in e2_root_cause_rows),
            default=None,
        ),
        "witness_repair_performed": False,
        "formal_result_changed": False,
    }
    decision_status = (
        "PASS_DIAGNOSTIC_CURRENT_SOURCE_REPLAY_EQUIVALENT"
        if not failed
        else "HALT_DIAGNOSTIC_CURRENT_SOURCE_REPLAY_NON_EQUIVALENT"
    )
    source_paths = (
        Path(__file__),
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
        REPO / "solver/src/setp_solver/search/evaluation.py",
        REPO / "solver/src/setp_solver/china81.py",
        REPO / "solver/src/setp_solver/charging_curve.py",
        REPO / "baselines/china_e3_e7/e4_joint_routing_20260801/run_probe.py",
        REPO / "baselines/china_e3_e7/e4_joint_routing_20260801/joint_soc_wrapper.py",
        REPO / "baselines/china_e3_e7/e6_contractor_participation_20260801/run_pilot06_direct_15.py",
        REPO / "baselines/china_e3_e7/e6_contractor_participation_20260801/e6_methods.py",
        E2 / "raw_runs.json",
        E4 / "raw_runs.csv",
        E6 / "panel_raw_runs.csv",
    )
    metadata = {
        "schema": "resetp.current-source-saved-solution-replay.metadata.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "formal_result": False,
        "diagnostic_scope": list(scopes),
        "zero_search": True,
        "frozen_parameters_reused": True,
        "purpose": "test current E5 default-zero and no-copy compatibility against saved formal solutions",
        "tolerance_absolute": TOLERANCE,
        "e2_halt_root_cause": e2_root_cause,
        "source_hashes": {
            str(path.relative_to(REPO)): sha256(path) for path in source_paths
        },
    }
    decision = {
        "schema": "resetp.current-source-saved-solution-replay.decision.v1",
        "formal_result": False,
        "status": decision_status,
        "replayed_solution_count": len(replay_rows),
        "non_replayable_e3_count": 1,
        "status_counts": counts,
        "failure_count": len(failed),
        "e2_halt_root_cause": e2_root_cause,
        "result_boundary": (
            "This is scorer/checker replay only: it neither reruns search nor upgrades any formal result."
        ),
    }
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    report = "\n".join(
        [
            "# 当前源码保存解重放兼容性诊断",
            "",
            f"状态：`{decision_status}`。",
            "",
            "- `formal_result=false`；未启动搜索、未改变正式参数、未修改任何正式结果。",
            f"- 重放保存解：{len(replay_rows)}；E3 不可检查：1（没有完整保存 solution）。",
            f"- 逐解失败或 HALT：{len(failed)}；绝对容差：{TOLERANCE:g}。",
            "- 六份 E2 HALT 源于锁定 140.41 kWh 与当前 77.28 kWh 电池契约不同；"
            "其保存 action 在锁定曲线下时长误差为 0，不归因于 E5。",
            "- 判断范围仅为当前 `cost.py`/`check.py` 对保存解的合法性和记分兼容性。",
            "",
        ]
    )
    (output / "report.md").write_text(report, encoding="utf-8")
    write_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "artifacts": output_hashes(output),
        },
    )
    return 0 if not failed else 2


def check(output: Path) -> int:
    manifest_path = output / "artifact_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bad = [
        name
        for name, expected in manifest["artifacts"].items()
        if not (output / name).exists() or sha256(output / name) != expected
    ]
    decision = json.loads((output / "decision.json").read_text(encoding="utf-8"))
    if decision.get("formal_result") is not False:
        bad.append("decision.formal_result")
    root_cause = decision.get("e2_halt_root_cause", {})
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("e2_halt_root_cause") != root_cause:
        bad.append("metadata.e2_halt_root_cause")
    if (
        root_cause.get("code") != E2_ROOT_CAUSE_CODE
        or root_cause.get("not_attributed_to_e5") is not True
        or root_cause.get("halt_solution_count") != 6
        or root_cause.get("locked_china81_sha256") != E2_LOCKED_CHINA81_SHA256
        or abs(float(root_cause.get("locked_battery_kwh", -1)) - E2_LOCKED_BATTERY_KWH) > TOLERANCE
        or abs(float(root_cause.get("current_battery_kwh", -1)) - 77.28) > TOLERANCE
        or float(root_cause.get("old_curve_max_duration_abs_error_seconds", float("inf"))) > TOLERANCE
    ):
        bad.append("e2_halt_root_cause")
    raw_rows = list(csv.DictReader((output / "raw_runs.csv").open(encoding="utf-8")))
    root_rows = [row for row in raw_rows if row["root_cause_code"] == E2_ROOT_CAUSE_CODE]
    if (
        len(raw_rows) != 3016
        or len(root_rows) != 6
        or any(
            row["status"] != "HALT_INPUT_OR_INTERFACE_UNRECONSTRUCTABLE"
            or row["halt_reason"] != "ValueError: charging action occupancy disagrees with the charging curve"
            or row["root_cause_not_e5"] != "True"
            or float(row["old_curve_max_duration_abs_error_seconds"]) > TOLERANCE
            for row in root_rows
        )
    ):
        bad.append("raw_runs.e2_halt_root_cause")
    if bad:
        raise RuntimeError("diagnostic check failed: " + ", ".join(bad))
    print(
        json.dumps(
            {
                "status": "PASS_DIAGNOSTIC_ARTIFACT_CHECK",
                "formal_result": False,
                "artifact_count": len(manifest["artifacts"]),
                "replayed_solution_count": decision["replayed_solution_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scope", nargs="+", choices=("E2", "E4", "E6"), default=("E2", "E4", "E6"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return check(args.output) if args.check else run(args.output, tuple(args.scope))


if __name__ == "__main__":
    raise SystemExit(main())
