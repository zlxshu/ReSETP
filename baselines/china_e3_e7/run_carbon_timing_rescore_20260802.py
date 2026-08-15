#!/usr/bin/env python3
"""XD: zero-search current-contract rescore for paper section 5.1.

The runner never constructs or searches a new route.  It reconstructs the
saved fixed-timing arms, deterministically prepares the saved routes for the
explicit multi-trip interface, and evaluates the unchanged content with the
current cost source.  Any infeasibility or frozen-input drift is retained and
forces a HALT decision.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/china_e3_e7/carbon_timing_rescore_20260802"
FIXED_ROOT = ROOT / "baselines/china_e3_e7/e4_carbon_timing_20260729"
JOINT_ROOT = (
    ROOT
    / "baselines/china_e3_e7/e4_joint_routing_20260801"
    / "formal_panel_20260801"
)
FLEET_ROOT = (
    ROOT / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
)
FLEET_EVIDENCE_ROOT = (
    ROOT / "baselines/china_e3_e7/fleet_authority_v3_20260802"
)
RUNTIME_V3 = (
    ROOT / "data/ChinaInstances/china81_runtime_parameter_authority_v3_20260723"
)
RUNTIME_V4 = (
    ROOT / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)
FIXED_COST_CNY = 170.0
EXPECTED_FIXED_SOURCE = 405
EXPECTED_FIXED_PAIRS = 11_340
EXPECTED_FIXED_SOLUTIONS = 22_680
EXPECTED_JOINT_PAIRS = 30
EXPECTED_JOINT_SOLUTIONS = 90
TOL = 1.0e-8

for entry in (
    ROOT,
    ROOT / "solver/src",
    ROOT / "baselines/china_e3_e7/e4_joint_routing_20260801",
):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from joint_soc_wrapper import (  # noqa: E402
    multitrip_soc_contract,
    physical_soc_prices,
    register_objective,
    score_fixed_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import _load_time_profile, load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    _physicalize_multitrip_solution,
    exact_china81_score,
)
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.model_config import (  # noqa: E402
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    ModelConfig,
    model_config_scope,
    strict_multitrip_enabled,
)
from setp_solver.search.e3_multitrip_runtime import (  # noqa: E402
    complete_prepared_solution_violations,
)
from setp_solver.search.metaheuristic_baselines import (  # noqa: E402
    solution_from_dict,
)
from setp_solver.search.multitrip_schedule import (  # noqa: E402
    prepare_multitrip_solution,
    validate_multitrip_certificate,
)
from setp_solver.solution import (  # noqa: E402
    Solution,
    physical_vehicle_id,
    route_trip_vehicle_id,
)


MODEL_CONFIG = ModelConfig(
    strict_multitrip=True,
    depot_charger_capacity_mode=DEPOT_CHARGER_CAPACITY_UNBOUNDED,
)
COST_COMPONENTS = (
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_time",
    "cost_transship",
    "cost_carbon",
)
SOURCE_CODE_PATHS = (
    Path(__file__).resolve(),
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
    ROOT / "solver/src/setp_solver/model_config.py",
    ROOT / "solver/src/setp_solver/solution.py",
    ROOT / "solver/src/setp_solver/china81.py",
    ROOT / "solver/src/setp_solver/china81_completion.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    ROOT / "solver/src/setp_solver/search/certificate_execution.py",
    ROOT / "baselines/china_e3_e7/e4_joint_routing_20260801/joint_soc_wrapper.py",
    ROOT / "baselines/china_e3_e7/e4_carbon_timing_20260729/run_e4_carbon_timing.py",
)
PROTECTED_PATHS = (
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
    ROOT / "docs/paper_v2/RETIRED_paper_main.tex",
)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty required CSV: {path}")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def close(left: Any, right: Any, tolerance: float = TOL) -> bool:
    return math.isclose(
        float(left), float(right), rel_tol=0.0, abs_tol=tolerance
    )


def physical_vehicle_count(solution: Solution) -> int:
    return len(
        {
            (route.vehicle_type.lower(), physical_vehicle_id(route.vehicle_id))
            for route in solution.routes
        }
    )


def physical_counts_by_depot_type(solution: Solution) -> Counter[tuple[str, str]]:
    identities: dict[tuple[str, str], set[str]] = defaultdict(set)
    for route in solution.routes:
        identities[(route.home_depot_id, route.vehicle_type.lower())].add(
            physical_vehicle_id(route.vehicle_id)
        )
    return Counter({key: len(value) for key, value in identities.items()})


def counts_text(counts: Counter[tuple[str, str]]) -> str:
    return "|".join(
        f"{depot}:{vehicle_type}:{count}"
        for (depot, vehicle_type), count in sorted(counts.items())
    )


def fleet_failures(solution: Solution, bundle: Any) -> list[str]:
    counts = physical_counts_by_depot_type(solution)
    failures: list[str] = []
    for depot, caps in sorted(bundle.fleet_caps_by_depot.items()):
        cv = int(counts.get((depot, "cv"), 0))
        ev = int(counts.get((depot, "ev"), 0))
        if cv > int(caps["num_cv"]):
            failures.append(f"{depot}:cv:{cv}>{int(caps['num_cv'])}")
        if ev > int(caps["num_ev"]):
            failures.append(f"{depot}:ev:{ev}>{int(caps['num_ev'])}")
        if cv + ev > int(caps["total_fleet_cap"]):
            failures.append(
                f"{depot}:total:{cv + ev}>{int(caps['total_fleet_cap'])}"
            )
    return failures


def violation_dicts(violations: Iterable[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in violations]


def fixed_bundle(instance_id: str, date: str) -> Any:
    base = load_china81_bundle(
        ROOT,
        instance_id,
        date=date,
        runtime_parameter_authority=RUNTIME_V4,
        fleet_authority=FLEET_ROOT,
        model_config=MODEL_CONFIG,
    )
    cities = {
        str(node.city).strip().lower()
        for node in base.instance.nodes
        if node.city is not None and str(node.city).strip()
    }
    profile = _load_time_profile(
        RUNTIME_V3 / "tariff_carbon_hourly_calendar.csv",
        cities=cities,
        date=date,
        require_explicit_mapping=False,
    )
    return replace(base, time_profile=profile)


def joint_bundle(instance_id: str) -> Any:
    base = load_china81_bundle(
        ROOT,
        instance_id,
        runtime_parameter_authority=RUNTIME_V4,
        fleet_authority=FLEET_ROOT,
        model_config=MODEL_CONFIG,
    )
    return replace(
        base,
        prices=physical_soc_prices(base),
        formal_search_allowed=False,
    )


def unchanged_solution_content(
    source: Solution,
    prepared: Solution,
) -> tuple[bool, list[str], dict[str, str]]:
    failures: list[str] = []
    if len(source.routes) != len(prepared.routes):
        failures.append("route_count")
        return False, failures, {}
    prepared_by_signature: dict[
        tuple[str, str, tuple[str, ...]], list[str]
    ] = defaultdict(list)
    for route in prepared.routes:
        prepared_by_signature[
            (
                route.vehicle_type,
                route.home_depot_id,
                tuple(route.node_sequence),
            )
        ].append(route.vehicle_id)
    route_id_map: dict[str, str] = {}
    for index, before in enumerate(source.routes):
        signature = (
            before.vehicle_type,
            before.home_depot_id,
            tuple(before.node_sequence),
        )
        candidates = prepared_by_signature.get(signature, [])
        if not candidates:
            failures.append(f"route_{index}_content")
            continue
        route_id_map[before.vehicle_id] = candidates.pop(0)
    if any(candidates for candidates in prepared_by_signature.values()):
        failures.append("prepared_route_multiset")
    if len(source.charging_actions) != len(prepared.charging_actions):
        failures.append("charging_action_count")
    else:
        expected_actions: list[dict[str, Any]] = []
        for before in source.charging_actions:
            expected = asdict(before)
            expected["vehicle_id"] = route_id_map.get(
                before.vehicle_id, before.vehicle_id
            )
            expected_actions.append(expected)
        actual_actions = [asdict(after) for after in prepared.charging_actions]
        expected_encoded = sorted(canonical_bytes(item) for item in expected_actions)
        actual_encoded = sorted(canonical_bytes(item) for item in actual_actions)
        if expected_encoded != actual_encoded:
            failures.append("charging_action_multiset")
    if canonical_bytes([asdict(item) for item in source.cross_site_services]) != (
        canonical_bytes([asdict(item) for item in prepared.cross_site_services])
    ):
        failures.append("cross_site_services")
    return not failures, failures, route_id_map


JOINT_TERMINAL_FIELDS = (
    "station_id",
    "energy_kwh",
    "occupancy_minutes",
    "start_second_absolute",
    "start_clock_second",
    "day_offset",
    "end_second_absolute",
)


def terminal_invariants(
    source_rows: Sequence[Mapping[str, Any]],
    rescored_rows: Sequence[Mapping[str, Any]],
    route_id_map: Mapping[str, str],
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    mapped: list[dict[str, Any]] = []
    for row in source_rows:
        item = dict(row)
        item["vehicle_id"] = route_id_map.get(
            str(row["vehicle_id"]), str(row["vehicle_id"])
        )
        mapped.append(item)
    mapped.sort(key=lambda row: (str(row["vehicle_id"]), str(row["station_id"])))
    actual = [dict(row) for row in rescored_rows]
    actual.sort(key=lambda row: (str(row["vehicle_id"]), str(row["station_id"])))
    failures: list[str] = []
    if len(mapped) != len(actual):
        failures.append("terminal_charge_count")
        return False, failures, mapped
    for index, (before, after) in enumerate(zip(mapped, actual)):
        if before["vehicle_id"] != after["vehicle_id"]:
            failures.append(f"terminal_{index}_vehicle_id")
        for field in JOINT_TERMINAL_FIELDS:
            if field in {"station_id"}:
                equal = str(before[field]) == str(after[field])
            elif field == "day_offset":
                equal = int(before[field]) == int(after[field])
            else:
                equal = close(before[field], after[field])
            if not equal:
                failures.append(f"terminal_{index}_{field}")
    return not failures, failures, mapped


def full_solution_payload(
    prepared: Solution,
    certificate: Any,
    *,
    terminal_charges: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "routes": [asdict(item) for item in prepared.routes],
        "charging_actions": [asdict(item) for item in prepared.charging_actions],
        "cross_site_services": [
            asdict(item) for item in prepared.cross_site_services
        ],
        "multitrip_certificate": certificate.as_dict(),
    }
    if terminal_charges:
        payload["terminal_charges"] = [dict(item) for item in terminal_charges]
    return payload


def remap_certificate_to_physicalized_solution(certificate: Any) -> Any:
    """Align certificate route ids with `_physicalize_multitrip_solution`.

    The current exact scorer intentionally keeps the builder's certificate as
    an internal witness while replacing route/action ids in the scored
    solution.  For the archived complete-solution package we remap only those
    witness identifiers so the saved certificate validates against the saved
    physicalized routes; no timing, energy, route, or assignment decision is
    changed.
    """

    id_map = {
        trip.route_id: route_trip_vehicle_id(
            trip.physical_vehicle_id,
            trip.trip_index,
        )
        for trip in certificate.trips
    }
    trips = tuple(
        replace(trip, route_id=id_map[trip.route_id])
        for trip in certificate.trips
    )
    ledger = tuple(
        replace(
            entry,
            after_route_id=id_map[entry.after_route_id],
            before_route_id=(
                None
                if entry.before_route_id is None
                else id_map[entry.before_route_id]
            ),
        )
        for entry in certificate.depot_charge_ledger
    )
    return replace(certificate, trips=trips, depot_charge_ledger=ledger)


def row_cost_fields(
    row: dict[str, Any],
    old_breakdown: Mapping[str, Any],
    new_breakdown: Mapping[str, Any],
    *,
    old_total: float,
    new_total: float,
) -> None:
    for field in COST_COMPONENTS:
        row[f"old_{field}_cny"] = float(old_breakdown.get(field, 0.0))
        row[f"new_{field}_cny"] = float(new_breakdown.get(field, 0.0))
    row["old_total_cost_cny"] = old_total
    row["new_total_cost_cny"] = new_total
    row["old_operating_cost_cny"] = old_total - float(
        old_breakdown.get("cost_carbon", 0.0)
    )
    row["new_operating_cost_cny"] = new_total - float(
        new_breakdown.get("cost_carbon", 0.0)
    )
    row["fixed_cost_delta_cny"] = (
        float(new_breakdown["cost_fix"]) - float(old_breakdown["cost_fix"])
    )
    row["total_cost_delta_cny"] = new_total - old_total


def metric_residuals(
    old_saved: Mapping[str, float], breakdown: Mapping[str, Any]
) -> dict[str, float]:
    return {
        key: float(breakdown[current]) - float(saved)
        for key, (saved, current) in {
            "charging_emissions_kg": (
                old_saved["charging_emissions_kg"],
                "E_ev_indirect",
            ),
            "system_emissions_kg": (
                old_saved["system_emissions_kg"],
                "E_total",
            ),
            "charging_electricity_cost_cny": (
                old_saved["charging_electricity_cost_cny"],
                "cost_elec",
            ),
        }.items()
    }


def metric_fields_from_breakdowns(
    row: dict[str, Any],
    old_breakdown: Mapping[str, Any],
    new_breakdown: Mapping[str, Any],
) -> None:
    mapping = {
        "charging_emissions_kg": "E_ev_indirect",
        "system_emissions_kg": "E_total",
        "charging_electricity_cost_cny": "cost_elec",
        "charging_energy_kwh": "electricity_kwh",
    }
    for output_name, breakdown_name in mapping.items():
        row[f"old_{output_name}"] = float(old_breakdown[breakdown_name])
        row[f"new_{output_name}"] = float(new_breakdown[breakdown_name])


def percent(treatment: float, control: float) -> float:
    if abs(control) <= TOL:
        raise ZeroDivisionError("percentage control is zero")
    return 100.0 * (treatment - control) / control


def pooled_pair_metrics(
    rows: Sequence[Mapping[str, Any]],
    control: str,
    treatment: str,
) -> dict[str, Any]:
    by_arm = {
        arm: [row for row in rows if row["variant"] == arm]
        for arm in (control, treatment)
    }
    metrics = (
        "charging_emissions_kg",
        "system_emissions_kg",
        "charging_electricity_cost_cny",
        "operating_cost_cny",
        "total_cost_cny",
        "cost_fix_cny",
    )
    result: dict[str, Any] = {
        "aggregation": "ratio_of_pooled_arm_sums",
        "control": control,
        "treatment": treatment,
        "pair_count": len(by_arm[control]),
    }
    for generation in ("old", "new"):
        for metric in metrics:
            field = f"{generation}_{metric}"
            control_total = sum(float(row[field]) for row in by_arm[control])
            treatment_total = sum(
                float(row[field]) for row in by_arm[treatment]
            )
            name = metric.removesuffix("_cny").removesuffix("_kg")
            result[f"{generation}_{name}_control"] = control_total
            result[f"{generation}_{name}_treatment"] = treatment_total
            result[f"{generation}_{name}_change_pct"] = percent(
                treatment_total, control_total
            )
    return result


def mean_paired_metrics(
    rows: Sequence[Mapping[str, Any]],
    control: str,
    treatment: str,
) -> dict[str, Any]:
    by_pair: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_pair[str(row["pair_id"])][str(row["variant"])] = row
    metrics = (
        "charging_emissions_kg",
        "system_emissions_kg",
        "charging_electricity_cost_cny",
        "operating_cost_cny",
        "total_cost_cny",
        "cost_fix_cny",
    )
    result: dict[str, Any] = {
        "aggregation": "simple_mean_of_within_pair_percentage_changes",
        "control": control,
        "treatment": treatment,
        "pair_count": len(by_pair),
    }
    for generation in ("old", "new"):
        for metric in metrics:
            field = f"{generation}_{metric}"
            effects = [
                percent(float(arms[treatment][field]), float(arms[control][field]))
                for arms in by_pair.values()
            ]
            name = metric.removesuffix("_cny").removesuffix("_kg")
            result[f"{generation}_{name}_change_pct"] = sum(effects) / len(
                effects
            )
    return result


def read_git_state() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    )
    return commit, dirty


def source_hashes(paths: Sequence[Path]) -> dict[str, str]:
    return {rel(path): sha256_path(path) for path in paths}


def ensure_output_contract() -> None:
    if not OUT.is_dir():
        raise RuntimeError(f"pre-registration directory is missing: {OUT}")
    prereg = OUT / "pre_registration.json"
    if not prereg.is_file():
        raise RuntimeError("pre_registration.json must exist before execution")
    forbidden = (
        "raw_runs.csv",
        "metadata.json",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
        "solutions.jsonl.gz",
        "summary.json",
        "validation_ledger.jsonl",
        "done.json",
    )
    existing = [name for name in forbidden if (OUT / name).exists()]
    if existing:
        raise RuntimeError(f"refusing to overwrite existing XD outputs: {existing}")


def load_fixed_inputs() -> tuple[
    list[dict[str, str]],
    dict[str, dict[str, str]],
    dict[tuple[str, int, str], list[dict[str, str]]],
]:
    manifest = read_csv(FIXED_ROOT / "input_manifest.csv")
    raw = read_csv(FIXED_ROOT / "raw_runs.csv")
    audit = read_csv(FIXED_ROOT / "action_timing_audit.csv")
    if len(manifest) != EXPECTED_FIXED_SOURCE:
        raise RuntimeError(f"fixed source count {len(manifest)} != 405")
    if len(raw) != EXPECTED_FIXED_PAIRS:
        raise RuntimeError(f"fixed pair count {len(raw)} != 11340")
    raw_by_pair = {row["pair_id"]: row for row in raw}
    if len(raw_by_pair) != len(raw):
        raise RuntimeError("duplicate fixed-route pair_id")
    audit_by_key: dict[tuple[str, int, str], list[dict[str, str]]] = defaultdict(
        list
    )
    for row in audit:
        audit_by_key[
            (row["instance_id"], int(row["seed"]), row["grid_date"])
        ].append(row)
    for rows in audit_by_key.values():
        rows.sort(key=lambda row: int(row["action_index"]))
    return manifest, raw_by_pair, audit_by_key


def load_joint_inputs() -> list[dict[str, Any]]:
    paths = sorted(JOINT_ROOT.glob("*/solutions/*.json"))
    paths = [path for path in paths if not path.name.startswith("._")]
    if len(paths) != EXPECTED_JOINT_SOLUTIONS:
        raise RuntimeError(f"joint solution count {len(paths)} != 90")
    out: list[dict[str, Any]] = []
    for path in paths:
        payload = read_json(path)
        out.append({"path": path, "payload": payload})
    identities = {
        (
            item["payload"]["instance_id"],
            int(item["payload"]["seed"]),
            item["payload"]["objective_mode"],
        )
        for item in out
    }
    if len(identities) != EXPECTED_JOINT_SOLUTIONS:
        raise RuntimeError("duplicate joint solution identity")
    pair_count = len({(left, seed) for left, seed, _ in identities})
    if pair_count != EXPECTED_JOINT_PAIRS:
        raise RuntimeError(f"joint pair count {pair_count} != 30")
    return out


def process_fixed(
    solution_writer: io.TextIOBase,
    validation_writer: io.TextIOBase,
    starting_line: int,
) -> tuple[list[dict[str, Any]], int]:
    manifest, old_rows, audits = load_fixed_inputs()
    manifest_by_instance: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in manifest:
        manifest_by_instance[row["instance_id"]].append(row)
    output: list[dict[str, Any]] = []
    solution_line = starting_line
    for instance_index, instance_id in enumerate(sorted(manifest_by_instance), 1):
        sources: dict[int, tuple[dict[str, str], Solution]] = {}
        for meta in manifest_by_instance[instance_id]:
            witness_path = ROOT / meta["witness_path"]
            if sha256_path(witness_path) != meta["witness_sha256"]:
                raise RuntimeError(f"fixed witness hash drift: {witness_path}")
            payload = read_json(witness_path)
            sources[int(meta["seed"])] = (
                meta,
                solution_from_dict(payload["solution"]),
            )
        dates = sorted(
            {
                pair_id.rsplit("__", 1)[1]
                for pair_id, row in old_rows.items()
                if row["instance_id"] == instance_id
            }
        )
        if len(dates) != 28:
            raise RuntimeError(f"{instance_id} has {len(dates)} dates, not 28")
        for date in dates:
            bundle = fixed_bundle(instance_id, date)
            if dict(bundle.model_config) != MODEL_CONFIG.as_metadata():
                raise RuntimeError("explicit fixed-route model config was not bound")
            for seed in sorted(sources):
                meta, source = sources[seed]
                pair_id = f"{instance_id}__seed{seed}__{date}"
                old_pair = old_rows[pair_id]
                action_rows = audits[(instance_id, seed, date)]
                if len(action_rows) != len(source.charging_actions):
                    raise RuntimeError(
                        f"action reconstruction gap for {pair_id}: "
                        f"{len(action_rows)} != {len(source.charging_actions)}"
                    )
                for arm, start_field, old_prefix in (
                    ("ASAP", "asap_start_second", "asap"),
                    ("CARBON", "carbon_start_second", "carbon"),
                ):
                    record_id = f"fixed/{pair_id}/{arm}"
                    starts = {
                        int(row["action_index"]): float(row[start_field])
                        for row in action_rows
                    }
                    arm_solution = replace(
                        source,
                        charging_actions=[
                            replace(action, charge_start_second=starts[index])
                            for index, action in enumerate(
                                source.charging_actions
                            )
                        ],
                    )
                    row: dict[str, Any] = {
                        "task_id": "XD",
                        "population": "FIXED_ROUTE_TIMING",
                        "record_id": record_id,
                        "pair_id": pair_id,
                        "instance_id": instance_id,
                        "seed": seed,
                        "grid_date": date,
                        "variant": arm,
                        "source_path": meta["witness_path"],
                        "source_sha256": meta["witness_sha256"],
                        "source_solution_sha256": canonical_sha256(
                            asdict(arm_solution)
                        ),
                        "route_count": len(arm_solution.routes),
                        "old_unique_physical_vehicle_count": len(
                            arm_solution.routes
                        ),
                        "search_executed": False,
                        "search_evaluations": 0,
                        "status": "",
                        "failure": "",
                    }
                    validation: dict[str, Any] = {
                        "record_id": record_id,
                        "population": "FIXED_ROUTE_TIMING",
                    }
                    try:
                        old_breakdown = evaluate(
                            arm_solution,
                            bundle.instance,
                            bundle.time_profile,
                            bundle.prices,
                        )
                        old_total = float(
                            old_pair[f"{old_prefix}_full_model_cost_cny"]
                        )
                        old_metric_values = {
                            "charging_emissions_kg": float(
                                old_pair[
                                    f"{old_prefix}_charging_emissions_kg"
                                ]
                            ),
                            "system_emissions_kg": float(
                                old_pair[
                                    f"{old_prefix}_system_total_emissions_kg"
                                ]
                            ),
                            "charging_electricity_cost_cny": float(
                                old_pair[
                                    f"{old_prefix}_charging_electricity_cost_cny"
                                ]
                            ),
                        }
                        old_total_residual = float(old_breakdown["total_cost"]) - old_total
                        old_metric_residual = metric_residuals(
                            old_metric_values, old_breakdown
                        )
                        prepared, certificate = _physicalize_multitrip_solution(
                            arm_solution, bundle
                        )
                        certificate = remap_certificate_to_physicalized_solution(
                            certificate
                        )
                        validate_multitrip_certificate(
                            certificate,
                            prepared.routes,
                            bundle.prices,
                            instance=bundle.instance,
                        )
                        invariant_ok, invariant_failures, _ = (
                            unchanged_solution_content(arm_solution, prepared)
                        )
                        exact_objective, exact_breakdown, current_violations = (
                            exact_china81_score(arm_solution, bundle)
                        )
                        fleet = fleet_failures(prepared, bundle)
                        direct_breakdown = evaluate(
                            prepared,
                            bundle.instance,
                            bundle.time_profile,
                            bundle.prices,
                        )
                        new_breakdown = dict(exact_breakdown)
                        exact_residual = max(
                            abs(
                                float(new_breakdown[field])
                                - float(direct_breakdown[field])
                            )
                            for field in new_breakdown
                        )
                        if not close(exact_objective, new_breakdown["total_cost"]):
                            raise RuntimeError("exact objective does not close")
                        if not close(exact_residual, 0.0):
                            raise RuntimeError(
                                f"exact/direct score residual {exact_residual}"
                            )
                        new_metric_residual = metric_residuals(
                            old_metric_values, new_breakdown
                        )
                        replay_ok = close(old_total_residual, 0.0) and all(
                            close(value, 0.0)
                            for value in old_metric_residual.values()
                        )
                        metric_invariants_ok = all(
                            close(value, 0.0)
                            for value in new_metric_residual.values()
                        )
                        feasible = not current_violations and not fleet
                        solution_payload = full_solution_payload(
                            prepared, certificate
                        )
                        solution_sha = canonical_sha256(solution_payload)
                        solution_line += 1
                        solution_writer.write(
                            json.dumps(
                                {
                                    "schema": "resetp.xd-complete-solution.v1",
                                    "record_id": record_id,
                                    "population": "FIXED_ROUTE_TIMING",
                                    "solution_sha256": solution_sha,
                                    "complete_solution": solution_payload,
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        row.update(
                            {
                                "new_unique_physical_vehicle_count": physical_vehicle_count(
                                    prepared
                                ),
                                "physical_counts_by_depot_type": counts_text(
                                    physical_counts_by_depot_type(prepared)
                                ),
                                "certificate_status": certificate.status,
                                "complete_checker_violation_count": len(
                                    current_violations
                                ),
                                "fleet_authority_violation_count": len(fleet),
                                "current_contract_feasible": feasible,
                                "frozen_invariants_match": invariant_ok,
                                "metric_invariants_match": metric_invariants_ok,
                                "old_replay_match": replay_ok,
                                "old_total_replay_residual_cny": old_total_residual,
                                "max_old_metric_residual": max(
                                    map(abs, old_metric_residual.values()),
                                    default=0.0,
                                ),
                                "max_new_metric_residual": max(
                                    map(abs, new_metric_residual.values()),
                                    default=0.0,
                                ),
                                "solution_line_number": solution_line,
                                "solution_sha256": solution_sha,
                                "status": (
                                    "PASS_RESCORED"
                                    if feasible
                                    and invariant_ok
                                    and metric_invariants_ok
                                    and replay_ok
                                    else "HALT_CURRENT_CONTRACT_OR_INVARIANT"
                                ),
                            }
                        )
                        row_cost_fields(
                            row,
                            old_breakdown,
                            new_breakdown,
                            old_total=old_total,
                            new_total=float(new_breakdown["total_cost"]),
                        )
                        metric_fields_from_breakdowns(
                            row, old_breakdown, new_breakdown
                        )
                        validation.update(
                            {
                                "status": row["status"],
                                "certificate": certificate.as_dict(),
                                "frozen_invariant_failures": invariant_failures,
                                "complete_checker_violations": violation_dicts(
                                    current_violations
                                ),
                                "fleet_authority_violations": fleet,
                                "old_metric_residuals": old_metric_residual,
                                "new_metric_residuals": new_metric_residual,
                            }
                        )
                    except Exception as exc:
                        row.update(
                            {
                                "status": "HALT_RECONSTRUCTION_OR_SCORE_FAILED",
                                "failure": f"{type(exc).__name__}: {exc}",
                                "current_contract_feasible": False,
                                "frozen_invariants_match": False,
                                "metric_invariants_match": False,
                                "old_replay_match": False,
                            }
                        )
                        validation.update(
                            {"status": row["status"], "failure": row["failure"]}
                        )
                    output.append(row)
                    validation_writer.write(
                        json.dumps(
                            validation,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
        if instance_index % 9 == 0 or instance_index == len(manifest_by_instance):
            print(
                json.dumps(
                    {
                        "phase": "fixed_route_timing",
                        "instances_done": instance_index,
                        "instances_total": len(manifest_by_instance),
                        "rows": len(output),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return output, solution_line


def process_joint(
    solution_writer: io.TextIOBase,
    validation_writer: io.TextIOBase,
    starting_line: int,
) -> tuple[list[dict[str, Any]], int]:
    inputs = load_joint_inputs()
    bundles: dict[str, Any] = {}
    output: list[dict[str, Any]] = []
    solution_line = starting_line
    for index, item in enumerate(inputs, 1):
        path = item["path"]
        payload = item["payload"]
        instance_id = str(payload["instance_id"])
        seed = int(payload["seed"])
        mode = str(payload["objective_mode"])
        pair_id = f"{instance_id}__seed{seed}"
        record_id = f"joint/{pair_id}/{mode}"
        if instance_id not in bundles:
            bundles[instance_id] = joint_bundle(instance_id)
        bundle = bundles[instance_id]
        register_objective(bundle, mode)
        source = solution_from_dict(payload["solution"])
        old_breakdown = dict(payload["breakdown"])
        old_total = float(old_breakdown["total_cost"])
        row: dict[str, Any] = {
            "task_id": "XD",
            "population": "JOINT_OPTIMIZATION",
            "record_id": record_id,
            "pair_id": pair_id,
            "instance_id": instance_id,
            "seed": seed,
            "grid_date": "2025-02-01",
            "variant": mode,
            "source_path": rel(path),
            "source_sha256": sha256_path(path),
            "source_solution_sha256": canonical_sha256(asdict(source)),
            "route_count": len(source.routes),
            "old_unique_physical_vehicle_count": len(source.routes),
            "search_executed": False,
            "search_evaluations": 0,
            "status": "",
            "failure": "",
        }
        validation: dict[str, Any] = {
            "record_id": record_id,
            "population": "JOINT_OPTIMIZATION",
        }
        try:
            if dict(bundle.model_config) != MODEL_CONFIG.as_metadata():
                raise RuntimeError("explicit joint model config was not bound")
            saved_terminal = list(payload.get("terminal_charges", ()))
            contract = multitrip_soc_contract(saved_terminal)
            prepared, certificate = prepare_multitrip_solution(
                source,
                bundle.instance,
                bundle.prices,
                continuous_soc_contract=contract,
            )
            validate_multitrip_certificate(
                certificate,
                prepared.routes,
                bundle.prices,
                instance=bundle.instance,
            )
            invariant_ok, invariant_failures, route_id_map = (
                unchanged_solution_content(source, prepared)
            )
            current_score = score_fixed_solution(
                prepared, bundle, validate_full=True
            )
            terminal_ok, terminal_failures, mapped_terminal = terminal_invariants(
                saved_terminal,
                current_score.terminal_charges,
                route_id_map,
            )
            invariant_failures.extend(terminal_failures)
            invariant_ok = invariant_ok and terminal_ok
            new_breakdown = dict(current_score.breakdown)
            core_violations = check_solution(
                prepared,
                bundle.instance,
                physical_soc_prices(bundle),
            )
            fleet = fleet_failures(prepared, bundle)
            feasible = not core_violations and not fleet
            invariant_metric_fields = (
                "cost_km",
                "cost_fuel",
                "cost_elec",
                "cost_occ",
                "cost_time",
                "cost_transship",
                "cost_carbon",
                "E_cv_direct",
                "E_ev_indirect",
                "E_total",
                "distance_total",
                "electricity_kwh",
            )
            metric_residual = {
                field: float(new_breakdown.get(field, 0.0))
                - float(old_breakdown.get(field, 0.0))
                for field in invariant_metric_fields
            }
            metric_invariants_ok = all(
                close(value, 0.0) for value in metric_residual.values()
            )
            solution_payload = full_solution_payload(
                prepared,
                certificate,
                terminal_charges=mapped_terminal,
            )
            solution_sha = canonical_sha256(solution_payload)
            solution_line += 1
            solution_writer.write(
                json.dumps(
                    {
                        "schema": "resetp.xd-complete-solution.v1",
                        "record_id": record_id,
                        "population": "JOINT_OPTIMIZATION",
                        "solution_sha256": solution_sha,
                        "complete_solution": solution_payload,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            row.update(
                {
                    "new_unique_physical_vehicle_count": physical_vehicle_count(
                        prepared
                    ),
                    "physical_counts_by_depot_type": counts_text(
                        physical_counts_by_depot_type(prepared)
                    ),
                    "certificate_status": certificate.status,
                    "complete_checker_violation_count": len(core_violations),
                    "fleet_authority_violation_count": len(fleet),
                    "legacy_wrapper_violation_count": len(
                        current_score.violations
                    ),
                    "current_contract_feasible": feasible,
                    "frozen_invariants_match": invariant_ok,
                    "metric_invariants_match": metric_invariants_ok,
                    "old_replay_match": metric_invariants_ok,
                    "old_total_replay_residual_cny": 0.0,
                    "max_old_metric_residual": 0.0,
                    "max_new_metric_residual": max(
                        map(abs, metric_residual.values()), default=0.0
                    ),
                    "solution_line_number": solution_line,
                    "solution_sha256": solution_sha,
                    "status": (
                        "PASS_RESCORED"
                        if feasible and invariant_ok and metric_invariants_ok
                        else "HALT_CURRENT_CONTRACT_OR_INVARIANT"
                    ),
                }
            )
            row_cost_fields(
                row,
                old_breakdown,
                new_breakdown,
                old_total=old_total,
                new_total=float(new_breakdown["total_cost"]),
            )
            metric_fields_from_breakdowns(row, old_breakdown, new_breakdown)
            validation.update(
                {
                    "status": row["status"],
                    "certificate": certificate.as_dict(),
                    "frozen_invariant_failures": invariant_failures,
                    "core_checker_violations": violation_dicts(core_violations),
                    "fleet_authority_violations": fleet,
                    "legacy_wrapper_violations": violation_dicts(
                        current_score.violations
                    ),
                    "metric_residuals": metric_residual,
                }
            )
        except Exception as exc:
            row.update(
                {
                    "status": "HALT_RECONSTRUCTION_OR_SCORE_FAILED",
                    "failure": f"{type(exc).__name__}: {exc}",
                    "current_contract_feasible": False,
                    "frozen_invariants_match": False,
                    "metric_invariants_match": False,
                    "old_replay_match": False,
                }
            )
            validation.update(
                {"status": row["status"], "failure": row["failure"]}
            )
        output.append(row)
        validation_writer.write(
            json.dumps(
                validation,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        if index % 15 == 0 or index == len(inputs):
            print(
                json.dumps(
                    {
                        "phase": "joint_optimization",
                        "rows_done": index,
                        "rows_total": len(inputs),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return output, solution_line


def failure_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fixed = [row for row in rows if row["population"] == "FIXED_ROUTE_TIMING"]
    joint = [row for row in rows if row["population"] == "JOINT_OPTIMIZATION"]

    def bad(selected: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        return [
            row
            for row in selected
            if row["status"] != "PASS_RESCORED"
        ]

    fixed_bad = bad(fixed)
    joint_bad = bad(joint)
    return {
        "fixed_route": {
            "solution_rows": len(fixed),
            "pair_count": len({row["pair_id"] for row in fixed}),
            "failed_solution_rows": len(fixed_bad),
            "affected_pairs": len({row["pair_id"] for row in fixed_bad}),
            "affected_source_instance_seed_units": len(
                {(row["instance_id"], row["seed"]) for row in fixed_bad}
            ),
            "infeasible_solution_rows": sum(
                not bool(row.get("current_contract_feasible", False))
                for row in fixed
            ),
            "invariant_failure_rows": sum(
                not bool(row.get("frozen_invariants_match", False))
                for row in fixed
            ),
        },
        "joint": {
            "solution_rows": len(joint),
            "pair_count": len({row["pair_id"] for row in joint}),
            "failed_solution_rows": len(joint_bad),
            "affected_pairs": len({row["pair_id"] for row in joint_bad}),
            "infeasible_solution_rows": sum(
                not bool(row.get("current_contract_feasible", False))
                for row in joint
            ),
            "invariant_failure_rows": sum(
                not bool(row.get("frozen_invariants_match", False))
                for row in joint
            ),
        },
    }


def render_report(
    summary: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> str:
    fixed = summary["fixed_route_comparison"]
    cost_plus = summary["joint_comparisons"][
        "COST_PLUS_CARBON_vs_COST_ONLY"
    ]
    pure = summary["joint_comparisons"]["PURE_CARBON_vs_COST_ONLY"]
    failures = summary["validation"]
    fixed_cost_delta = (
        fixed["new_cost_fix_change_pct"]
        - fixed["old_cost_fix_change_pct"]
    )
    return f"""# XD：论文 5.1 碳择时数据按新合同零搜索重打分

