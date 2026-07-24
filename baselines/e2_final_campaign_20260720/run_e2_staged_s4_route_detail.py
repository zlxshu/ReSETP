#!/usr/bin/env python3
"""Build the V7 route-detail witness without search or result repair."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v7_small_archive_ledger_20260724",
)
EXPECTED_CAMPAIGN = (
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
if CAMPAIGN_NAME != EXPECTED_CAMPAIGN:
    raise RuntimeError(f"unsupported S4 campaign: {CAMPAIGN_NAME!r}")
CAMPAIGN = (
    REPO / "baselines/e2_final_campaign_20260720" / CAMPAIGN_NAME
)
FULL = CAMPAIGN / "full_gate"
S3 = CAMPAIGN / "s3_trajectory_gate"
OUT = CAMPAIGN / "table4_gate"
PREREGISTRATION = CAMPAIGN / "s4_route_detail_preregistration_v2.json"
LEGACY_PATH = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_20260723/run_corrected_s4.py"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def verify_manifest(root: Path) -> None:
    payload = json.loads(
        (root / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    for relative, expected in payload["artifacts"].items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


def validate_preregistration() -> dict[str, Any]:
    payload = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    if (
        payload.get("campaign_name") != CAMPAIGN_NAME
        or payload.get("operation") != "ZERO_SEARCH_ROUTE_DETAIL_RECHECK"
        or payload.get("search_evaluations") != 0
    ):
        raise RuntimeError("S4 preregistration mismatch")
    for relative, expected in payload["source_hashes"].items():
        source = REPO / relative
        if not source.is_file() or sha256(source) != expected:
            raise RuntimeError(f"S4 source drift: {relative}")
    return payload


def load_legacy() -> Any:
    spec = importlib.util.spec_from_file_location(
        "resetp_v7_s4_legacy",
        LEGACY_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load S4 implementation: {LEGACY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def task_dir(instance_id: str, seed: int) -> Path:
    task_id = f"D6-E2-STAGED__{instance_id}__seed{seed}"
    if seed <= 5:
        return FULL / "tasks" / task_id
    return S3 / "extra_seed_tasks" / "tasks" / task_id


def best_s3_witness(legacy: Any) -> tuple[str, int, float, Path, Any]:
    decision = json.loads(
        (S3 / "decision.json").read_text(encoding="utf-8")
    )
    if (
        decision.get("verdict")
        != "PASS_S3_STAGED_GENUINE_ITERATION_CURVES"
        or not bool(decision.get("trajectory_gate_pass"))
    ):
        raise RuntimeError("V7 S3 trajectory gate is not PASS")
    verify_manifest(S3)
    instance_id = str(decision["selected_instance_id"])
    rows = read_csv(S3 / "raw_runs.csv")
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
    source_dir = task_dir(instance_id, seed)
    task_decision = json.loads(
        (source_dir / "decision.json").read_text(encoding="utf-8")
    )
    if (
        task_decision.get("verdict")
        != "PASS_D6_E2_STAGED_PORTFOLIO_TASK"
    ):
        raise RuntimeError(f"selected S4 task is not PASS: {source_dir}")
    verify_manifest(source_dir)
    witness = source_dir / "solution_witnesses.json"
    if sha256(witness) != selected["witness_sha256"]:
        raise RuntimeError("selected S4 witness hash differs from S3 row")
    payload = json.loads(witness.read_text(encoding="utf-8"))
    return (
        instance_id,
        seed,
        float(selected["MV-HGS-SP_cost"]),
        witness,
        legacy.load_solution(payload["MV-HGS-SP"]),
    )


def rewrite_root_records(legacy: Any) -> None:
    decision = json.loads(
        (OUT / "decision.json").read_text(encoding="utf-8")
    )
    metadata_path = OUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema"] = "resetp.e2-staged-v7-s4.metadata.v1"
    metadata["campaign_name"] = CAMPAIGN_NAME
    metadata["preregistration_sha256"] = sha256(PREREGISTRATION)
    metadata["source_hashes"].update(
        {
            str(Path(__file__).resolve().relative_to(REPO)): sha256(
                Path(__file__).resolve()
            ),
            str(PREREGISTRATION.relative_to(REPO)): sha256(
                PREREGISTRATION
            ),
            str(LEGACY_PATH.relative_to(REPO)): sha256(LEGACY_PATH),
        }
    )
    legacy.write_json(metadata_path, metadata)
    (OUT / "report.md").write_text(
        "# V7 S4 route-detail recheck\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        f"Iteration-display case `{decision['case_instance_id']}`, "
        f"best sealed MV-HGS-SP seed {decision['best_seed']}. The saved "
        "complete solution was rechecked by the global checker and exact "
        "scorer; customer coverage was checked only on that complete "
        "solution. Per-route distance, cost, time, energy, emissions and "
        "service totals were recomputed arithmetically and required to "
        "close to the complete-solution totals. No search, rescue, fragment "
        "coverage check or result replacement was performed.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    legacy.write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )


def main() -> int:
    validate_preregistration()
    legacy = load_legacy()
    legacy.CAMPAIGN_NAME = CAMPAIGN_NAME
    legacy.CAMPAIGN = CAMPAIGN
    legacy.S3 = S3
    legacy.OUT = OUT
    legacy.S4_CASE_ROLE = "iteration_display"
    legacy.best_s3_witness = lambda: best_s3_witness(legacy)
    result = int(legacy.main())
    if result == 0:
        rewrite_root_records(legacy)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
