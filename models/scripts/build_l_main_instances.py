from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from build_e2_benchmark_instances import (
    DATA_ROOT,
    DONORS,
    SHIFT_SECONDS,
    _raw_inventory,
    build_full_source_threeshift,
)
from setp_instance_lab.io import sha256_file


FORMAL_SOURCE_SCALES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
EXPECTED_MERGED_COUNTS = (22, 34, 45, 55, 114, 163, 221, 322, 449)
ACTIVE_ROOT = DATA_ROOT / "generated_instances" / "L-main"
MANIFEST_NAME = "resetp-l-main-main-benchmark.v3.json"


def build_l_main_instances(output_root: str | Path, *, donor: str = "01", overwrite: bool = False) -> dict[str, Any]:
    output_root = Path(output_root).resolve()
    active_root = ACTIVE_ROOT.resolve()
    if donor != "01":
        raise ValueError("formal L-main v3 is locked to donor 01; -02/-03 remain diagnostic-only")
    if output_root == active_root:
        raise ValueError("refusing to write active L-main; build a candidate directory first")
    if active_root in output_root.parents or output_root in active_root.parents:
        raise ValueError("candidate output may not be the active L-main directory, its parent, or its child")
    if output_root.exists():
        existing_manifest = output_root / MANIFEST_NAME
        if not overwrite:
            raise FileExistsError(f"{output_root} already exists; pass --overwrite only for an existing v3 candidate")
        if not existing_manifest.is_file():
            raise ValueError("--overwrite is allowed only for a directory already identified by a v3 manifest")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=False)

    raw_index = _raw_inventory()
    rows = []
    for scale, expected in zip(FORMAL_SOURCE_SCALES, EXPECTED_MERGED_COUNTS, strict=True):
        instance_id = f"L-main-threeshift-{scale}c-{donor}"
        bundle_dir = output_root / instance_id
        row = build_full_source_threeshift(raw_index, scale, donor, instance_id, bundle_dir)
        if row.n_customers_actual != expected:
            raise RuntimeError(
                f"L-main v3 count mismatch for {instance_id}: expected {expected}, got {row.n_customers_actual}; activation is forbidden"
            )
        rows.append(_instance_record(bundle_dir, row, raw_index, scale, donor))

    manifest = {
        "schema_version": "resetp-l-main-main-benchmark.v3",
        "formal_default": True,
        "activation_requires_verdict": "LMAIN_V3_READY",
        "generator_commit": _git("rev-parse", "HEAD"),
        "generator_commit_short": _git("rev-parse", "--short", "HEAD"),
        "source_scales": list(FORMAL_SOURCE_SCALES),
        "expected_merged_customer_counts": list(EXPECTED_MERGED_COUNTS),
        "instances": rows,
    }
    _write_json(output_root / MANIFEST_NAME, manifest)
    return manifest


def _instance_record(bundle_dir: Path, row: Any, raw_index: dict[str, Any], scale: int, donor: str) -> dict[str, Any]:
    three_shift = json.loads((bundle_dir / "three_shift_manifest.json").read_text(encoding="utf-8"))
    instance = json.loads((bundle_dir / "instance.json").read_text(encoding="utf-8"))
    with (bundle_dir / "carbon_profile.csv").open(encoding="utf-8", newline="") as handle:
        carbon = list(csv.DictReader(handle))
    facilities = [node for node in instance["nodes"] if node["node_type"] in {"d", "f"}]
    depots = [node for node in facilities if node["node_type"] == "d"]
    source_ids = [item["source_base_id"] for item in three_shift["source_children"]]
    return {
        "instance_id": row.instance_id,
        "source_scale": scale,
        "merged_customer_count": row.n_customers_actual,
        "source_children": source_ids,
        "raw_source_hashes": {source_id: sha256_file(raw_index[source_id].path) for source_id in source_ids},
        "shift_seconds": list(SHIFT_SECONDS),
        "input_customer_counts": [item["input_customer_count"] for item in three_shift["source_children"]],
        "kept_customer_counts": [item["kept_customer_count"] for item in three_shift["source_children"]],
        "deleted_customer_counts": [item["deleted_customer_count"] for item in three_shift["source_children"]],
        "depot_ids": [node["node_id"] for node in depots],
        "depot_locations": {node["node_id"]: [node["x"], node["y"]] for node in depots},
        "station_count": sum(1 for node in facilities if node["node_type"] == "f"),
        "carbon_slot_count": len(carbon),
        "carbon_slot_starts": [int(item["horizon_second_start"]) for item in carbon],
        "anchor_source_fleet": {"num_cv": raw_index[f"E-UK{scale}_{donor}"].num_cv, "num_ev": raw_index[f"E-UK{scale}_{donor}"].num_ev},
        "bundle_file_hashes": {
            path.name: sha256_file(path)
            for path in sorted(bundle_dir.iterdir())
            if path.is_file()
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=Path(__file__).resolve().parents[2], text=True).strip()
    except Exception:
        return "UNKNOWN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the formal nine-instance L-main v3 candidate bundle.")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--donor", default="01", choices=DONORS)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_l_main_instances(args.output_root, donor=args.donor, overwrite=args.overwrite)
    print(json.dumps({"manifest": str(Path(args.output_root) / MANIFEST_NAME), "instances": len(manifest["instances"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
