#!/usr/bin/env python3
"""Run the V7 S4 route-detail check with the sealed-task witness lookup fixed.

The S3 summary intentionally contains only costs and CPU time.  The witness
hash therefore has to be read from the selected seed's sealed task row, not
from the S3 summary row.  This wrapper changes only that lookup and then uses
the already registered zero-search S4 implementation.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
BASE_PATH = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "run_e2_staged_s4_route_detail.py"
)
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
PREREGISTRATION = CAMPAIGN / "s4_route_detail_preregistration_v3.json"
ABS_TOL = 1.0e-9


def load_base() -> Any:
    spec = importlib.util.spec_from_file_location(
        "resetp_v7_s4_route_detail_v2",
        BASE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load S4 base module: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def best_s3_witness_v3(module: Any, legacy: Any) -> tuple[Any, ...]:
    decision = json.loads(
        (module.S3 / "decision.json").read_text(encoding="utf-8")
    )
    if (
        decision.get("verdict")
        != "PASS_S3_STAGED_GENUINE_ITERATION_CURVES"
        or not bool(decision.get("trajectory_gate_pass"))
    ):
        raise RuntimeError("V7 S3 trajectory gate is not PASS")
    module.verify_manifest(module.S3)
    instance_id = str(decision["selected_instance_id"])
    rows = module.read_csv(module.S3 / "raw_runs.csv")
    if (
        len(rows) != 10
        or {int(row["seed"]) for row in rows} != set(range(1, 11))
        or any(row["status"] != "PASS" for row in rows)
        or any(row["instance_id"] != instance_id for row in rows)
    ):
        raise RuntimeError("V7 S3 matrix is not one case x seeds 1--10")
    selected = min(
        rows,
        key=lambda row: (
            float(row["MV-HGS-SP_cost"]),
            int(row["seed"]),
        ),
    )
    seed = int(selected["seed"])
    source_dir = module.task_dir(instance_id, seed)
    task_decision = json.loads(
        (source_dir / "decision.json").read_text(encoding="utf-8")
    )
    if (
        task_decision.get("verdict")
        != "PASS_D6_E2_STAGED_PORTFOLIO_TASK"
    ):
        raise RuntimeError(f"selected S4 task is not PASS: {source_dir}")
    module.verify_manifest(source_dir)
    task_rows = module.read_csv(source_dir / "raw_runs.csv")
    if len(task_rows) != 1:
        raise RuntimeError("selected sealed task must contain exactly one row")
    task_row = task_rows[0]
    if (
        task_row.get("status") != "PASS"
        or task_row.get("instance_id") != instance_id
        or int(task_row.get("seed", "-1")) != seed
        or not math.isclose(
            float(task_row["MV-HGS-SP_cost"]),
            float(selected["MV-HGS-SP_cost"]),
            rel_tol=0.0,
            abs_tol=ABS_TOL,
        )
    ):
        raise RuntimeError("S3 summary and selected sealed task disagree")
    witness = source_dir / "solution_witnesses.json"
    if module.sha256(witness) != task_row["witness_sha256"]:
        raise RuntimeError("selected witness hash differs from sealed task row")
    payload = json.loads(witness.read_text(encoding="utf-8"))
    return (
        instance_id,
        seed,
        float(selected["MV-HGS-SP_cost"]),
        witness,
        legacy.load_solution(payload["MV-HGS-SP"]),
    )


def refresh_v3_records(module: Any) -> None:
    metadata_path = module.OUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema"] = "resetp.e2-staged-v7-s4.metadata.v3"
    metadata["witness_hash_source"] = "selected sealed task raw_runs.csv"
    metadata["source_hashes"][
        str(Path(__file__).resolve().relative_to(REPO))
    ] = module.sha256(Path(__file__).resolve())
    module.write_json(metadata_path, metadata)
    report_path = module.OUT / "report.md"
    report_path.write_text(
        report_path.read_text(encoding="utf-8")
        + "\nThe v3 connector reads `witness_sha256` from the selected sealed "
        "task row because the S3 publication summary deliberately contains "
        "only cost and CPU columns. This is a zero-search lookup correction; "
        "the selected case, seed, witness, score and checking rules are "
        "unchanged.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(module.OUT)): module.sha256(path)
        for path in sorted(module.OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    module.write_json(
        module.OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )


def main() -> int:
    module = load_base()
    module.PREREGISTRATION = PREREGISTRATION
    module.best_s3_witness = lambda legacy: best_s3_witness_v3(
        module,
        legacy,
    )
    result = int(module.main())
    if result == 0:
        refresh_v3_records(module)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
