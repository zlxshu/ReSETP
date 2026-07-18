#!/usr/bin/env python3
"""Freeze the result-blind donor-03 D1 bundles for the initial-pool gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODEL_SCRIPTS = REPO / "models/scripts"
for path in (MODEL_SCRIPTS, REPO / "models/src", REPO / "solver/src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_e2_benchmark_instances import (  # noqa: E402
    _raw_inventory,
    build_full_source_threeshift,
)


OUTPUT = HERE / "blind_d1_bundles"
DONOR = "03"
SOURCE_SCALES = (25, 50)
CONTRACT = REPO / "docs/handoff/unified_mechanism_alns_execution_contract_20260719.md"
GENERATOR = REPO / "models/scripts/build_e2_benchmark_instances.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite frozen D1 bundles: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    inventory = _raw_inventory()
    rows: list[dict[str, object]] = []
    for source_scale in SOURCE_SCALES:
        source_id = f"E-UK{source_scale}_{DONOR}"
        source = inventory[source_id]
        stage = OUTPUT / f".stage-src{source_scale}"
        build_row = build_full_source_threeshift(
            inventory,
            source_scale,
            DONOR,
            f"DEV-INIT-D1-DONOR{DONOR}-SRC{source_scale}",
            stage,
        )
        payload = json.loads((stage / "instance.json").read_text(encoding="utf-8"))
        nodes = list(payload["nodes"])
        actual_customers = sum(
            str(item.get("node_type", "")).lower() == "c"
            for item in nodes
        )
        actual_depots = sum(
            str(item.get("node_type", "")).lower() == "d"
            for item in nodes
        )
        instance_id = (
            f"DEV-INIT-D1-DONOR{DONOR}-SRC{source_scale}"
            f"-N{actual_customers}-DEP{actual_depots}"
        )
        final_dir = OUTPUT / instance_id
        stage.replace(final_dir)
        rows.append(
            {
                "instance_id": instance_id,
                "source_id": source_id,
                "source_scale": int(source_scale),
                "actual_customer_count": int(actual_customers),
                "actual_depot_count": int(actual_depots),
                "builder_reported_customer_count": int(build_row.n_customers_actual),
                "source_path_repo_relative": str(source.path.relative_to(REPO)),
                "source_sha256": sha256(source.path),
                "bundle_files": {
                    path.name: sha256(path)
                    for path in sorted(final_dir.iterdir())
                    if path.is_file() and not path.name.startswith("._")
                },
            }
        )

    manifest = {
        "schema_version": "resetp.unified-mechanism-alns.d1-dataset.v1",
        "purpose": "isolated_initial_pool_diagnosis_only_not_formal_benchmark",
        "selection_rule": (
            "donor 03 is the only not-previously-observed donor for the "
            "source-scale 25/50 mechanism-development pair after donor 02"
        ),
        "result_blind": True,
        "formal_l_main_activated": False,
        "stage2_activated": False,
        "donor": DONOR,
        "source_scales": list(SOURCE_SCALES),
        "generator_repo_relative": str(GENERATOR.relative_to(REPO)),
        "generator_sha256": sha256(GENERATOR),
        "contract_repo_relative": str(CONTRACT.relative_to(REPO)),
        "contract_sha256": sha256(CONTRACT),
        "instances": rows,
    }
    atomic_json(OUTPUT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
