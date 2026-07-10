from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from setp_instance_lab.config import ScenarioConfig
from setp_instance_lab.evrptwmf import pairwise_distances
from setp_instance_lab.generator import generate_scenario
from setp_instance_lab.io import sha256_file, write_scenario_bundle
from setp_instance_lab.models import Node, Scenario
from setp_instance_lab.validation import validate_scenario


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = REPO_ROOT / "models"
DATA_ROOT = MODEL_ROOT / "data_bundle"
RAW_ROOT = DATA_ROOT / "raw_instances" / "goeke_uk"
OUTPUT_ROOT = DATA_ROOT / "generated_instances"
# v2026-06-12: U0/U1 uses the repo-level DESNZ-derived carbon source shared by
# the existing 24h generated bundles, not a model-local copy.
CARBON_SOURCE = REPO_ROOT / "data" / "Carbon" / "\u65f6\u53d8\u78b3\u5f3a\u5ea6" / "regional_carbon_intensity_2025-11-01_to_2025-11-30.csv"
CARBON_ANCHOR_UTC = "2025-11-13T00:00:00+00:00"
HORIZON_SECONDS = 86_400.0
MERGED_ID = "E-UK24h-\u4e09\u73ed-01"


@dataclass(frozen=True)
class ChildSpec:
    base_id: str
    seed: int
    shift_seconds: float

    @property
    def scenario_id(self) -> str:
        return f"{self.base_id}__u0_seed{self.seed}_24h_20251113"


CHILD_SPECS = (
    ChildSpec("E-UK100_01", 1, 0.0),
    ChildSpec("E-UK100_02", 2, 9.0 * 3600.0),
    ChildSpec("E-UK100_03", 3, 18.0 * 3600.0),
)


