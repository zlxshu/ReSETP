from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_l_main_instances import EXPECTED_MERGED_COUNTS, FORMAL_SOURCE_SCALES, MANIFEST_NAME
from setp_instance_lab.io import sha256_file
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution


REPO_ROOT = Path(__file__).resolve().parents[2]


def audit_l_main_v3(candidate_root: str | Path, output_root: str | Path) -> dict[str, Any]:
    candidate_root = Path(candidate_root)
    output_root = Path(output_root)
    manifest_path = candidate_root / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    expected = dict(zip(FORMAL_SOURCE_SCALES, EXPECTED_MERGED_COUNTS, strict=True))
    if manifest.get("schema_version") != "resetp-l-main-main-benchmark.v3":
        failures.append("schema_version")
    if manifest.get("source_scales") != list(FORMAL_SOURCE_SCALES):
        failures.append("source_scales")

    for entry in manifest.get("instances", []):
        result = _audit_instance(candidate_root, entry, expected)
        rows.append(result)
        failures.extend(result["failures"])
    if len(rows) != 9:
        failures.append(f"instance_count={len(rows)}")
    verdict = "LMAIN_V3_READY" if not failures else "HALT_LMAIN_V3_AUDIT"
    decision = {
        "schema_version": "resetp-l-main-v3-audit.v1",
        "verdict": verdict,
        "candidate_root": str(candidate_root),
        "manifest_sha256": sha256_file(manifest_path),
        "failure_count": len(failures),
        "failures": failures,
        "instances": rows,
    }
    _write_outputs(output_root, decision)
    return decision


def _audit_instance(candidate_root: Path, entry: dict[str, Any], expected: dict[int, int]) -> dict[str, Any]:
    instance_id = entry["instance_id"]
    bundle_dir = candidate_root / instance_id
    failures: list[str] = []
    scale = int(entry["source_scale"])
    if entry.get("merged_customer_count") != expected.get(scale):
        failures.append(f"{instance_id}:merged_count")
    for name, expected_hash in entry.get("bundle_file_hashes", {}).items():
        path = bundle_dir / name
        if not path.is_file() or sha256_file(path) != expected_hash:
            failures.append(f"{instance_id}:hash:{name}")
    three = json.loads((bundle_dir / "three_shift_manifest.json").read_text(encoding="utf-8"))
    children = three.get("source_children", [])
    if [item.get("input_customer_count") for item in children] != [scale, scale, scale]:
        failures.append(f"{instance_id}:full_sources")
    if any(item.get("deleted_customer_count") for item in children[:2]):
        failures.append(f"{instance_id}:nonthird_deletion")
    if children and int(children[2].get("kept_customer_count", 0)) < 1:
        failures.append(f"{instance_id}:third_shift_coverage")
    if any(float(item["shifted_due_time"]) <= 86400.0 for item in three.get("deleted_customers", [])):
        failures.append(f"{instance_id}:invalid_deletion_reason")
    instance = json.loads((bundle_dir / "instance.json").read_text(encoding="utf-8"))
    depots = [node for node in instance["nodes"] if node["node_type"] == "d"]
    if [node["node_id"] for node in depots] != ["D0", "D1"]:
        failures.append(f"{instance_id}:depots")
    with (bundle_dir / "carbon_profile.csv").open(encoding="utf-8", newline="") as handle:
        carbon = list(csv.DictReader(handle))
    starts = [int(item["horizon_second_start"]) for item in carbon]
    if starts != list(range(0, 86400, 1800)):
        failures.append(f"{instance_id}:carbon_slots")
    violations: list[Any] = []
    try:
        bundle = load_search_bundle(bundle_dir)
        solution = make_shared_initial_solution(bundle)
        violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
        if violations:
            failures.append(f"{instance_id}:initial_solution_violations={len(violations)}")
    except Exception as exc:
        failures.append(f"{instance_id}:initial_solution_exception={type(exc).__name__}:{exc}")
    return {
        "instance_id": instance_id,
        "source_scale": scale,
        "merged_customer_count": entry.get("merged_customer_count"),
        "carbon_slot_count": len(carbon),
        "initial_solution_violation_count": len(violations),
        "failures": failures,
    }


def _write_outputs(output_root: Path, decision: dict[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    metadata = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "candidate_root": decision["candidate_root"], "audit": "l-main-v3"}
    _write_json(output_root / "metadata.json", metadata)
    with (output_root / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance_id", "source_scale", "merged_customer_count", "carbon_slot_count", "initial_solution_violation_count", "failures"])
        writer.writeheader()
        for row in decision["instances"]:
            writer.writerow({**row, "failures": "; ".join(row["failures"])})
    _write_json(output_root / "decision.json", decision)
    report = f"# L-main v3 rebuild audit\n\nVerdict: `{decision['verdict']}`.\n\nFailures: {decision['failure_count']}.\n"
    (output_root / "report.md").write_text(report, encoding="utf-8")
    hashes = {path.name: sha256_file(path) for path in output_root.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}
    _write_json(output_root / "artifact_hashes.json", hashes)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a L-main v3 candidate without running E2.")
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    decision = audit_l_main_v3(args.candidate_root, args.output_root)
    print(json.dumps({"verdict": decision["verdict"], "output_root": args.output_root}, ensure_ascii=False))
    return 0 if decision["verdict"] == "LMAIN_V3_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
