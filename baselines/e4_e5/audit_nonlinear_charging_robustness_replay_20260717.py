#!/usr/bin/env python3
"""Independent structural and conservation audit for the nonlinear replay."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import csv
import hashlib
import json
import math


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/e4_e5/nonlinear_charging_robustness_replay_20260717"
CURVES = ("NL90_mild", "NL80_stress")
RULES = ("L->NL-F", "L->NL-E", "L->NL-C")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def keyed(row: dict[str, str], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(row[field] for field in fields)


def main() -> int:
    artifact_hashes = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))
    metadata = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    decision = json.loads((OUT / "decision.json").read_text(encoding="utf-8"))
    actions = read_csv("action_replay.csv")
    plans = read_csv("plan_replay.csv")
    raw_runs = read_csv("raw_runs.csv")
    pairs = read_csv("paired_by_seed_day.csv")

    action_fields = (
        "instance",
        "condition",
        "arm",
        "seed",
        "operating_day",
        "curve",
        "replay_rule",
        "vehicle_trip",
    )
    plan_fields = action_fields[:-1]
    pair_fields = plan_fields[:-1]
    nonnumeric = {
        "instance",
        "condition",
        "arm",
        "operating_day",
        "curve",
        "curve_role",
        "vehicle_trip",
        "station_id",
        "charge_scope",
        "replay_rule",
        "infeasibility_reason",
        "feasible",
        "above_constant_power_end",
    }
    action_rollup: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0])
    for row in actions:
        key = keyed(row, plan_fields)
        action_rollup[key][0] += 1
        action_rollup[key][1] += row["feasible"] == "False"

    checks: dict[str, bool] = {
        "artifact_hashes_match": all(
            (ROOT / relative).is_file() and sha256(ROOT / relative) == expected
            for relative, expected in artifact_hashes.items()
        ),
        "input_hashes_match": all(
            (ROOT / relative).is_file() and sha256(ROOT / relative) == expected
            for relative, expected in metadata["input_hashes"].items()
        ),
        "source_hashes_match": all(
            (ROOT / relative).is_file() and sha256(ROOT / relative) == expected
            for relative, expected in metadata["source_hashes"].items()
        ),
        "row_counts": (len(actions), len(plans), len(raw_runs), len(pairs))
        == (264_600, 18_144, 18_144, 6_048),
        "raw_runs_is_plan_replay": sha256(OUT / "raw_runs.csv")
        == sha256(OUT / "plan_replay.csv"),
        "action_keys_unique": len({keyed(row, action_fields) for row in actions})
        == len(actions),
        "plan_keys_unique": len({keyed(row, plan_fields) for row in plans}) == len(plans),
        "pair_keys_unique": len({keyed(row, pair_fields) for row in pairs}) == len(pairs),
        "action_matrix_balanced": Counter(
            (row["curve"], row["replay_rule"]) for row in actions
        )
        == Counter({(curve, rule): 44_100 for curve in CURVES for rule in RULES}),
        "plan_matrix_balanced": Counter(
            (row["curve"], row["replay_rule"]) for row in plans
        )
        == Counter({(curve, rule): 3_024 for curve in CURVES for rule in RULES}),
        "pair_matrix_balanced": Counter(row["curve"] for row in pairs)
        == Counter({curve: 3_024 for curve in CURVES}),
        "all_numeric_action_values_finite": all(
            math.isfinite(float(value))
            for row in actions
            for field, value in row.items()
            if value != "" and field not in nonnumeric
        ),
        "feasible_action_energy_closes": max(
            abs(float(row["energy_kwh"]) - float(row["slot_energy_sum_kwh"]))
            for row in actions
            if row["feasible"] == "True"
        )
        < 1e-8,
        "infeasible_outputs_are_blank": all(
            row["actual_emissions_kg"] == ""
            and row["forecast_emissions_kg"] == ""
            and row["slot_energy_sum_kwh"] == ""
            for row in actions
            if row["feasible"] == "False"
        ),
        "plan_action_rollup_matches": all(
            action_rollup[keyed(row, plan_fields)]
            == [int(row["action_count"]), int(row["infeasible_action_count"])]
            for row in plans
        ),
        "wide_capacity_is_nonbinding": all(
            int(row["exact_capacity_excess"]) == 0
            and int(row["half_hour_capacity_excess"]) == 0
            for row in plans
        ),
        "runner_mechanical_checks_pass": bool(decision["mechanical_pass"])
        and all(bool(value) for value in decision["mechanical_checks"].values()),
    }
    for curve, prefix in (("NL90_mild", "primary"), ("NL80_stress", "stress")):
        subset = [row for row in pairs if row["curve"] == curve]
        checks[f"{prefix}_infeasible_count_matches"] = sum(
            row["nonlinear_feasible"] == "False" for row in subset
        ) == int(decision[f"{prefix}_infeasible_seed_day_plans"])
        checks[f"{prefix}_direction_reversal_count_matches"] = sum(
            row["direction_reversal"] == "True" for row in subset
        ) == int(decision[f"{prefix}_direction_reversals"])

    passed = all(checks.values())
    verification: dict[str, Any] = {
        "verdict": (
            "PASS_INDEPENDENT_NL_CHARGING_REPLAY_AUDIT"
            if passed
            else "HALT_INDEPENDENT_NL_CHARGING_REPLAY_AUDIT"
        ),
        "checks": checks,
        "checked_rows": {
            "action_replay": len(actions),
            "plan_replay": len(plans),
            "raw_runs": len(raw_runs),
            "paired_by_seed_day": len(pairs),
        },
        "runner_verdict": decision["verdict"],
        "core_model_upgrade_required": decision["core_model_upgrade_required"],
        "audit_source_sha256": sha256(Path(__file__)),
    }
    (OUT / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(verification["verdict"])
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
