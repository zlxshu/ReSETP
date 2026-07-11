"""Independent integrity checks for the frozen 280 kWh fleet audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


SOURCE = Path("baselines/e2_alns/e2_submission_20260711/carbon_280/raw_runs.csv")
ALGORITHM = "staged_hybrid_carbon_aware"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def close(left: float, right: float, tolerance: float = 1e-8) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output_dir.resolve()
    source = [row for row in read_csv(root / SOURCE) if row["algorithm"] == ALGORITHM]
    audit = read_csv(output / "raw_audit_rows.csv")
    decision = json.loads((output / "decision.json").read_text(encoding="utf-8"))
    existing_hashes = json.loads((output / "artifact_hashes.json").read_text(encoding="utf-8"))
    current_before_verification = hashes(output)
    hash_mismatches = sorted(
        key for key, expected in existing_hashes.items() if current_before_verification.get(key) != expected
    )
    source_keys = {(row["instance"], int(row["seed"])) for row in source}
    audit_keys = {(row["instance"], int(row["seed"])) for row in audit}
    eligible = [row for row in audit if int(row["size"]) != 15]
    checks = {
        "source_aware_rows_45": len(source) == 45,
        "audit_rows_45": len(audit) == 45,
        "source_and_audit_keys_match": source_keys == audit_keys,
        "all_pair_contracts_true": all(
            row[field] == "True"
            for row in audit
            for field in (
                "aware_zero_violation",
                "naive_zero_violation",
                "same_route_structure",
                "same_electricity_kwh",
                "same_charging_action_multiset",
            )
        ),
        "source_action_total_matches": sum(int(row["charging_action_count"]) for row in source if int(row["size"]) != 15)
        == sum(int(row["charging_action_count"]) for row in eligible)
        == int(decision["total_charging_actions"]),
        "shifted_action_total_matches": sum(int(row["shifted_action_count"]) for row in eligible)
        == int(decision["total_shifted_actions"]),
        "charging_energy_total_matches": close(
            sum(float(row["charging_energy_kwh"]) for row in eligible),
            float(decision["total_charging_energy_kwh"]),
        ),
        "shifted_energy_total_matches": close(
            sum(float(row["shifted_energy_kwh"]) for row in eligible),
            float(decision["total_shifted_energy_kwh"]),
        ),
        "public_charging_is_really_zero": sum(int(row["public_charging_action_count"]) for row in eligible) == 0
        and close(sum(float(row["public_charging_energy_kwh"]) for row in eligible), 0.0),
        "positive_carbon_saving_all_eligible_pairs": all(float(row["ev_carbon_saved_kg"]) > 0.0 for row in eligible),
        "artifact_hashes_match_before_verification": not hash_mismatches,
        "no_appledouble_artifacts": not any(path.name.startswith("._") for path in output.rglob("*")),
    }
    ok = all(checks.values())
    verification = {
        "verdict": "E2_280_FLEET_CHARGING_AUDIT_VERIFIED" if ok else "HALT_E2_280_FLEET_CHARGING_AUDIT_VERIFY",
        "all_checks_pass": ok,
        "checks": checks,
        "hash_mismatches_before_verification": hash_mismatches,
    }
    write_json(output / "verification.json", verification)
    write_json(output / "artifact_hashes.json", hashes(output))
    print(json.dumps(verification, ensure_ascii=False, sort_keys=True))
    if not ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