状态：`{decision['status']}`。

## FACT：输入与规模

固定路线择时输入为 `baselines/china_e3_e7/e4_carbon_timing_20260729/`：405 个完整源解、28 个电网日、11,340 个 ASAP/CARBON 配对、22,680 个重建完整解。联合优化输入为 `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/`：3 个算例、每例 10 个种子、30 个配对单位、90 个完整解（COST_ONLY、COST_PLUS_CARBON、PURE_CARBON）。

本轮没有路线搜索、候选评价、重跑选种子或子集删除。每个输出解均写入 `solutions.jsonl.gz`，其规范化 SHA-256 见 `raw_runs.csv` 的 `solution_sha256`。

## FACT：新合同

多趟显式开启；固定成本为每个去重实体车 170 元；车场充电并发不设上限，公共站容量不变；车队使用 `data/ChinaInstances/china81_finite_fleet_authority_v3_20260802/`。当前 git 提交和全部涉及源码哈希见 `metadata.json`。

## FACT：固定路线 11,340 对的新旧对照

| 指标（CARBON 相对 ASAP） | 旧口径(%) | 新口径(%) | 新减旧（百分点） |
|---|---:|---:|---:|
| 充电侧排放变化 | {fixed['old_charging_emissions_change_pct']:.6f} | {fixed['new_charging_emissions_change_pct']:.6f} | {fixed['new_charging_emissions_change_pct'] - fixed['old_charging_emissions_change_pct']:+.6f} |
| 系统排放变化 | {fixed['old_system_emissions_change_pct']:.6f} | {fixed['new_system_emissions_change_pct']:.6f} | {fixed['new_system_emissions_change_pct'] - fixed['old_system_emissions_change_pct']:+.6f} |
| 充电电费变化 | {fixed['old_charging_electricity_cost_change_pct']:.6f} | {fixed['new_charging_electricity_cost_change_pct']:.6f} | {fixed['new_charging_electricity_cost_change_pct'] - fixed['old_charging_electricity_cost_change_pct']:+.6f} |
| 运营成本变化 | {fixed['old_operating_cost_change_pct']:.6f} | {fixed['new_operating_cost_change_pct']:.6f} | {fixed['new_operating_cost_change_pct'] - fixed['old_operating_cost_change_pct']:+.6f} |
| 固定成本变化 | {fixed['old_cost_fix_change_pct']:.6f} | {fixed['new_cost_fix_change_pct']:.6f} | {fixed_cost_delta:+.6f} |

