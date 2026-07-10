from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .carbon import SLOT_SECONDS, carbon_profile_metadata, load_carbon_profile
from .models import DynamicEvent, Node, Scenario


def ensure_data_roots(root: Path) -> dict[str, Path]:
    roots = {
        "raw_instances": root / "raw_instances",
        "generated_instances": root / "generated_instances",
        "dynamic_scenarios": root / "dynamic_scenarios",
        "catalog": root / "catalog",
        "external_sources": root / "external_sources",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return roots


def write_scenario_bundle(
    scenario: Scenario,
    output_dir: str | Path,
    *,
    config: dict[str, Any] | None = None,
    export_evrptwmf: bool = True,
    export_dynamic: bool = True,
) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    instance_path = out / "instance.json"
    nodes_path = out / "nodes.csv"
    matrix_path = out / "distance_matrix.npy"
    depot_scores_path = out / "depot_candidate_scores.csv"
    station_scores_path = out / "station_candidate_scores.csv"
    manifest_path = out / "scenario_manifest.json"
    config_payload = config or {}
    carbon_mode = str(config_payload.get("carbon_alignment_mode", "none"))
    carbon_profile = _load_output_carbon_profile(config_payload, carbon_mode)
    carbon_metadata = carbon_profile_metadata(
        carbon_profile,
        alignment_mode=carbon_mode,
        source_path=str(config_payload.get("carbon_profile_path", "")),
        anchor_utc=config_payload.get("carbon_time_anchor_utc"),
    )
    if carbon_metadata:
        scenario.metadata.update(carbon_metadata)
    scenario.metadata.update(
        {
            # v2026-06-12: keep fleet structure reproducible in both instance.json and scenario_manifest.json.
            "num_cv": int(config_payload.get("num_cv", 10)),
            "num_ev": int(config_payload.get("num_ev", 10)),
            "station_avoid_node_overlap": config_payload.get("station_avoid_node_overlap", True),
            "station_min_node_distance": config_payload.get("station_min_node_distance", 1.0),
            # v2026-06-12: Z0b manifest-facing experiment setting for
            # eq:station_capacity. Public stations are scarce; depots are
            # provisioned by route-count upper bound.
            "public_station_chargers": int(config_payload.get("station_capacity", 1)),
            "depot_chargers_policy": "customer_count_route_upper_bound",
            "depot_chargers": sum(1 for node in scenario.nodes if node.node_type == "c"),
        }
    )

    _write_json(instance_path, scenario.to_instance_dict())
    _write_nodes_csv(nodes_path, scenario.nodes)
    np.save(matrix_path, scenario.distance_matrix)
    _write_dict_rows(depot_scores_path, [row.to_dict() for row in scenario.depot_scores])
    _write_dict_rows(station_scores_path, [row.to_dict() for row in scenario.station_scores])

    files: dict[str, str] = {
        "instance_json": instance_path.name,
        "nodes_csv": nodes_path.name,
        "distance_matrix_npy": matrix_path.name,
        "depot_candidate_scores_csv": depot_scores_path.name,
        "station_candidate_scores_csv": station_scores_path.name,
        "scenario_manifest_json": manifest_path.name,
    }
    if export_evrptwmf:
        txt_path = out / "instance_evrptwmf.txt"
        _write_evrptwmf(
            txt_path,
            scenario.nodes,
            scenario.distance_matrix,
            num_cv=int(config_payload.get("num_cv", 10)),
            num_ev=int(config_payload.get("num_ev", 10)),
        )
        files["evrptwmf_txt"] = txt_path.name
    if export_dynamic and scenario.dynamic_events:
        events_path = out / "dynamic_events.tsv"
        _write_dynamic_events(events_path, scenario.dynamic_events)
        files["dynamic_events_tsv"] = events_path.name
    if carbon_profile:
        carbon_path = out / "carbon_profile.csv"
        _write_carbon_profile(carbon_path, carbon_profile)
        files["carbon_profile_csv"] = carbon_path.name

    manifest = {
        "schema_version": "setp-instance-lab.v1",
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "generator": "setp_instance_lab",
        "generator_version": "0.1.0",
        "config": config_payload,
        "files": files,
        "hashes": {
            name: sha256_file(out / rel_path)
            for name, rel_path in files.items()
            if (out / rel_path).is_file()
        },
        "validation": scenario.validation,
        "metadata": scenario.metadata,
    }
    _write_json(manifest_path, manifest)
    return {name: str(out / rel_path) for name, rel_path in files.items()}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_output_carbon_profile(config: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if mode == "none":
        return []
    csv_path = config.get("carbon_profile_path")
    if not csv_path:
        raise ValueError("carbon_profile_path is required when carbon_alignment_mode is not none")
    horizon_start = float(config.get("horizon_start", 0.0))
    horizon_end = float(config.get("horizon_end", 32400.0))
    n_slots = math.ceil(max(horizon_end - horizon_start, 0.0) / SLOT_SECONDS)
    return load_carbon_profile(
        str(csv_path),
        mode,
        config.get("carbon_time_anchor_utc"),
        n_slots,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_nodes_csv(path: Path, nodes: list[Node]) -> None:
    rows = [node.to_dict() for node in nodes]
    _write_dict_rows(path, rows)


def _write_dict_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_carbon_profile(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "time_index",
        "datetime_utc",
        "actual_gco2_per_kwh",
        "forecast_gco2_per_kwh",
        "index_label",
        "index_code",
        "horizon_second_start",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = dict(row)
            payload["datetime_utc"] = payload["datetime_utc"].isoformat()
            writer.writerow(payload)


def _write_evrptwmf(path: Path, nodes: list[Node], distance_matrix: np.ndarray, *, num_cv: int = 10, num_ev: int = 10) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("StringID  Type  x          y          demand  ReadyTime  DueDate  ServiceTime\n")
        for node in nodes:
            handle.write(
                f"{node.node_id:<9} {node.node_type:<5} {node.x:<11.2f} {node.y:<11.2f} "
                f"{node.demand:<7.1f} {node.ready_time:<10.1f} {node.due_time:<8.1f} {node.service_time:.1f}\n"
            )
        handle.write("\n")
        # v2026-06-12: export actual structural fleet counts for EV-heavy generated variants.
        handle.write(f"m numVeh /{num_cv + num_ev}/\n")
        handle.write(f"m numPetrolVeh /{num_cv}/\n")
        handle.write(f"m numElectroVeh /{num_ev}/\n")
        handle.write("\nDistanceMatrix\n")
        for row in distance_matrix:
            handle.write(" ".join(str(int(round(value))) for value in row))
            handle.write("\n")


def _write_dynamic_events(path: Path, events: list[DynamicEvent]) -> None:
    rows = [event.to_dict() for event in events]
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
