"""Build two result-blind rich development bundles with the frozen generator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODEL_SCRIPTS = REPO / "models/scripts"
if str(MODEL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MODEL_SCRIPTS))

from build_e2_benchmark_instances import (  # noqa: E402
    _raw_inventory,
    build_full_source_threeshift,
)


OUTPUT = HERE / "fresh_donor02_mechanism_bundles"
SCALES = (25, 50)
DONOR = "02"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite frozen bundles: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    inventory = _raw_inventory()
    rows = []
    for scale in SCALES:
        instance_id = f"DEV-fullsource-donor02-{scale}c"
        bundle = OUTPUT / instance_id
        row = build_full_source_threeshift(
            inventory,
            scale,
            DONOR,
            instance_id,
            bundle,
        )
        rows.append(
            {
                "instance_id": instance_id,
                "source_scale": scale,
                "actual_customers": int(row.n_customers_actual),
                "bundle_files": {
                    path.name: _sha(path)
                    for path in sorted(bundle.iterdir())
                    if path.is_file() and not path.name.startswith("._")
                },
            }
        )
    manifest = {
        "schema_version": "result-blind-mechanism-dev-bundles.v1",
        "purpose": "algorithm_development_only_not_formal_benchmark",
        "selection_rule": "predeclared donor 02 and source scales 25,50",
        "generator": (
            "models/scripts/build_e2_benchmark_instances.py:"
            "build_full_source_threeshift"
        ),
        "generator_method_changed": False,
        "formal_l_main_activated": False,
        "donor": DONOR,
        "instances": rows,
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
