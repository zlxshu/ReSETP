#!/usr/bin/env python3
"""Z1 zero-search saved-solution regression; never launches path search."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "baselines/china_e3_e7/blocker_fix_20260802"
for entry in (REPO, REPO / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from baselines.china_e3_e7 import (  # noqa: E402
    diagnose_saved_solution_multitrip_repack_20260801 as replay,
)
from setp_solver.model_config import (  # noqa: E402
    ModelConfig,
    model_config_scope,
    strict_multitrip_enabled,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict  # noqa: E402


SAMPLE_COUNT = 30
FIELDS = (
    "record_id",
    "experiment",
    "instance_id",
    "seed",
    "variant",
    "source_path",
    "source_sha256",
    "selection_index",
    "population_count",
    "multitrip_off",
    "off_status",
    "off_failure",
    "off_objective_bitwise_equal",
    "off_components_bitwise_equal",
    "off_component_count",
    "off_mismatch_fields",
    "off_violation_count",
    "current_objective",
    "saved_objective",
    "multitrip_on",
    "on_status",
    "on_failure",
    "on_certificate_valid",
    "on_interface_directly_usable",
    "on_complete_checker_violation_count",
    "on_depot_fleet_violation_count",
    "original_route_count",
    "packed_physical_vehicle_count",
    "saved_physical_vehicle_count",
    "prepared_solution_sha256",
    "certificate_record_sha256",
    "overall_status",
)


def spread_sample(specs: list[dict[str, Any]], count: int) -> list[tuple[int, dict[str, Any]]]:
    """Deterministically cover the complete sorted population, including both ends."""

    ordered = sorted(specs, key=replay.spec_record_id)
    if len(ordered) < count:
        raise RuntimeError(f"population {len(ordered)} is smaller than requested sample {count}")
    if count == 1:
        indices = [0]
    else:
        indices = [round(i * (len(ordered) - 1) / (count - 1)) for i in range(count)]
    if len(set(indices)) != count:
        raise RuntimeError(f"spread selection produced duplicate indices: {indices}")
    return [(idx, ordered[idx]) for idx in indices]


def main() -> int:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing result directory: {OUT}")
    OUT.mkdir(parents=True)
    specs = replay.source_specs()
    selected: list[tuple[int, int, dict[str, Any]]] = []
    for experiment in ("E4", "E6"):
        population = [spec for spec in specs if spec["experiment"] == experiment]
        selected.extend(
            (index, len(population), spec)
            for index, spec in spread_sample(population, SAMPLE_COUNT)
        )

    bundles = replay.Bundles()
    rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    off_config = ModelConfig(strict_multitrip=False)
    on_config = ModelConfig(strict_multitrip=True)
    for selection_index, population_count, spec in selected:
        bundle = bundles.for_spec(spec)
        solution = solution_from_dict(spec["payload"]["solution"])
        regression: dict[str, Any]
        off_failure = ""
        try:
            with model_config_scope(off_config):
                if strict_multitrip_enabled():
                    raise RuntimeError("explicit multitrip-off configuration was not active")
                regression = replay.single_trip_regression(spec, solution, bundle)
            off_pass = bool(
                regression["objective_bitwise_equal"]
                and regression["components_bitwise_equal"]
                and not regression["mismatch_fields"]
                and int(regression["violation_count"]) == 0
            )
        except Exception as exc:
            off_failure = f"{type(exc).__name__}: {exc}"
            regression = {
                "objective_bitwise_equal": False,
                "components_bitwise_equal": False,
                "component_count": len(replay.REGRESSION_COMPONENTS),
                "mismatch_fields": ["exception"],
                "violation_count": "",
                "current_objective": "",
                "saved_objective": "",
            }
            off_pass = False

        with model_config_scope(on_config):
            if not strict_multitrip_enabled():
                raise RuntimeError("explicit multitrip-on configuration was not active")
            on_row, on_detail = replay.process(
                spec,
                bundles,
                regression_selected=False,
            )
        on_pass = bool(
            replay.bool_value(on_row["certificate_valid"])
            and replay.bool_value(on_row["interface_directly_usable"])
            and int(on_row["current_checker_violation_count"] or 0) == 0
            and int(on_row["depot_fleet_violation_count"] or 0) == 0
            and not str(on_row["failure"])
        )
        overall_pass = off_pass and on_pass
        row = {
            "record_id": replay.spec_record_id(spec),
            "experiment": spec["experiment"],
            "instance_id": spec["instance_id"],
            "seed": spec["seed"],
            "variant": spec["variant"],
            "source_path": replay.rel(spec["path"]),
            "source_sha256": replay.sha256(spec["path"]),
            "selection_index": selection_index,
            "population_count": population_count,
            "multitrip_off": False,
            "off_status": "PASS_BITWISE_IDENTICAL" if off_pass else "HALT_BITWISE_REPLAY_FAILED",
            "off_failure": off_failure,
            "off_objective_bitwise_equal": regression["objective_bitwise_equal"],
            "off_components_bitwise_equal": regression["components_bitwise_equal"],
            "off_component_count": regression["component_count"],
            "off_mismatch_fields": ";".join(regression["mismatch_fields"]),
            "off_violation_count": regression["violation_count"],
            "current_objective": regression["current_objective"],
            "saved_objective": regression["saved_objective"],
            "multitrip_on": True,
            "on_status": on_row["status"],
            "on_failure": on_row["failure"],
            "on_certificate_valid": on_row["certificate_valid"],
            "on_interface_directly_usable": on_row["interface_directly_usable"],
            "on_complete_checker_violation_count": on_row["current_checker_violation_count"],
            "on_depot_fleet_violation_count": on_row["depot_fleet_violation_count"],
            "original_route_count": on_row["original_route_count"],
            "packed_physical_vehicle_count": on_row["packed_physical_vehicle_count"],
            "saved_physical_vehicle_count": on_row["saved_physical_vehicle_count"],
            "prepared_solution_sha256": on_row["prepared_solution_sha256"],
            "certificate_record_sha256": on_row["certificate_record_sha256"],
            "overall_status": "PASS" if overall_pass else "HALT",
        }
        rows.append(row)
        details.append(
            {
                "selection_index": selection_index,
                "population_count": population_count,
                "model_config_off": off_config.as_metadata(),
                "single_trip_regression": regression,
                "model_config_on": on_config.as_metadata(),
                "multitrip_certificate_replay": on_detail,
                "overall_status": row["overall_status"],
            }
        )

    with (OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (OUT / "replay_details.jsonl").open("w", encoding="utf-8") as handle:
        for detail in details:
            handle.write(json.dumps(detail, ensure_ascii=False, sort_keys=True) + "\n")

    passed = sum(row["overall_status"] == "PASS" for row in rows)
    print(json.dumps({"rows": len(rows), "passed": passed, "failed": len(rows) - passed}))
    return 0 if passed == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