排放和电费百分比不受固定成本口径影响，因为路线、车型、服务、充电量和充电时刻未进入成本重分类；相应新旧百分比只可能出现浮点尾差。运营成本是否变化以及变化原因由两臂去重实体车数和固定成本差决定，逐解证据见 `raw_runs.csv`。

## FACT：联合优化 30 对的新旧对照

| 比较 | 指标 | 旧口径(%) | 新口径(%) | 新减旧（百分点） |
|---|---|---:|---:|---:|
| COST_PLUS_CARBON / COST_ONLY | 充电侧排放 | {cost_plus['old_charging_emissions_change_pct']:.6f} | {cost_plus['new_charging_emissions_change_pct']:.6f} | {cost_plus['new_charging_emissions_change_pct'] - cost_plus['old_charging_emissions_change_pct']:+.6f} |
| 同上 | 系统排放 | {cost_plus['old_system_emissions_change_pct']:.6f} | {cost_plus['new_system_emissions_change_pct']:.6f} | {cost_plus['new_system_emissions_change_pct'] - cost_plus['old_system_emissions_change_pct']:+.6f} |
| 同上 | 充电电费 | {cost_plus['old_charging_electricity_cost_change_pct']:.6f} | {cost_plus['new_charging_electricity_cost_change_pct']:.6f} | {cost_plus['new_charging_electricity_cost_change_pct'] - cost_plus['old_charging_electricity_cost_change_pct']:+.6f} |
| 同上 | 运营成本 | {cost_plus['old_operating_cost_change_pct']:.6f} | {cost_plus['new_operating_cost_change_pct']:.6f} | {cost_plus['new_operating_cost_change_pct'] - cost_plus['old_operating_cost_change_pct']:+.6f} |
| PURE_CARBON / COST_ONLY | 充电侧排放 | {pure['old_charging_emissions_change_pct']:.6f} | {pure['new_charging_emissions_change_pct']:.6f} | {pure['new_charging_emissions_change_pct'] - pure['old_charging_emissions_change_pct']:+.6f} |
| 同上 | 系统排放 | {pure['old_system_emissions_change_pct']:.6f} | {pure['new_system_emissions_change_pct']:.6f} | {pure['new_system_emissions_change_pct'] - pure['old_system_emissions_change_pct']:+.6f} |
| 同上 | 充电电费 | {pure['old_charging_electricity_cost_change_pct']:.6f} | {pure['new_charging_electricity_cost_change_pct']:.6f} | {pure['new_charging_electricity_cost_change_pct'] - pure['old_charging_electricity_cost_change_pct']:+.6f} |
| 同上 | 运营成本 | {pure['old_operating_cost_change_pct']:.6f} | {pure['new_operating_cost_change_pct']:.6f} | {pure['new_operating_cost_change_pct'] - pure['old_operating_cost_change_pct']:+.6f} |

