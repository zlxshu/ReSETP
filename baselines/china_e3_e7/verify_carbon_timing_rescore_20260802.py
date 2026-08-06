#!/usr/bin/env python3
"""Independent artifact-level verification and terminal marker for XD."""

from __future__ import annotations

from collections import defaultdict
import csv
from datetime import UTC, datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/china_e3_e7/carbon_timing_rescore_20260802"
EXPECTED_ROWS = 22_680 + 90
TOL = 1.0e-8


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def close(left: Any, right: Any) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=TOL)


def percent(treatment: float, control: float) -> float:
    return 100.0 * (treatment - control) / control


def pooled(
    rows: Sequence[Mapping[str, str]], control: str, treatment: str
) -> dict[str, float]:
    result: dict[str, float] = {}
    metrics = (
        "charging_emissions_kg",
        "system_emissions_kg",
        "charging_electricity_cost_cny",
        "operating_cost_cny",
        "total_cost_cny",
        "cost_fix_cny",
    )
    for generation in ("old", "new"):
        for metric in metrics:
            field = f"{generation}_{metric}"
            base = sum(
                float(row[field]) for row in rows if row["variant"] == control
            )
            target = sum(
                float(row[field])
                for row in rows
                if row["variant"] == treatment
            )
            name = metric.removesuffix("_cny").removesuffix("_kg")
            result[f"{generation}_{name}_change_pct"] = percent(target, base)
    return result


def paired_mean(
    rows: Sequence[Mapping[str, str]], control: str, treatment: str
) -> dict[str, float]:
    by_pair: dict[str, dict[str, Mapping[str, str]]] = defaultdict(dict)
    for row in rows:
        by_pair[row["pair_id"]][row["variant"]] = row
    result: dict[str, float] = {}
    metrics = (
        "charging_emissions_kg",
        "system_emissions_kg",
        "charging_electricity_cost_cny",
        "operating_cost_cny",
        "total_cost_cny",
        "cost_fix_cny",
    )
    for generation in ("old", "new"):
        for metric in metrics:
            field = f"{generation}_{metric}"
            effects = [
                percent(float(arms[treatment][field]), float(arms[control][field]))
                for arms in by_pair.values()
            ]
            name = metric.removesuffix("_cny").removesuffix("_kg")
            result[f"{generation}_{name}_change_pct"] = sum(effects) / len(
                effects
            )
    return result


def artifact_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path.name == "artifact_hashes.json":
            continue
        relative = path.relative_to(OUT)
        if (
            path.name.startswith("._")
            or "__pycache__" in relative.parts
            or any(part.startswith(".") for part in relative.parts)
        ):
            continue
        hashes[str(relative)] = sha256_path(path)
    return hashes


