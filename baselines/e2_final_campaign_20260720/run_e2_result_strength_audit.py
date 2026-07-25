#!/usr/bin/env python3
"""Audit corrected E2 result strength against a result-blind preregistration."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scipy.stats import wilcoxon


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v4_20260724",
)
if (
    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", CAMPAIGN_NAME)
    or not CAMPAIGN_NAME.startswith("corrected_china81_rerun_")
):
    raise RuntimeError(
        f"invalid RESET_D6_CAMPAIGN_NAME: {CAMPAIGN_NAME!r}"
    )
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / CAMPAIGN_NAME
)
FULL = CAMPAIGN / "full_gate"
REPLAY = CAMPAIGN / "full_witness_replay"
PREREGISTRATION = (
    CAMPAIGN / "e2_result_release_preregistration_v1_20260724.json"
)
OUT = CAMPAIGN / "result_strength_gate"
ARMS = ("HGS-F", "HGS-E", "HGS-M")
EPS = 1.0e-9
SCALE_BANDS = {
    "S": {10, 15, 20},
    "M": {25, 50, 75},
    "L": {100, 150, 200},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def verify_manifest(root: Path) -> None:
    manifest_path = root / "artifact_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise RuntimeError(f"invalid artifact manifest: {manifest_path}")
    for relative, expected in artifacts.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


def band(tier: int) -> str:
    for label, tiers in SCALE_BANDS.items():
        if tier in tiers:
            return label
    raise ValueError(f"unknown tier: {tier}")


def outcome_rows(
    differences: dict[str, list[float]],
    *,
    scope: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for arm in ARMS:
        values = differences[arm]
        wins = sum(value > EPS for value in values)
        losses = sum(value < -EPS for value in values)
        rows.append(
            {
                "scope": scope,
                "comparison": f"MV-HGS-SP_vs_{arm}",
                "paired_units": len(values),
                "wins": wins,
                "ties": len(values) - wins - losses,
                "losses": losses,
            }
        )
    return rows


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=lambda arm: p_values[arm])
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for rank, arm in enumerate(ordered):
        candidate = min(1.0, (count - rank) * p_values[arm])
        running = max(running, candidate)
        adjusted[arm] = running
    return adjusted


def evaluate_gate(
    task_stats: dict[str, dict[str, Any]],
    instance_stats: dict[str, dict[str, Any]],
    layer_stats: dict[str, dict[str, Any]],
    reductions: dict[str, float],
    thresholds: dict[str, Any],
) -> dict[str, bool]:
    task_gate = thresholds["instance_seed_pairs"]
    instance_gate = thresholds["instance_five_seed_means"]
    layer_gate = thresholds["nine_region_scale_layers"]
    reduction_gate = thresholds["overall_mean_cost_reduction_percent"]
    checks: dict[str, bool] = {}
    for arm in ARMS:
        checks[f"{arm}:task_losses"] = (
            int(task_stats[arm]["losses"])
            <= int(task_gate["maximum_losses_vs_each_single_view"])
        )
        checks[f"{arm}:task_wins"] = (
            int(task_stats[arm]["wins"])
            >= int(task_gate["minimum_strict_wins"][arm])
        )
        checks[f"{arm}:instance_losses"] = (
            int(instance_stats[arm]["losses"])
            <= int(
                instance_gate[
                    "maximum_losses_vs_each_single_view"
                ]
            )
        )
        checks[f"{arm}:instance_wins"] = (
            int(instance_stats[arm]["wins"])
            >= int(instance_gate["minimum_strict_wins"][arm])
        )
        checks[f"{arm}:holm_p"] = (
            float(instance_stats[arm]["holm_adjusted_p_value"])
            <= float(
                instance_gate[
                    "maximum_holm_adjusted_one_sided_wilcoxon_p"
                ]
            )
        )
        checks[f"{arm}:mean_reduction"] = (
            float(reductions[arm])
            >= float(reduction_gate["minimum"][arm])
        )
        checks[f"{arm}:layer_losses"] = (
            int(layer_stats[arm]["losses"])
            <= int(
                layer_gate[
                    "maximum_adverse_layers_vs_each_single_view"
                ]
            )
        )
        checks[f"{arm}:layer_wins"] = (
            int(layer_stats[arm]["wins"])
            >= int(
                layer_gate["minimum_strictly_improved_layers"][arm]
            )
        )
    return checks


def main() -> int:
    if not PREREGISTRATION.is_file():
        raise RuntimeError("missing E2 result release preregistration")
    preregistration = json.loads(
        PREREGISTRATION.read_text(encoding="utf-8")
    )
    full_decision = json.loads(
        (FULL / "decision.json").read_text(encoding="utf-8")
    )
    replay_decision = json.loads(
        (REPLAY / "decision.json").read_text(encoding="utf-8")
    )
    if (
        full_decision.get("verdict")
        != "PASS_D6_CORRECTED_CHINA81_E2_RAW"
        or replay_decision.get("verdict")
        != "PASS_D6_CORRECTED_FULL_WITNESS_REPLAY"
    ):
        raise RuntimeError("corrected E2 or independent replay is not PASS")
    verify_manifest(FULL)
    verify_manifest(REPLAY)
    rows = read_csv(FULL / "raw_runs.csv")
    if len(rows) != 405:
        raise RuntimeError(f"expected 405 formal rows, found {len(rows)}")
    task_keys = {
        (row["instance_id"], int(row["seed"])) for row in rows
    }
    integrity = preregistration["hard_integrity_gates"]
    integrity_checks = {
        "formal_task_count": len(rows)
        == int(integrity["formal_task_count"]),
        "unique_instance_seed_count": len(task_keys) == 405,
        "all_formal_rows_pass": all(
            row["status"] == "PASS" for row in rows
        ),
        "all_complete_budgets_80": all(
            int(row["complete_candidate_attempts"])
            == int(
                integrity[
                    "complete_candidate_evaluation_attempts_per_task"
                ]
            )
            for row in rows
        ),
        "no_wallclock_safety_trigger": all(
            row["wallclock_safety_triggered"].lower() == "false"
            for row in rows
        ),
        "formal_day_identity": all(
            row["all_charging_on_registered_date"].lower() == "true"
            for row in rows
        ),
        "formal_predeparture_charging": all(
            row[
                "all_depot_charging_finishes_before_departure"
            ].lower()
            == "true"
            for row in rows
        ),
        "formal_depot_fleet_caps": all(
            row["all_depot_fleet_caps_respected"].lower() == "true"
            for row in rows
        ),
        "replay_solution_count": int(
            replay_decision.get("solution_count", -1)
        )
        == int(integrity["independent_replay_solution_count"]),
        "replay_costs": bool(
            replay_decision.get("all_costs_reproduced")
        ),
        "replay_emissions": bool(
            replay_decision.get("all_emissions_reproduced")
        ),
        "replay_feasibility": bool(
            replay_decision.get("all_full_model_feasible")
        ),
        "replay_city_date_slot": bool(
            replay_decision.get(
                "all_static_charging_within_registered_day"
            )
        ),
        "replay_predeparture_charging": bool(
            replay_decision.get(
                "all_depot_charging_finishes_before_departure"
            )
        ),
        "replay_depot_fleet_caps": bool(
            replay_decision.get(
                "all_depot_fleet_caps_respected"
            )
        ),
    }
    if not all(integrity_checks.values()):
        raise RuntimeError(
            "E2 integrity gate failed before result-strength analysis"
        )

    task_differences = {
        arm: [
            float(row[f"{arm}_cost"])
            - float(row["MV-HGS-SP_cost"])
            for row in rows
        ]
        for arm in ARMS
    }
    task_rows = outcome_rows(
        task_differences,
        scope="instance_seed_descriptive",
    )

    by_instance: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_instance.setdefault(row["instance_id"], []).append(row)
    if len(by_instance) != 81 or any(
        len(items) != 5 for items in by_instance.values()
    ):
        raise RuntimeError("formal rows do not form 81 five-seed instances")
    instance_means: dict[str, dict[str, float | str | int]] = {}
    for instance_id, items in by_instance.items():
        instance_means[instance_id] = {
            "region": items[0]["region"],
            "tier": int(items[0]["tier"]),
            **{
                arm: statistics.fmean(
                    float(item[f"{arm}_cost"]) for item in items
                )
                for arm in (*ARMS, "MV-HGS-SP")
            },
        }
    instance_differences = {
        arm: [
            float(item[arm]) - float(item["MV-HGS-SP"])
            for item in instance_means.values()
        ]
        for arm in ARMS
    }
    raw_p: dict[str, float] = {}
    for arm, values in instance_differences.items():
        nonzero = [value for value in values if abs(value) > EPS]
        if nonzero:
            raw_p[arm] = float(
                wilcoxon(
                    nonzero,
                    alternative="greater",
                    zero_method="wilcox",
                    method="auto",
                ).pvalue
            )
        else:
            raw_p[arm] = 1.0
    adjusted_p = holm_adjust(raw_p)
    instance_rows = outcome_rows(
        instance_differences,
        scope="instance_five_seed_mean_primary",
    )
    for row in instance_rows:
        arm = str(row["comparison"]).removeprefix("MV-HGS-SP_vs_")
        row["one_sided_wilcoxon_p_value"] = raw_p[arm]
        row["holm_adjusted_p_value"] = adjusted_p[arm]

    layer_rows: list[dict[str, Any]] = []
    layer_differences: dict[str, list[float]] = {
        arm: [] for arm in ARMS
    }
    for region in ("jjj", "prd", "cy"):
        for label in ("S", "M", "L"):
            items = [
                item
                for item in instance_means.values()
                if item["region"] == region
                and band(int(item["tier"])) == label
            ]
            if len(items) != 9:
                raise RuntimeError(
                    f"bad region-scale layer: {region}/{label}"
                )
            for arm in ARMS:
                arm_mean = statistics.fmean(
                    float(item[arm]) for item in items
                )
                mv_mean = statistics.fmean(
                    float(item["MV-HGS-SP"]) for item in items
                )
                difference = arm_mean - mv_mean
                layer_differences[arm].append(difference)
                layer_rows.append(
                    {
                        "region": region,
                        "scale_band": label,
                        "comparison": f"MV-HGS-SP_vs_{arm}",
                        "single_view_mean_cost": arm_mean,
                        "mv_hgs_sp_mean_cost": mv_mean,
                        "difference_cny": difference,
                        "outcome": (
                            "win"
                            if difference > EPS
                            else (
                                "loss"
                                if difference < -EPS
                                else "tie"
                            )
                        ),
                    }
                )
    layer_outcomes = outcome_rows(
        layer_differences,
        scope="nine_region_scale_layers",
    )
    reductions = {
        arm: 100.0
        * (
            statistics.fmean(
                float(row[f"{arm}_cost"]) for row in rows
            )
            - statistics.fmean(
                float(row["MV-HGS-SP_cost"]) for row in rows
            )
        )
        / statistics.fmean(
            float(row[f"{arm}_cost"]) for row in rows
        )
        for arm in ARMS
    }
    task_stats = {
        row["comparison"].removeprefix("MV-HGS-SP_vs_"): row
        for row in task_rows
    }
    instance_stats = {
        row["comparison"].removeprefix("MV-HGS-SP_vs_"): row
        for row in instance_rows
    }
    layer_stats = {
        row["comparison"].removeprefix("MV-HGS-SP_vs_"): row
        for row in layer_outcomes
    }
    strength_checks = evaluate_gate(
        task_stats,
        instance_stats,
        layer_stats,
        reductions,
        preregistration["paper_strength_gates"],
    )
    paper_strength_pass = all(strength_checks.values())
    verdict = (
        "PASS_E2_CORRECTED_PAPER_STRENGTH"
        if paper_strength_pass
        else "HOLD_E2_CORRECTED_RESULT_NOT_PAPER_STRONG"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "task_pair_outcomes.csv", task_rows)
    write_csv(OUT / "instance_pair_outcomes.csv", instance_rows)
    write_csv(OUT / "layer_pair_outcomes.csv", layer_rows)
    write_json(
        OUT / "result_summary.json",
        {
            "schema": "resetp.e2-result-strength-summary.v1",
            "task_pair_outcomes": task_stats,
            "instance_pair_outcomes": instance_stats,
            "layer_pair_outcomes": layer_stats,
            "overall_mean_cost_reduction_percent": reductions,
            "paper_strength_checks": strength_checks,
        },
    )
    decision = {
        "schema": "resetp.e2-result-strength-decision.v1",
        "verdict": verdict,
        "integrity_pass": True,
        "paper_strength_pass": paper_strength_pass,
        "integrity_checks": integrity_checks,
        "paper_strength_checks": strength_checks,
        "preregistration": str(PREREGISTRATION.relative_to(REPO)),
        "preregistration_sha256": sha256(PREREGISTRATION),
        "formal_raw_sha256": sha256(FULL / "raw_runs.csv"),
        "independent_replay_decision_sha256": sha256(
            REPLAY / "decision.json"
        ),
        "claim_boundary": preregistration["claim_boundary"],
        "formal_e3_search_allowed": False,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e2-result-strength-metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    PREREGISTRATION,
                    FULL / "raw_runs.csv",
                    FULL / "decision.json",
                    FULL / "artifact_hashes.json",
                    REPLAY / "raw_runs.csv",
                    REPLAY / "decision.json",
                    REPLAY / "artifact_hashes.json",
                    Path(__file__).resolve(),
                )
            },
        },
    )
    (OUT / "report.md").write_text(
        "# Corrected E2 result-strength audit\n\n"
        f"Decision: `{verdict}`.\n\n"
        "This zero-search audit applies the result-blind thresholds frozen "
        "before the root formal result files existed. All 405 formal tasks "
        "and all 1,620 independently replayed solutions passed the integrity "
        "gate. The paper-strength verdict is determined only by the frozen "
        "task, instance, layer, effect-size and Holm-adjusted significance "
        "thresholds; adverse outcomes are retained without rescue.\n",
        encoding="utf-8",
    )
    for path in OUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and path.name != "done.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "._*",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.e2-result-strength-completion.v1",
            "verdict": verdict,
            "decision_sha256": sha256(OUT / "decision.json"),
            "result_summary_sha256": sha256(
                OUT / "result_summary.json"
            ),
            "artifact_hashes_sha256": sha256(
                OUT / "artifact_hashes.json"
            ),
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if paper_strength_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