## DECISION：5.1 能否按当前合同继续使用

固定路线重打分失败解为 {failures['fixed_route']['failed_solution_rows']}/{failures['fixed_route']['solution_rows']}，涉及 {failures['fixed_route']['affected_source_instance_seed_units']} 个源算例—种子。联合优化失败解为 {failures['joint']['failed_solution_rows']}/{failures['joint']['solution_rows']}，涉及 {failures['joint']['affected_pairs']} 个配对单位。

结论方向判定：`{decision['direction_assessment']}`。

当前合同正式可用性判定：`{decision['current_contract_support']}`。

需要搜索的最小范围与完整正式面板范围见 `decision.json` 的 `required_search_scope`。本任务没有擅自启动搜索。

## 记录边界

`raw_runs.csv` 每行记录旧/新总成本、旧/新固定成本、全部成本分项、路线数、去重实体车数、可行性、冻结不变量和 `solution_sha256`。`validation_ledger.jsonl` 保留完整证书及所有不利检查结果。`artifact_hashes.json` 由独立核验步骤最后生成，并排除 `._*`、`__pycache__` 和自身。
"""


def main() -> int:
    ensure_output_contract()
    started_at = utc_now()
    git_commit, worktree_dirty = read_git_state()
    protected_before = source_hashes(PROTECTED_PATHS)
    prereg_sha = sha256_path(OUT / "pre_registration.json")
    solution_tmp = OUT / "solutions.jsonl.gz.tmp"
    validation_tmp = OUT / "validation_ledger.jsonl.tmp"
    solution_line = 0
    with solution_tmp.open("wb") as raw_gzip, gzip.GzipFile(
        fileobj=raw_gzip, mode="wb", mtime=0
    ) as compressed, io.TextIOWrapper(compressed, encoding="utf-8") as solutions, (
        validation_tmp.open("w", encoding="utf-8")
    ) as validations:
        with model_config_scope(MODEL_CONFIG):
            if not strict_multitrip_enabled():
                raise RuntimeError("explicit strict_multitrip=True was not active")
            fixed_rows, solution_line = process_fixed(
                solutions, validations, solution_line
            )
            joint_rows, solution_line = process_joint(
                solutions, validations, solution_line
            )
    solution_tmp.replace(OUT / "solutions.jsonl.gz")
    validation_tmp.replace(OUT / "validation_ledger.jsonl")
    rows = [*fixed_rows, *joint_rows]
    if len(fixed_rows) != EXPECTED_FIXED_SOLUTIONS:
        raise RuntimeError(
            f"fixed output {len(fixed_rows)} != {EXPECTED_FIXED_SOLUTIONS}"
        )
    if len(joint_rows) != EXPECTED_JOINT_SOLUTIONS:
        raise RuntimeError(
            f"joint output {len(joint_rows)} != {EXPECTED_JOINT_SOLUTIONS}"
        )
    write_csv(OUT / "raw_runs.csv", rows)

    fixed_summary = pooled_pair_metrics(fixed_rows, "ASAP", "CARBON")
    joint_summaries = {
        "COST_PLUS_CARBON_vs_COST_ONLY": mean_paired_metrics(
            joint_rows, "COST_ONLY", "COST_PLUS_CARBON"
        ),
        "PURE_CARBON_vs_COST_ONLY": mean_paired_metrics(
            joint_rows, "COST_ONLY", "PURE_CARBON"
        ),
    }
    validation = failure_summary(rows)
    summary = {
        "schema": "resetp.xd-carbon-rescore-summary.v1",
        "fixed_route_comparison": fixed_summary,
        "joint_comparisons": joint_summaries,
        "validation": validation,
    }
    write_json(OUT / "summary.json", summary)

    fixed_direction = (
        fixed_summary["new_charging_emissions_change_pct"] < 0.0
        and fixed_summary["new_system_emissions_change_pct"] < 0.0
    )
    joint_direction = all(
        row["new_system_emissions_change_pct"] < 0.0
        for row in joint_summaries.values()
    )
    output_complete = (
        solution_line == EXPECTED_FIXED_SOLUTIONS + EXPECTED_JOINT_SOLUTIONS
    )
    any_failed = any(
        validation[group]["failed_solution_rows"] > 0
        for group in ("fixed_route", "joint")
    )
    # A changed fixed-cost objective and changed fleet authority mean the old
    # joint-search incumbents cannot establish new-contract optimizer results,
    # even where a saved incumbent remains feasible.  Preserve the arithmetic
    # rescore, but require a full paired rerun for the optimization claim.
    joint_formal_search_required = True
    search_required = any_failed or joint_formal_search_required
    status = (
        "HALT_XD_CURRENT_CONTRACT_REQUIRES_SEARCH"
        if search_required
        else "XD_CARBON_RESCORE_COMPLETE"
    )
    direction_assessment = (
        "UNCHANGED_FOR_ZERO_SEARCH_SAVED_SOLUTIONS"
        if fixed_direction and joint_direction
        else "CHANGED_OR_FALSIFIED_FOR_ZERO_SEARCH_SAVED_SOLUTIONS"
    )
    affected_fixed_sources = validation["fixed_route"][
        "affected_source_instance_seed_units"
    ]
    affected_joint_pairs = validation["joint"]["affected_pairs"]
    decision = {
        "schema": "resetp.xd-carbon-rescore-decision.v1",
        "task_id": "XD",
        "status": status,
        "route_search_executed": False,
        "search_evaluations": 0,
        "all_rows_retained": True,
        "fixed_pair_count": EXPECTED_FIXED_PAIRS,
        "joint_pair_count": EXPECTED_JOINT_PAIRS,
        "complete_solution_count": solution_line,
        "expected_complete_solution_count": (
            EXPECTED_FIXED_SOLUTIONS + EXPECTED_JOINT_SOLUTIONS
        ),
        "complete_solution_output_complete": output_complete,
        "direction_assessment": direction_assessment,
        "fixed_route_direction_reduction_retained": fixed_direction,
        "joint_saved_solution_direction_reduction_retained": joint_direction,
        "current_contract_support": (
            "NOT_FORMALLY_SUPPORTED_WITHOUT_NEW_SEARCH"
            if search_required
            else "SUPPORTED_BY_COMPLETE_ZERO_SEARCH_RESCORE"
        ),
        "reasons": {
            "failed_saved_solution_rows": any_failed,
            "joint_objective_and_feasible_set_changed": True,
            "saved_joint_incumbents_are_not_new_contract_optimization_results": True,
        },
        "required_search_scope": {
            "fixed_route_minimum_if_infeasible": {
                "affected_source_instance_seed_units": affected_fixed_sources,
                "then_replay_grid_days_per_source": 28,
                "then_replay_arms_per_day": 2,
                "note": "Only affected base route units require replacement; the timing replay itself remains zero-search."
            },
            "joint_infeasible_only_minimum": {
                "affected_pair_units": affected_joint_pairs,
                "modes_per_pair": 3,
                "optimization_runs": affected_joint_pairs * 3,
            },
            "joint_formal_current_contract_panel": {
                "pair_units": 30,
                "modes_per_pair": 3,
                "optimization_runs": 90,
                "reason": "fixed-cost objective, multi-trip physical assignment, and fleet authority changed; old incumbents do not prove current-contract optima",
            },
        },
        "preregistered_falsifiers": {
            "F1_FIXED_CHARGING_DIRECTION": not (
                fixed_summary["new_charging_emissions_change_pct"] >= 0.0
            ),
            "F2_FIXED_SYSTEM_DIRECTION": not (
                fixed_summary["new_system_emissions_change_pct"] >= 0.0
            ),
            "F3_JOINT_COST_PLUS_DIRECTION": not (
                joint_summaries["COST_PLUS_CARBON_vs_COST_ONLY"][
                    "new_system_emissions_change_pct"
                ]
                >= 0.0
            ),
            "F4_JOINT_PURE_DIRECTION": not (
                joint_summaries["PURE_CARBON_vs_COST_ONLY"][
                    "new_system_emissions_change_pct"
                ]
                >= 0.0
            ),
            "F5_CURRENT_CONTRACT_INFEASIBLE": not any_failed,
            "F6_FROZEN_INPUT_DRIFT": all(
                bool(row.get("frozen_invariants_match", False))
                for row in rows
            ),
            "F7_POPULATION_INCOMPLETE": output_complete,
        },
    }
    write_json(OUT / "decision.json", decision)

    protected_after = source_hashes(PROTECTED_PATHS)
    if protected_before != protected_after:
        raise RuntimeError("protected source drifted during XD rescore")
    input_paths = (
        FIXED_ROOT / "metadata.json",
        FIXED_ROOT / "decision.json",
        FIXED_ROOT / "raw_runs.csv",
        FIXED_ROOT / "action_timing_audit.csv",
        FIXED_ROOT / "input_manifest.csv",
        JOINT_ROOT / "metadata.json",
        JOINT_ROOT / "decision.json",
        JOINT_ROOT / "raw_runs.csv",
        FLEET_ROOT / "metadata.json",
        FLEET_ROOT / "decision.json",
        FLEET_ROOT / "fleet_caps.csv",
        FLEET_ROOT / "manifest.json",
        FLEET_ROOT / "artifact_hashes.json",
        FLEET_EVIDENCE_ROOT / "metadata.json",
        FLEET_EVIDENCE_ROOT / "decision.json",
        RUNTIME_V3 / "tariff_carbon_hourly_calendar.csv",
        RUNTIME_V4 / "tariff_carbon_hourly_calendar.csv",
    )
    joint_source_manifest = {
        rel(item["path"]): sha256_path(item["path"])
        for item in load_joint_inputs()
    }
    manifest_rows = read_csv(FIXED_ROOT / "input_manifest.csv")
    fixed_source_manifest = {
        row["witness_path"]: row["witness_sha256"] for row in manifest_rows
    }
    metadata = {
        "schema": "resetp.xd-carbon-rescore-metadata.v1",
        "task_id": "XD",
        "status": status,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "git_commit": git_commit,
        "worktree_dirty_before": worktree_dirty,
        "preexisting_changes_preserved": True,
        "change_id": "MC-W1-F2-DEPOT-CONCURRENCY-01",
        "model_config": MODEL_CONFIG.as_metadata(),
        "fixed_cost_contract": {
            "vehicle_fixed_cost_cny": FIXED_COST_CNY,
            "billing_unit": "distinct vehicle_type plus physical_vehicle_id",
            "old_billing_unit": "delivery route or trip",
        },
        "depot_charging_concurrency": "unbounded",
        "public_station_capacity": "finite instance value unchanged",
        "fleet_authority": {
            "version": "v3_20260802",
            "path": rel(FLEET_ROOT),
            "evidence_path": rel(FLEET_EVIDENCE_ROOT),
            "total_physical_vehicles": 943,
            "per_depot_total_range": [2, 22],
        },
        "population": {
            "fixed_source_solutions": EXPECTED_FIXED_SOURCE,
            "fixed_grid_days": 28,
            "fixed_pairs": EXPECTED_FIXED_PAIRS,
            "fixed_complete_solutions": EXPECTED_FIXED_SOLUTIONS,
            "joint_pairs": EXPECTED_JOINT_PAIRS,
            "joint_complete_solutions": EXPECTED_JOINT_SOLUTIONS,
        },
        "solution_archive": {
            "path": rel(OUT / "solutions.jsonl.gz"),
            "format": "gzip JSON Lines, deterministic gzip mtime=0",
            "complete_solution_count": solution_line,
            "solution_hash_rule": "SHA-256 of canonical complete_solution JSON",
        },
        "route_search_executed": False,
        "search_evaluations": 0,
        "metaheuristic_called": False,
        "rescue_tuning": False,
        "all_rows_retained": True,
        "pre_registration_sha256": prereg_sha,
        "source_code_sha256": source_hashes(SOURCE_CODE_PATHS),
        "input_artifact_sha256": source_hashes(input_paths),
        "fixed_source_solution_manifest_sha256": canonical_sha256(
            fixed_source_manifest
        ),
        "joint_source_solution_manifest_sha256": canonical_sha256(
            joint_source_manifest
        ),
        "protected_sha256_before": protected_before,
        "protected_sha256_after": protected_after,
        "artifact_hash_exclusions": [
            "artifact_hashes.json",
            "._*",
            "__pycache__",
            "hidden monitor runtime directories",
        ],
    }
    write_json(OUT / "metadata.json", metadata)
    write_json(OUT / "summary.json", summary)
    (OUT / "report.md").write_text(
        render_report(summary, decision), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": status,
                "rows": len(rows),
                "solutions": solution_line,
                "fixed_failed": validation["fixed_route"][
                    "failed_solution_rows"
                ],
                "joint_failed": validation["joint"]["failed_solution_rows"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