def main() -> int:
    forbidden_existing = [
        name
        for name in (
            "independent_verification.json",
            "done.json",
            "artifact_hashes.json",
        )
        if (OUT / name).exists()
    ]
    if forbidden_existing:
        raise RuntimeError(
            f"refusing to overwrite verification outputs: {forbidden_existing}"
        )
    required = (
        "pre_registration.json",
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "report.md",
        "summary.json",
        "solutions.jsonl.gz",
        "validation_ledger.jsonl",
    )
    failures = [name for name in required if not (OUT / name).is_file()]
    rows = read_rows(OUT / "raw_runs.csv") if not failures else []
    metadata = read_json(OUT / "metadata.json") if not failures else {}
    decision = read_json(OUT / "decision.json") if not failures else {}
    summary = read_json(OUT / "summary.json") if not failures else {}

    record_ids = [row["record_id"] for row in rows]
    if len(rows) != EXPECTED_ROWS:
        failures.append(f"raw_row_count:{len(rows)}!={EXPECTED_ROWS}")
    if len(set(record_ids)) != len(record_ids):
        failures.append("duplicate_record_id")
    fixed = [row for row in rows if row["population"] == "FIXED_ROUTE_TIMING"]
    joint = [row for row in rows if row["population"] == "JOINT_OPTIMIZATION"]
    if len(fixed) != 22_680:
        failures.append(f"fixed_solution_rows:{len(fixed)}!=22680")
    if len(joint) != 90:
        failures.append(f"joint_solution_rows:{len(joint)}!=90")
    if len({row["pair_id"] for row in fixed}) != 11_340:
        failures.append("fixed_pair_count")
    if len({row["pair_id"] for row in joint}) != 30:
        failures.append("joint_pair_count")

    solution_records: dict[str, tuple[int, str]] = {}
    if not failures:
        with gzip.open(OUT / "solutions.jsonl.gz", "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                payload = json.loads(line)
                solution_hash = canonical_sha256(payload["complete_solution"])
                if solution_hash != payload["solution_sha256"]:
                    failures.append(f"solution_payload_hash:{line_number}")
                solution_records[payload["record_id"]] = (
                    line_number,
                    solution_hash,
                )
        if len(solution_records) != EXPECTED_ROWS:
            failures.append(
                f"solution_record_count:{len(solution_records)}!={EXPECTED_ROWS}"
            )
        for row in rows:
            identity = solution_records.get(row["record_id"])
            if identity is None:
                failures.append(f"missing_solution:{row['record_id']}")
                continue
            if int(row["solution_line_number"]) != identity[0]:
                failures.append(f"solution_line:{row['record_id']}")
            if row["solution_sha256"] != identity[1]:
                failures.append(f"solution_sha:{row['record_id']}")

    if not failures:
        fixed_recomputed = pooled(fixed, "ASAP", "CARBON")
        fixed_saved = summary["fixed_route_comparison"]
        for key, value in fixed_recomputed.items():
            if not close(value, fixed_saved[key]):
                failures.append(f"fixed_summary:{key}")
        for label, treatment in (
            ("COST_PLUS_CARBON_vs_COST_ONLY", "COST_PLUS_CARBON"),
            ("PURE_CARBON_vs_COST_ONLY", "PURE_CARBON"),
        ):
            recomputed = paired_mean(joint, "COST_ONLY", treatment)
            saved = summary["joint_comparisons"][label]
            for key, value in recomputed.items():
                if not close(value, saved[key]):
                    failures.append(f"joint_summary:{label}:{key}")

    for relative, expected in metadata.get("protected_sha256_after", {}).items():
        path = ROOT / relative
        if not path.is_file() or sha256_path(path) != expected:
            failures.append(f"protected_hash:{relative}")
    for relative, expected in metadata.get("source_code_sha256", {}).items():
        path = ROOT / relative
        if not path.is_file() or sha256_path(path) != expected:
            failures.append(f"source_hash:{relative}")

    checks = {
        "required_artifacts_present": not any(
            failure.startswith(tuple(required)) for failure in failures
        ),
        "raw_row_count": len(rows) == EXPECTED_ROWS,
        "fixed_pair_count": len({row["pair_id"] for row in fixed}) == 11_340,
        "joint_pair_count": len({row["pair_id"] for row in joint}) == 30,
        "complete_solution_count": len(solution_records) == EXPECTED_ROWS,
        "unique_solution_record_ids": len(solution_records)
        == len(set(solution_records)),
        "summary_recomputed": not any(
            failure.startswith(("fixed_summary:", "joint_summary:"))
            for failure in failures
        ),
        "protected_hashes_match": not any(
            failure.startswith("protected_hash:") for failure in failures
        ),
        "source_hashes_match": not any(
            failure.startswith("source_hash:") for failure in failures
        ),
        "decision_population_counts_match": bool(decision)
        and int(decision.get("fixed_pair_count", -1)) == 11_340
        and int(decision.get("joint_pair_count", -1)) == 30,
    }
    if not all(checks.values()):
        for name, passed in checks.items():
            if not passed and name not in failures:
                failures.append(f"check:{name}")
    verification = {
        "schema": "resetp.xd-carbon-rescore-independent-verification.v1",
        "verified_at_utc": utc_now(),
        "status": (
            "PASS_INDEPENDENT_VERIFICATION"
            if not failures
            else "HALT_INDEPENDENT_VERIFICATION_FAILED"
        ),
        "checks": checks,
        "failures": failures,
        "raw_row_count": len(rows),
        "fixed_pair_count": len({row["pair_id"] for row in fixed}),
        "joint_pair_count": len({row["pair_id"] for row in joint}),
        "complete_solution_count": len(solution_records),
        "decision_status": decision.get("status"),
    }
    write_json(OUT / "independent_verification.json", verification)
    terminal_status = (
        decision.get("status")
        if not failures
        else "HALT_XD_INDEPENDENT_VERIFICATION_FAILED"
    )
    done = {
        "schema": "resetp.xd-carbon-rescore-done.v1",
        "task_id": "XD",
        "terminal_state_reached": True,
        "status": terminal_status,
        "completed_at_utc": utc_now(),
        "independent_verification_status": verification["status"],
        "route_search_executed": False,
        "search_evaluations": 0,
    }
    write_json(OUT / "done.json", done)
    hashes = artifact_hashes()
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.xd-carbon-rescore-artifact-hashes.v1",
            "generated_at_utc": utc_now(),
            "algorithm": "sha256",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                "hidden monitor runtime directories"
            ],
            "files": hashes,
        },
    )
    print(
        json.dumps(
            {
                "status": terminal_status,
                "verification": verification["status"],
                "artifact_count": len(hashes),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
