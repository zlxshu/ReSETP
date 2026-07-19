"""Historical zero-search input builder for a cancelled donor03 gate.

The generated inputs are not private performance evidence.  The user later
restricted private performance to China81 only, so this builder must not be
run again or used to score an algorithm.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODEL_SCRIPTS = REPO / "models/scripts"
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    MODEL_SCRIPTS,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_e2_benchmark_instances import (  # noqa: E402
    _raw_inventory,
    _rotated_donors,
    build_full_source_threeshift,
)


OUTPUT = HERE / "fresh_segment_v2_bundles"
SCALES = (100, 150)
DONOR = "03"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(
            f"refusing to overwrite frozen bundles: {OUTPUT}"
        )
    OUTPUT.mkdir(parents=True)
    inventory = _raw_inventory()
    rows = []
    for scale in SCALES:
        keys = [
            f"E-UK{scale}_{donor_id}"
            for donor_id in _rotated_donors(DONOR)
        ]
        missing = [key for key in keys if key not in inventory]
        if missing:
            raise RuntimeError(
                f"pre-registered raw inputs do not exist: {missing}"
            )
        instance_id = f"DEV-seggen-v2-donor03-{scale}c"
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
                "actual_customers": int(
                    row.n_customers_actual
                ),
                "raw_input_files": [
                    str(inventory[key].path.relative_to(REPO))
                    for key in keys
                ],
                "raw_input_sha256": {
                    key: _sha(inventory[key].path)
                    for key in keys
                },
                "bundle_files": {
                    path.name: _sha(path)
                    for path in sorted(bundle.iterdir())
                    if path.is_file()
                    and not path.name.startswith("._")
                },
            }
        )
    manifest = {
        "schema_version": "result-blind-seg-gen-02-bundles.v1",
        "purpose": (
            "SEG-GEN-02 algorithm development only; "
            "not a formal benchmark"
        ),
        "selection_rule": (
            "unused donor03 source scales 100 and 150; "
            "75 was rejected before generation because no raw 75 source exists"
        ),
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
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
