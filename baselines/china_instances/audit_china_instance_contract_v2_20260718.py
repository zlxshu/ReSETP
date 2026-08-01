"""Read-only hard-parameter audit for a China V2 instance bundle.

The audit is deliberately stricter than the historical DRAFT structure gate.
It checks demand, time windows, facility provenance, charging fields, distance
provenance and 48-slot carbon rows before any solver search is allowed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
DEFAULT_PAYLOAD_CAPACITY_KG = 1300.0
CITY_START_SECONDS = 6 * 3600
CITY_END_SECONDS = 22 * 3600
HORIZON_SECONDS = 24 * 3600


def _error(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _contains_legacy_marker(value: Any) -> bool:
    text = str(value).lower()
    return any(marker in text for marker in ("goeke", "goeke_uk", "£", "gbp", "united kingdom", "uk 2025"))


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _matrix_errors(
    matrix: np.ndarray | None,
    node_count: int,
    label: str,
) -> list[dict[str, str]]:
    if matrix is None:
        return [_error(f"{label}_MATRIX_MISSING", f"{label.lower()} matrix missing")]
    value = np.asarray(matrix, dtype=float)
    if value.shape != (node_count, node_count):
        return [
            _error(
                f"{label}_MATRIX_SHAPE_INVALID",
                f"{value.shape} != {(node_count, node_count)}",
            )
        ]
    if not np.isfinite(value).all():
        return [_error(f"{label}_MATRIX_NONFINITE", "matrix contains NaN or infinity")]
    if np.any(value < 0) or not np.allclose(np.diag(value), 0.0, atol=1e-6):
        return [
            _error(
                f"{label}_MATRIX_BASIC_INVARIANT_FAILED",
                "negative value or nonzero diagonal",
            )
        ]
    if np.any(value[~np.eye(node_count, dtype=bool)] <= 0):
        return [
            _error(
                f"{label}_MATRIX_OFF_DIAGONAL_NOT_POSITIVE",
                "every directed off-diagonal value must be positive",
            )
        ]
    return []


def audit_instance(
    payload: dict[str, Any],
    nodes: list[dict[str, Any]],
    distance_matrix: np.ndarray | None,
    carbon_rows: list[dict[str, Any]] | None,
    duration_matrix: np.ndarray | None = None,
    sum_v2d_matrix: np.ndarray | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {}
    customers = [node for node in nodes if str(node.get("node_type", "")).lower() == "c"]
    depots = [node for node in nodes if str(node.get("node_type", "")).lower() == "d"]
    stations = [node for node in nodes if str(node.get("node_type", "")).lower() == "f"]
    metrics: dict[str, Any] = {
        "customers": len(customers),
        "depots": len(depots),
        "stations": len(stations),
    }

    if (
        payload.get("formal_experiment_authorized") is not False
        or payload.get("draft_only") is not True
    ):
        errors.append(
            _error(
                "FORMAL_FLAG_NOT_CLOSED",
                "pre-acceptance V2 candidate requires formal_experiment_authorized=false and draft_only=true",
            )
        )
    if payload.get("demand_unit") != "kg" or payload.get("distance_unit") not in {"meter", "metre"}:
        errors.append(_error("UNIT_CONTRACT_INVALID", "demand must be kg and distance must be meter"))
    price_contract = metadata.get("price_contract", {})
    if price_contract.get("currency") != "CNY":
        errors.append(_error("CURRENCY_NOT_CNY", str(price_contract.get("currency"))))
    if any(_contains_legacy_marker(value) for value in (payload, metadata)):
        errors.append(_error("LEGACY_FOREIGN_PARAMETER_MARKER", "payload contains Goeke/UK/GBP marker"))

    vehicle_contract = metadata.get("vehicle_contract", {})
    max_demand = float(vehicle_contract.get("minimum_payload_capacity_kg", DEFAULT_PAYLOAD_CAPACITY_KG))
    if max_demand <= 0:
        errors.append(_error("PAYLOAD_CAPACITY_INVALID", str(max_demand)))
    demand_values: list[float] = []
    widths: list[float] = []
    for node in customers:
        node_id = str(node.get("node_id", "?"))
        demand = node.get("demand")
        ready = node.get("ready_time")
        due = node.get("due_time")
        service = node.get("service_time")
        if not _finite_number(demand) or float(demand) <= 0:
            errors.append(_error("DEMAND_NOT_POSITIVE", node_id))
        else:
            demand_values.append(float(demand))
            if float(demand) > max_demand + 1e-9:
                errors.append(_error("DEMAND_EXCEEDS_SELECTED_PAYLOAD", f"{node_id}: {demand}>{max_demand}"))
        if not all(_finite_number(value) for value in (ready, due, service)):
            errors.append(_error("TIME_FIELD_NOT_FINITE", node_id))
            continue
        width = float(due) - float(ready)
        widths.append(width)
        if not (0 <= float(ready) < float(due) <= HORIZON_SECONDS):
            errors.append(_error("TIME_WINDOW_INVALID", node_id))
        if float(service) <= 0 or float(service) >= width:
            errors.append(_error("SERVICE_TIME_NOT_WITHIN_WINDOW", node_id))

    window_mode = str(metadata.get("customer_contract", {}).get("service_window_mode", ""))
    if window_mode != "city_06_22":
        errors.append(_error("TIME_WINDOW_MODE_UNDECLARED", window_mode or "missing"))
    else:
        for node in customers:
            if float(node.get("ready_time", -1)) < CITY_START_SECONDS or float(node.get("due_time", -1)) > CITY_END_SECONDS:
                errors.append(_error("CITY_WINDOW_OUTSIDE_06_22", str(node.get("node_id", "?"))))
    if len(customers) >= 2 and len({round(width, 6) for width in widths}) < 2:
        errors.append(_error("TIME_WINDOW_WIDTH_NOT_VARIED", "all customer windows have the same width"))
    metrics.update(
        {
            "total_demand_kg": round(sum(demand_values), 6),
            "demand_min_kg": min(demand_values) if demand_values else None,
            "demand_max_kg": max(demand_values) if demand_values else None,
            "window_width_min_seconds": min(widths) if widths else None,
            "window_width_max_seconds": max(widths) if widths else None,
        }
    )

    if not depots:
        errors.append(_error("NO_DEPOT", "at least one named depot is required"))
    for depot in depots:
        node_id = str(depot.get("node_id", "?"))
        source_kind = str(depot.get("source_kind", "")).lower()
        if "industrial" in source_kind or "landuse" in source_kind:
            errors.append(_error("DEPOT_IS_GENERIC_INDUSTRIAL_CANDIDATE", node_id))
        for field in ("facility_id", "facility_name_zh", "source_url", "source_capture_sha256", "operating_status"):
            if depot.get(field) in (None, ""):
                errors.append(_error("DEPOT_FIELD_MISSING", f"{node_id}.{field}"))
    if not stations:
        errors.append(_error("NO_PUBLIC_STATION", "at least one source-bound public station is required"))
    for station in stations:
        node_id = str(station.get("node_id", "?"))
        power = station.get("charge_power_kw")
        chargers = station.get("station_chargers")
        if not _finite_number(power) or float(power) <= 0:
            errors.append(_error("STATION_POWER_INVALID", node_id))
        if not isinstance(chargers, int) or chargers <= 0:
            errors.append(_error("STATION_GUN_COUNT_INVALID", node_id))
        provenance = str(station.get("charger_count_provenance", "")).lower()
        if not provenance or any(marker in provenance for marker in ("default", "derived", "missing")):
            errors.append(_error("STATION_GUN_COUNT_UNSUPPORTED_DEFAULT", node_id))
        for field in ("station_name_zh", "source_url", "source_capture_sha256", "operator"):
            if station.get(field) in (None, ""):
                errors.append(_error("STATION_FIELD_MISSING", f"{node_id}.{field}"))

    distance_contract = metadata.get("distance_contract", {})
    rule = str(metadata.get("distance_rule", ""))
    if "road_network" not in rule.lower() or not distance_contract.get("router_name"):
        errors.append(_error("ROAD_DISTANCE_CONTRACT_MISSING", rule or "missing"))
    distance_errors = _matrix_errors(distance_matrix, len(nodes), "DISTANCE")
    errors.extend(distance_errors)
    errors.extend(_matrix_errors(duration_matrix, len(nodes), "DURATION"))
    errors.extend(_matrix_errors(sum_v2d_matrix, len(nodes), "SUM_V2D"))
    if not distance_errors and distance_matrix is not None:
        matrix = np.asarray(distance_matrix, dtype=float)
        if matrix.shape == (len(nodes), len(nodes)):
            customer_indices = [nodes.index(node) for node in customers]
            depot_indices = [nodes.index(node) for node in depots]
            station_indices = [nodes.index(node) for node in stations]
            if any(not np.isfinite(matrix[index, depot_indices]).any() for index in customer_indices):
                errors.append(_error("CUSTOMER_DEPOT_ROAD_REACHABILITY_FAILED", "some customer has no reachable depot"))
            if any(not np.isfinite(matrix[index, station_indices]).any() for index in customer_indices):
                errors.append(_error("CUSTOMER_STATION_ROAD_REACHABILITY_FAILED", "some customer has no reachable station"))

    carbon = metadata.get("carbon_curve", {})
    if carbon.get("data_nature", "").lower().find("projected") < 0 or carbon.get("source_sha256") in (None, ""):
        errors.append(_error("CARBON_SOURCE_CONTRACT_MISSING", "China projected TVCI source and hash are required"))
    if carbon_rows is None or len(carbon_rows) != 48:
        errors.append(_error("CARBON_SLOT_COUNT_INVALID", str(len(carbon_rows) if carbon_rows is not None else None)))
    else:
        column = str(carbon.get("column", ""))
        for row_index, row in enumerate(carbon_rows):
            if column not in row:
                errors.append(_error("CARBON_COLUMN_MISSING", f"{column}@row{row_index}"))
                break
            try:
                value = float(row[column])
            except (TypeError, ValueError):
                errors.append(_error("CARBON_VALUE_INVALID", f"{column}@row{row_index}"))
                break
            if not math.isfinite(value) or value < 0:
                errors.append(_error("CARBON_VALUE_INVALID", f"{column}@row{row_index}"))
                break

    return {
        "schema": "resetp.china.instance-contract-audit.v2",
        "pass": not errors,
        "formal_search_allowed": False,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "search_evaluations": 0,
    }


def _load_matrix_csv(path: Path, nodes: list[dict[str, Any]]) -> np.ndarray | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    node_ids = [str(node["node_id"]) for node in nodes]
    if not rows or rows[0][1:] != node_ids or [row[0] for row in rows[1:]] != node_ids:
        raise ValueError(f"matrix node order drift: {path}")
    return np.asarray([[float(value) for value in row[1:]] for row in rows[1:]])


def _load_bundle(
    bundle: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    np.ndarray | None,
    np.ndarray | None,
    np.ndarray | None,
    list[dict[str, Any]] | None,
]:
    payload = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
    nodes_path = bundle / "nodes.csv"
    if nodes_path.is_file():
        with nodes_path.open(encoding="utf-8", newline="") as handle:
            nodes = list(csv.DictReader(handle))
        for node in nodes:
            for field in ("demand", "ready_time", "due_time", "service_time", "x", "y"):
                if field in node:
                    try:
                        node[field] = float(node[field])
                    except ValueError:
                        pass
            if "station_chargers" in node and node["station_chargers"] not in ("", None):
                try:
                    node["station_chargers"] = int(float(node["station_chargers"]))
                except ValueError:
                    pass
    else:
        nodes = payload.get("nodes", [])
    legacy_matrix_path = bundle / "distance_matrix.npy"
    distance = (
        _load_matrix_csv(bundle / "road_distance_m.csv", nodes)
        if (bundle / "road_distance_m.csv").is_file()
        else (
            np.load(legacy_matrix_path, allow_pickle=False)
            if legacy_matrix_path.is_file()
            else None
        )
    )
    duration = _load_matrix_csv(bundle / "road_duration_s.csv", nodes)
    sum_v2d = _load_matrix_csv(bundle / "road_sum_v2d_m3_s2.csv", nodes)
    carbon_path = bundle / "carbon_profile.csv"
    if carbon_path.is_file():
        with carbon_path.open(encoding="utf-8", newline="") as handle:
            carbon_rows = list(csv.DictReader(handle))
    else:
        carbon_rows = None
    return payload, nodes, distance, duration, sum_v2d, carbon_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    payload, nodes, distance, duration, sum_v2d, carbon_rows = _load_bundle(bundle)
    result = audit_instance(
        payload,
        nodes,
        distance,
        carbon_rows,
        duration,
        sum_v2d,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
