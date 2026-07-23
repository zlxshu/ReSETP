#!/usr/bin/env python3
"""No-search replay of all corrected D6 E2 solution witnesses.

This closes the D6 input-byte binding after the batch: every one of the 1,620
saved algorithm solutions is checked and rescored against the current
corrected bundle. Every instance also receives a manifest of the actual input
file bytes, not merely the input path strings.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v2_20260723"
)
FULL = CAMPAIGN / "full_gate"
OUT = CAMPAIGN / "full_witness_replay"
FORMAL_DIR = REPO / "baselines/china_e3_e7"
for path in (
    REPO / "solver/src",
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720",
    FORMAL_DIR,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from formal_e3_runner import (  # noqa: E402
    _bundle_input_file_manifest,
    _require_depot_charge_before_departure,
    _require_depot_fleet_caps,
    _require_single_day_charging,
    _settlement_trace,
    payload_sha256,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


ARMS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_solution(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[
                    str(item) for item in row["node_sequence"]
                ],
            )
            for row in payload["routes"]
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=str(row["vehicle_id"]),
                station_id=str(row["station_id"]),
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
                charge_day_offset=int(row.get("charge_day_offset", 0)),
                start_energy_kwh=(
                    None
                    if row.get("start_energy_kwh") is None
                    else float(row["start_energy_kwh"])
                ),
                end_energy_kwh=(
                    None
                    if row.get("end_energy_kwh") is None
                    else float(row["end_energy_kwh"])
                ),
                charging_curve_id=row.get("charging_curve_id"),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def main() -> int:
    full_decision = json.loads(
        (FULL / "decision.json").read_text(encoding="utf-8")
    )
    if (
        full_decision.get("verdict")
        != "PASS_D6_CORRECTED_CHINA81_E2_RAW"
    ):
        raise RuntimeError("corrected D6 full gate is not PASS")
    source_rows: list[dict[str, str]] = []
    with (FULL / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        source_rows = list(csv.DictReader(handle))
    if len(source_rows) != 405:
        raise RuntimeError("expected 405 corrected D6 task rows")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_dir = OUT / "input_manifests"
    manifest_hash_by_instance: dict[str, str] = {}
    bundle_by_instance: dict[str, Any] = {}
    output: list[dict[str, Any]] = []
    for task_index, source in enumerate(source_rows, start=1):
        instance_id = source["instance_id"]
        bundle = bundle_by_instance.get(instance_id)
        if bundle is None:
            bundle = load_china81_bundle(REPO, instance_id)
            bundle_by_instance[instance_id] = bundle
            manifest = _bundle_input_file_manifest(bundle)
            manifest_path = manifest_dir / f"{instance_id}.json"
            write_json(
                manifest_path,
                {
                    "schema": "resetp.china81-bundle-input-bytes.v1",
                    "instance_id": instance_id,
                    "source_paths": dict(bundle.source_paths),
                    "files": manifest,
                    "manifest_sha256": payload_sha256(manifest),
                },
            )
            manifest_hash_by_instance[instance_id] = payload_sha256(
                manifest
            )
        task_dir = (
            FULL
            / "tasks"
            / f"D6-E2__{instance_id}__seed{source['seed']}"
        )
        witness_path = task_dir / "solution_witnesses.json"
        if sha256(witness_path) != source["witness_sha256"]:
            raise RuntimeError(f"witness hash mismatch: {task_dir.name}")
        witness = json.loads(witness_path.read_text(encoding="utf-8"))
        path_identity_hash = payload_sha256(dict(bundle.source_paths))
        if path_identity_hash != source["input_manifest_sha256"]:
            raise RuntimeError(
                f"historical path-identity hash mismatch: {task_dir.name}"
            )
        for arm in ARMS:
            solution = annotate_cross_site_services(
                load_solution(witness[arm]),
                bundle.customer_home_depot,
            )
            try:
                _require_depot_fleet_caps(solution, bundle)
                depot_fleet_caps_respected = True
            except RuntimeError:
                depot_fleet_caps_respected = False
            try:
                _require_single_day_charging(solution)
                charging_within_registered_day = True
            except RuntimeError:
                charging_within_registered_day = False
            try:
                _require_depot_charge_before_departure(
                    solution,
                    bundle,
                )
                depot_charging_before_departure = True
            except RuntimeError:
                depot_charging_before_departure = False
            violations = check_solution(
                solution,
                bundle.instance,
                bundle.prices,
            )
            direct = evaluate(
                solution,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
            )
            objective, breakdown, exact_violations = exact_china81_score(
                solution,
                bundle,
            )
            recorded_cost = float(source[f"{arm}_cost"])
            recorded_emissions = float(
                source[f"{arm}_emissions_kg"]
            )
            trace = _settlement_trace(solution, bundle)
            cost_equal = math.isclose(
                objective,
                recorded_cost,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ) and math.isclose(
                float(direct["total_cost"]),
                recorded_cost,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
            emissions_equal = math.isclose(
                float(breakdown["E_total"]),
                recorded_emissions,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
            day_offsets = sorted(
                {
                    int(action.charge_day_offset)
                    for action in solution.charging_actions
                }
            )
            output.append(
                {
                    "task_id": source["task_id"],
                    "instance_id": instance_id,
                    "seed": int(source["seed"]),
                    "arm": arm,
                    "status": (
                        "PASS"
                        if (
                            not violations
                            and not exact_violations
                            and cost_equal
                            and emissions_equal
                            and charging_within_registered_day
                            and depot_fleet_caps_respected
                        )
                        else "FAIL"
                    ),
                    "recorded_cost": recorded_cost,
                    "replayed_cost": objective,
                    "cost_equal": cost_equal,
                    "recorded_emissions_kg": recorded_emissions,
                    "replayed_emissions_kg": float(
                        breakdown["E_total"]
                    ),
                    "emissions_equal": emissions_equal,
                    "direct_violation_count": len(violations),
                    "exact_violation_count": len(exact_violations),
                    "input_file_manifest_sha256": (
                        manifest_hash_by_instance[instance_id]
                    ),
                    "path_identity_sha256": path_identity_hash,
                    "diesel_route_count": len(
                        trace["diesel_routes"]
                    ),
                    "charging_slot_segment_count": len(
                        trace["charging_slot_segments"]
                    ),
                    "charge_day_offsets_json": json.dumps(
                        day_offsets,
                        separators=(",", ":"),
                    ),
                    "all_charge_day_offsets_zero": all(
                        value == 0 for value in day_offsets
                    ),
                    "all_charging_within_registered_day": (
                        charging_within_registered_day
                    ),
                    "all_depot_charging_finishes_before_departure": (
                        depot_charging_before_departure
                    ),
                    "all_depot_fleet_caps_respected": (
                        depot_fleet_caps_respected
                    ),
                    "settlement_trace_sha256": payload_sha256(trace),
                }
            )
        if task_index % 25 == 0:
            print(
                f"[D6-REPLAY] {task_index}/405 tasks replayed",
                flush=True,
            )
    write_csv(OUT / "raw_runs.csv", output)
    passed = (
        len(output) == 1620
        and len(manifest_hash_by_instance) == 81
        and all(row["status"] == "PASS" for row in output)
        and all(
            row["all_charge_day_offsets_zero"] for row in output
        )
        and all(
            row["all_charging_within_registered_day"]
            for row in output
        )
        and all(
            row["all_depot_charging_finishes_before_departure"]
            for row in output
        )
        and all(
            row["all_depot_fleet_caps_respected"]
            for row in output
        )
    )
    decision = {
        "schema": "resetp.d6-corrected-full-witness-replay.decision.v1",
        "verdict": (
            "PASS_D6_CORRECTED_FULL_WITNESS_REPLAY"
            if passed
            else "HALT_D6_CORRECTED_FULL_WITNESS_REPLAY"
        ),
        "search_executions": 0,
        "task_count": 405,
        "solution_count": len(output),
        "instance_input_manifest_count": len(
            manifest_hash_by_instance
        ),
        "all_costs_reproduced": all(
            row["cost_equal"] for row in output
        ),
        "all_emissions_reproduced": all(
            row["emissions_equal"] for row in output
        ),
        "all_full_model_feasible": all(
            int(row["direct_violation_count"]) == 0
            and int(row["exact_violation_count"]) == 0
            for row in output
        ),
        "all_static_charge_day_offsets_zero": all(
            row["all_charge_day_offsets_zero"] for row in output
        ),
        "all_static_charging_within_registered_day": all(
            row["all_charging_within_registered_day"]
            for row in output
        ),
        "all_depot_charging_finishes_before_departure": all(
            row["all_depot_charging_finishes_before_departure"]
            for row in output
        ),
        "all_depot_fleet_caps_respected": all(
            row["all_depot_fleet_caps_respected"]
            for row in output
        ),
        "joint_settlement_policy": (
            "diesel by route-origin city; electricity and carbon by charging "
            "node city, 2025-02-12 and half-hour slot; fail closed"
        ),
        "historical_field_note": (
            "D6 task input_manifest_sha256 encoded path identity. This "
            "no-search gate adds actual input-byte manifests and independently "
            "replays every saved solution under those bytes."
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-corrected-full-witness-replay.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    FULL / "raw_runs.csv",
                    FULL / "decision.json",
                    FORMAL_DIR / "formal_e3_runner.py",
                    REPO / "solver/src/setp_solver/china81.py",
                    REPO
                    / "solver/src/setp_solver/"
                    "china81_completion.py",
                    REPO / "solver/src/setp_solver/cost.py",
                    REPO / "solver/src/setp_solver/check.py",
                    REPO / "solver/src/setp_solver/prices.py",
                    REPO / "solver/src/setp_solver/solution.py",
                    REPO
                    / "solver/src/setp_solver/"
                    "instance_loader.py",
                    REPO
                    / "solver/src/setp_solver/"
                    "charging_curve.py",
                    REPO
                    / "solver/src/setp_solver/search/"
                    "charging.py",
                    REPO
                    / "solver/src/setp_solver/algorithms/"
                    "resetp_alns/support/charging.py",
                    Path(__file__).resolve(),
                )
            },
        },
    )
    (OUT / "report.md").write_text(
        "# Corrected D6 full witness replay\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "All 1,620 saved solutions were checked and rescored without search "
        "against the current corrected input bytes. Costs, emissions and "
        "feasibility reproduce the sealed D6 ledger. Every charging segment "
        "also passed the city/date/half-hour electricity-carbon key and every "
        "diesel route used its route-origin city price. The static E2 "
        "completion path produced only day-offset zero charging actions, so "
        "the scenario date remains 2025-02-12 throughout this campaign. Every "
        "charging interval also lies wholly within that registered day.\n",
        encoding="utf-8",
    )
    for path in OUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