def main() -> None:
    child_rows = _build_children()
    merged_row = _build_merged(child_rows)
    report = {
        "schema_version": "setp-three-shift-build.v1",
        "build_note": (
            "v2026-06-12: U0/U1 three-shift 24h instance build; "
            "facility layout is shared from E-UK100_01 after isolated-customer diagnostics."
        ),
        "carbon_anchor_utc": CARBON_ANCHOR_UTC,
        "horizon_seconds": HORIZON_SECONDS,
        "children": [_summary_child(row) for row in child_rows],
        "merged": merged_row["manifest"],
    }
    report_path = Path(merged_row["output_dir"]) / "three_shift_build_report.json"
    _write_json(report_path, report)
    _attach_extra_file_to_manifest(Path(merged_row["output_dir"]), "three_shift_build_report_json", report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def _build_children() -> list[dict[str, Any]]:
    first_config = _config(CHILD_SPECS[0], cluster_std_ratio=0.12)
    first_scenario = generate_scenario(first_config)
    facility_layout = {node.node_id: node for node in first_scenario.nodes if node.node_type.lower() in {"d", "f"}}

    rows: list[dict[str, Any]] = []
    for spec in CHILD_SPECS:
        scenario, config, adjustment = _generate_child_with_retries(spec, facility_layout)
        output_dir = OUTPUT_ROOT / spec.scenario_id
        payload = config.to_dict()
        payload.update(
            {
                "base_id": spec.base_id,
                "u0_adjustment": adjustment,
                "facility_layout_source": CHILD_SPECS[0].scenario_id,
                "facility_layout_policy": "reuse E-UK100_01 depots/stations; regenerate distances before validation",
                "max_isolated_customer_share_for_u0": 0.15,
            }
        )
        paths = write_scenario_bundle(scenario, output_dir, config=payload, export_dynamic=False)
        rows.append(
            {
                "spec": spec,
                "config": config,
                "scenario": scenario,
                "output_dir": str(output_dir),
                "paths": paths,
                "adjustment": adjustment,
            }
        )
    return rows


def _generate_child_with_retries(
    spec: ChildSpec,
    facility_layout: dict[str, Node],
) -> tuple[Scenario, ScenarioConfig, dict[str, Any]]:
    # v2026-06-12: exact empirical coordinates produced isolated shares above
    # the U0 threshold on the 100-customer Goeke bases. Keep empirical demand
    # and time windows, but switch customer coordinates to the generator's
    # clustered synthetic mode and retry with tighter clusters only if needed.
    tried: list[dict[str, Any]] = []
    for cluster_std_ratio in (0.12, 0.08, 0.06):
        config = _config(spec, cluster_std_ratio=cluster_std_ratio)
        raw_scenario = generate_scenario(config)
        scenario = _with_shared_facility_layout(raw_scenario, config, facility_layout)
        tried.append(
            {
                "cluster_std_ratio": cluster_std_ratio,
                "validation_passed": scenario.validation.get("passed"),
                "isolated_customer_share": scenario.validation.get("isolated_customer_share"),
            }
        )
        if scenario.validation.get("passed") and float(scenario.validation.get("isolated_customer_share", 1.0)) <= 0.15:
            adjustment = {
                "reason": "isolated_customer_share exceeded 0.15 under exact empirical coordinates in preflight",
                "coord_mode": "synthetic",
                "demand_mode": "empirical",
                "time_window_mode": "empirical",
                "empirical_exact_base": False,
                "cluster_std_ratio": cluster_std_ratio,
                "tried": tried,
            }
            scenario.metadata.update({"u0_adjustment": adjustment})
            return scenario, config, adjustment
    raise RuntimeError(f"U0 failed for {spec.base_id}: {tried}")


def _config(spec: ChildSpec, *, cluster_std_ratio: float) -> ScenarioConfig:
    return ScenarioConfig(
        scenario_id=spec.scenario_id,
        seed=spec.seed,
        base_instance_path=str(RAW_ROOT / f"{spec.base_id}.txt"),
        n_depots=2,
        n_stations=3,
        n_customers=100,
        num_cv=10,
        num_ev=10,
        coord_mode="synthetic",
        demand_mode="empirical",
        time_window_mode="empirical",
        empirical_exact_base=False,
        cluster_std_ratio=cluster_std_ratio,
        max_isolated_customer_share=0.15,
        horizon_start=0.0,
        horizon_end=HORIZON_SECONDS,
        depot_due_time=HORIZON_SECONDS,
        carbon_alignment_mode="fixed_utc_anchor",
        carbon_time_anchor_utc=CARBON_ANCHOR_UTC,
        carbon_profile_path=str(CARBON_SOURCE),
    )


def _with_shared_facility_layout(
    scenario: Scenario,
    config: ScenarioConfig,
    facility_layout: dict[str, Node],
) -> Scenario:
    nodes: list[Node] = []
    for node in scenario.nodes:
        if node.node_type.lower() in {"d", "f"} and node.node_id in facility_layout:
            source = facility_layout[node.node_id]
            nodes.append(
                replace(
                    node,
                    x=source.x,
                    y=source.y,
                    ready_time=source.ready_time,
                    due_time=source.due_time,
                    service_time=source.service_time,
                    station_capacity=source.station_capacity,
                    charge_power_kw=source.charge_power_kw,
                    carbon_region=source.carbon_region,
                )
            )
        else:
            nodes.append(node)
    matrix = _distance_matrix(nodes)
    metadata = dict(scenario.metadata)
    metadata.update(
        {
            "facility_layout_source": CHILD_SPECS[0].scenario_id,
            "facility_layout_policy": "shared depots/stations for U1 three-shift merge",
        }
    )
    out = Scenario(
        scenario_id=scenario.scenario_id,
        seed=scenario.seed,
        nodes=nodes,
        distance_matrix=matrix,
        depot_scores=scenario.depot_scores,
        station_scores=scenario.station_scores,
        dynamic_events=scenario.dynamic_events,
        metadata=metadata,
    )
    out.validation = validate_scenario(nodes, matrix, config)
    return out


def _build_merged(child_rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_layout = {
        node.node_id: node
        for node in child_rows[0]["scenario"].nodes
        if node.node_type.lower() in {"d", "f"}
    }
    _assert_facility_layouts_match(child_rows, source_layout)

    nodes: list[Node] = []
    for node_id in sorted((node_id for node_id in source_layout if node_id.startswith("D")), key=_natural_key):
        nodes.append(replace(source_layout[node_id], ready_time=0.0, due_time=HORIZON_SECONDS, service_time=0.0))

    kept_customers: list[dict[str, Any]] = []
    deleted_customers: list[dict[str, Any]] = []
    customer_idx = 1
    for row in child_rows:
        spec: ChildSpec = row["spec"]
        scenario: Scenario = row["scenario"]
        for customer in [node for node in scenario.nodes if node.node_type.lower() == "c"]:
            shifted_ready = float(customer.ready_time) + spec.shift_seconds
            shifted_due = float(customer.due_time) + spec.shift_seconds
            if spec.base_id == "E-UK100_03" and shifted_due > HORIZON_SECONDS + 1e-9:
                deleted_customers.append(
                    {
                        "source_base_id": spec.base_id,
                        "source_scenario_id": spec.scenario_id,
                        "source_node_id": customer.node_id,
                        "shift_seconds": spec.shift_seconds,
                        "ready_time": customer.ready_time,
                        "due_time": customer.due_time,
                        "shifted_ready_time": shifted_ready,
                        "shifted_due_time": shifted_due,
                        "reason": "shifted_due_time_exceeds_24h",
                    }
                )
                continue
            new_id = f"C{customer_idx:03d}"
            nodes.append(
                Node(
                    new_id,
                    "c",
                    customer.x,
                    customer.y,
                    customer.demand,
                    shifted_ready,
                    shifted_due,
                    customer.service_time,
                )
            )
            kept_customers.append(
                {
                    "new_node_id": new_id,
                    "source_base_id": spec.base_id,
                    "source_scenario_id": spec.scenario_id,
                    "source_node_id": customer.node_id,
                    "shift_seconds": spec.shift_seconds,
                    "ready_time": customer.ready_time,
                    "due_time": customer.due_time,
                    "shifted_ready_time": shifted_ready,
                    "shifted_due_time": shifted_due,
                }
            )
            customer_idx += 1

    for node_id in sorted((node_id for node_id in source_layout if node_id.startswith("F")), key=_natural_key):
        nodes.append(replace(source_layout[node_id], ready_time=0.0, due_time=HORIZON_SECONDS, service_time=0.0))

    matrix = _distance_matrix(nodes)
    config = ScenarioConfig(
        scenario_id=MERGED_ID,
        seed=20251113,
        n_depots=2,
        n_stations=3,
        n_customers=len(kept_customers),
        num_cv=10,
        num_ev=10,
        coord_mode="three_shift_merge",
        demand_mode="empirical",
        time_window_mode="empirical_shifted",
        max_isolated_customer_share=0.15,
        horizon_start=0.0,
        horizon_end=HORIZON_SECONDS,
        depot_due_time=HORIZON_SECONDS,
        carbon_alignment_mode="fixed_utc_anchor",
        carbon_time_anchor_utc=CARBON_ANCHOR_UTC,
        carbon_profile_path=str(CARBON_SOURCE),
    )
    validation = validate_scenario(nodes, matrix, config)
    manifest = {
        "name": MERGED_ID,
        "build_note": "v2026-06-12: U1 24h three-shift merge; customer windows are shifted only.",
        "source_children": [
            {
                "source_base_id": row["spec"].base_id,
                "scenario_id": row["spec"].scenario_id,
                "seed": row["spec"].seed,
                "shift_seconds": row["spec"].shift_seconds,
                "output_dir": row["output_dir"],
                "validation": row["scenario"].validation,
            }
            for row in child_rows
        ],
        "facility_layout_source": child_rows[0]["spec"].scenario_id,
        "deleted_customers": deleted_customers,
        "deleted_customer_count": len(deleted_customers),
        "kept_customer_count": len(kept_customers),
        "total_demand": sum(float(node.demand) for node in nodes if node.node_type.lower() == "c"),
        "return_deadline_seconds": HORIZON_SECONDS,
        "b2_safe": HORIZON_SECONDS <= 86_400.0,
        "validation": validation,
    }
    scenario = Scenario(
        scenario_id=MERGED_ID,
        seed=20251113,
        nodes=nodes,
        distance_matrix=matrix,
        depot_scores=child_rows[0]["scenario"].depot_scores,
        station_scores=child_rows[0]["scenario"].station_scores,
        metadata={
            "source": "three_shift_merge",
            "three_shift_manifest": manifest,
            "num_cv": 10,
            "num_ev": 10,
            "carbon_time_anchor_utc": CARBON_ANCHOR_UTC,
        },
    )
    scenario.validation = validation
    output_dir = OUTPUT_ROOT / MERGED_ID
    payload = config.to_dict()
    payload.update({"source": "three_shift_merge", "three_shift_manifest": manifest})
    paths = write_scenario_bundle(scenario, output_dir, config=payload, export_dynamic=False)

    manifest_path = output_dir / "three_shift_manifest.json"
    _write_json(manifest_path, {**manifest, "kept_customers": kept_customers})
    _attach_extra_file_to_manifest(output_dir, "three_shift_manifest_json", manifest_path)

    return {
        "scenario": scenario,
        "config": config,
        "output_dir": str(output_dir),
        "paths": paths,
        "manifest": {**manifest, "output_dir": str(output_dir)},
    }


def _assert_facility_layouts_match(child_rows: list[dict[str, Any]], source_layout: dict[str, Node]) -> None:
    differences: list[dict[str, Any]] = []
    for row in child_rows:
        scenario: Scenario = row["scenario"]
        for node in scenario.nodes:
            if node.node_type.lower() not in {"d", "f"}:
                continue
            source = source_layout[node.node_id]
            if abs(node.x - source.x) > 1e-9 or abs(node.y - source.y) > 1e-9:
                differences.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "node_id": node.node_id,
                        "x": node.x,
                        "y": node.y,
                        "source_x": source.x,
                        "source_y": source.y,
                    }
                )
    if differences:
        raise RuntimeError(json.dumps({"HALT_U1": "facility_layout_mismatch", "differences": differences}, ensure_ascii=False, indent=2))


def _summary_child(row: dict[str, Any]) -> dict[str, Any]:
    spec: ChildSpec = row["spec"]
    scenario: Scenario = row["scenario"]
    return {
        "source_base_id": spec.base_id,
        "scenario_id": spec.scenario_id,
        "seed": spec.seed,
        "shift_seconds": spec.shift_seconds,
        "output_dir": row["output_dir"],
        "validation": scenario.validation,
        "adjustment": row["adjustment"],
    }


def _distance_matrix(nodes: list[Node]) -> np.ndarray:
    return pairwise_distances(np.asarray([(node.x, node.y) for node in nodes], dtype=float))


def _attach_extra_file_to_manifest(output_dir: Path, key: str, path: Path) -> None:
    manifest_path = output_dir / "scenario_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("files", {})[key] = path.name
    manifest.setdefault("hashes", {})[key] = sha256_file(path)
    _write_json(manifest_path, manifest)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _natural_key(value: str) -> tuple[str, int]:
    prefix = "".join(ch for ch in value if not ch.isdigit())
    digits = "".join(ch for ch in value if ch.isdigit())
    return prefix, int(digits or 0)


if __name__ == "__main__":
    main()
