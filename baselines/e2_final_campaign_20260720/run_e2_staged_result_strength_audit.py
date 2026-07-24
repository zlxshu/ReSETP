#!/usr/bin/env python3
"""Apply the frozen staged-portfolio E2 strength criteria without search."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scipy.stats import wilcoxon


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v7_small_archive_ledger_20260724",
)
CAMPAIGN_CONFIGS = {
    "corrected_china81_rerun_v5_staged_portfolio_20260724": {
        "formal_preregistration": "formal_preregistration_v2.json",
        "audit_preregistration": (
            "result_strength_audit_preregistration_v2.json"
        ),
        "formal_verdict": "PASS_D6_CORRECTED_CHINA81_E2_STAGED_RAW",
        "threshold_key": "paper_strength_acceptance",
        "require_v7_ledger": False,
    },
    "corrected_china81_rerun_v7_small_archive_ledger_20260724": {
        "formal_preregistration": "formal_preregistration_v4.json",
        "audit_preregistration": (
            "result_strength_audit_preregistration_v3.json"
        ),
        "formal_verdict": (
            "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_"
            "SMALL_ARCHIVE_LEDGER"
        ),
        "threshold_key": "paper_strength_acceptance_inherited_from_v6",
        "require_v7_ledger": True,
    },
}
if CAMPAIGN_NAME not in CAMPAIGN_CONFIGS:
    raise RuntimeError(f"unsupported staged campaign: {CAMPAIGN_NAME!r}")
CAMPAIGN_CONFIG = CAMPAIGN_CONFIGS[CAMPAIGN_NAME]
CAMPAIGN = (
    REPO / "baselines/e2_final_campaign_20260720" / CAMPAIGN_NAME
)
FULL = CAMPAIGN / "full_gate"
REPLAY = CAMPAIGN / "full_witness_replay"
FORMAL_PREREGISTRATION = (
    CAMPAIGN / str(CAMPAIGN_CONFIG["formal_preregistration"])
)
AUDIT_PREREGISTRATION = (
    CAMPAIGN / str(CAMPAIGN_CONFIG["audit_preregistration"])
)
OUT = CAMPAIGN / "result_strength_gate"
ARMS = ("HGS-F", "HGS-E", "HGS-M")
EPS = 1.0e-9


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
    payload = json.loads(
        (root / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    for relative, expected in payload["artifacts"].items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


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


def outcome(values: list[float]) -> dict[str, int]:
    wins = sum(value > EPS for value in values)
    losses = sum(value < -EPS for value in values)
    return {
        "paired_units": len(values),
        "wins": wins,
        "ties": len(values) - wins - losses,
        "losses": losses,
    }


def _validate_preregistrations() -> dict[str, Any]:
    formal = json.loads(
        FORMAL_PREREGISTRATION.read_text(encoding="utf-8")
    )
    audit = json.loads(
        AUDIT_PREREGISTRATION.read_text(encoding="utf-8")
    )
    if (
        formal.get("campaign_name") != CAMPAIGN_NAME
        or audit.get("campaign_name") != CAMPAIGN_NAME
        or audit.get("formal_preregistration_sha256")
        != sha256(FORMAL_PREREGISTRATION)
        or audit.get("operation")
        != "ZERO_SEARCH_RESULT_STRENGTH_AUDIT"
    ):
        raise RuntimeError("result-strength audit registration mismatch")
    for relative, expected in audit["source_hashes"].items():
        source = REPO / relative
        if not source.is_file() or sha256(source) != expected:
            raise RuntimeError(
                f"result-strength audit source drift: {relative}"
            )
    return formal


def main() -> int:
    formal = _validate_preregistrations()
    full_decision = json.loads(
        (FULL / "decision.json").read_text(encoding="utf-8")
    )
    replay_decision = json.loads(
        (REPLAY / "decision.json").read_text(encoding="utf-8")
    )
    if (
        full_decision.get("verdict")
        != CAMPAIGN_CONFIG["formal_verdict"]
        or replay_decision.get("verdict")
        != "PASS_D6_STAGED_FULL_WITNESS_REPLAY"
    ):
        raise RuntimeError("formal E2 or independent replay is not PASS")
    verify_manifest(FULL)
    verify_manifest(REPLAY)
    rows = read_csv(FULL / "raw_runs.csv")
    mechanical = formal["mechanical_acceptance"]
    integrity_checks = {
        "formal_task_count": len(rows)
        == int(mechanical["unique_completed_tasks"]),
        "unique_instance_seed_count": len(
            {(row["instance_id"], int(row["seed"])) for row in rows}
        )
        == 405,
        "all_formal_rows_pass": all(
            row["status"] == "PASS" for row in rows
        ),
        "all_complete_budgets_280": all(
            int(row["complete_candidate_attempts"]) == 280
            for row in rows
        ),
        "all_iterations_25000_per_view": all(
            int(row["total_iterations_per_view"]) == 25_000
            for row in rows
        ),
        "all_warm_types_preserved": all(
            row["warm_route_types_preserved"].lower() == "true"
            for row in rows
        ),
        "all_history_ledgers_complete": all(
            row["history_archive_ledger_complete"].lower() == "true"
            for row in rows
        ),
        "all_registered_budget_accounts_close": all(
            int(row["search_complete_candidate_attempts"])
            + int(row["budget_padding_rechecks"])
            == int(row["complete_candidate_attempts"])
            for row in rows
        ),
        "all_v7_archive_selections_complete": (
            not bool(CAMPAIGN_CONFIG["require_v7_ledger"])
            or all(
                row["historical_archive_selection_complete"].lower()
                == "true"
                and int(row["historical_selected_count"]) > 0
                for row in rows
            )
        ),
        "no_wallclock_safety_trigger": all(
            row["wallclock_safety_triggered"].lower() == "false"
            for row in rows
        ),
        "replay_solution_count": int(
            replay_decision.get("solution_count", -1)
        )
        == int(mechanical["independent_witness_replay_matches"]),
        "replay_costs": bool(
            replay_decision.get("all_costs_reproduced")
        ),
        "replay_emissions": bool(
            replay_decision.get("all_emissions_reproduced")
        ),
        "replay_feasibility": bool(
            replay_decision.get("all_full_model_feasible")
        ),
        "replay_date_slot": bool(
            replay_decision.get(
                "all_static_charging_within_registered_day"
            )
        ),
        "replay_predeparture": bool(
            replay_decision.get(
                "all_depot_charging_finishes_before_departure"
            )
        ),
        "replay_fleet": bool(
            replay_decision.get("all_depot_fleet_caps_respected")
        ),
    }
    if not all(integrity_checks.values()):
        raise RuntimeError("mechanical integrity failed before statistics")

    task_differences = {
        arm: [
            float(row[f"{arm}_cost"])
            - float(row["MV-HGS-SP_cost"])
            for row in rows
        ]
        for arm in ARMS
    }
    task_outcomes = {
        arm: outcome(values)
        for arm, values in task_differences.items()
    }
    by_instance: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_instance.setdefault(row["instance_id"], []).append(row)
    if len(by_instance) != 81 or any(
        len(items) != 5 for items in by_instance.values()
    ):
        raise RuntimeError("formal rows are not 81 five-seed instances")
    instance_means: dict[str, dict[str, Any]] = {}
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
        raw_p[arm] = (
            float(
                wilcoxon(
                    nonzero,
                    alternative="greater",
                    zero_method="wilcox",
                    method="auto",
                ).pvalue
            )
            if nonzero
            else 1.0
        )
    adjusted_p = holm_adjust(raw_p)
    instance_outcomes = {
        arm: {
            **outcome(values),
            "one_sided_wilcoxon_p_value": raw_p[arm],
            "holm_adjusted_p_value": adjusted_p[arm],
        }
        for arm, values in instance_differences.items()
    }

    layer_rows: list[dict[str, Any]] = []
    layer_differences: dict[str, list[float]] = {
        arm: [] for arm in ARMS
    }
    for region in ("jjj", "prd", "cy"):
        for tier in (10, 15, 20, 25, 50, 75, 100, 150, 200):
            items = [
                item
                for item in instance_means.values()
                if item["region"] == region and item["tier"] == tier
            ]
            if len(items) != 3:
                raise RuntimeError(
                    f"bad region-tier layer: {region}/{tier}"
                )
            for arm in ARMS:
                arm_mean = statistics.fmean(
                    float(item[arm]) for item in items
                )
                main_mean = statistics.fmean(
                    float(item["MV-HGS-SP"]) for item in items
                )
                difference = arm_mean - main_mean
                layer_differences[arm].append(difference)
                layer_rows.append(
                    {
                        "region": region,
                        "tier": tier,
                        "comparison": f"MV-HGS-SP_vs_{arm}",
                        "single_view_mean_cost": arm_mean,
                        "mv_hgs_sp_mean_cost": main_mean,
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
    layer_outcomes = {
        arm: outcome(values)
        for arm, values in layer_differences.items()
    }
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
    strict_stage_1_improvements = sum(
        float(row["improvement_over_protected_stage_1"]) > EPS
        for row in rows
    )
    route_fusion_improvements = sum(
        float(row["route_fusion_incremental_improvement"]) > EPS
        for row in rows
    )
    thresholds = formal[str(CAMPAIGN_CONFIG["threshold_key"])]
    checks: dict[str, bool] = {
        "stage_1_improvement_count": (
            strict_stage_1_improvements
            >= int(
                thresholds[
                    "minimum_tasks_strictly_improved_over_protected_stage_1"
                ]
            )
        )
    }
    for arm in ARMS:
        checks[f"{arm}:task_losses_zero"] = (
            task_outcomes[arm]["losses"] == 0
        )
        checks[f"{arm}:instance_losses_zero"] = (
            instance_outcomes[arm]["losses"]
            == int(
                thresholds[
                    "main_method_losses_against_each_single_view"
                ]
            )
        )
        checks[f"{arm}:instance_wins"] = (
            instance_outcomes[arm]["wins"]
            >= int(thresholds["minimum_strict_instance_mean_wins"][arm])
        )
        checks[f"{arm}:mean_reduction"] = (
            reductions[arm]
            >= float(
                thresholds[
                    "minimum_overall_mean_reduction_percent"
                ][arm]
            )
        )
        checks[f"{arm}:holm_p"] = (
            adjusted_p[arm]
            <= float(thresholds["maximum_holm_adjusted_p_value"])
        )
        checks[f"{arm}:all_27_layers_nonworse"] = (
            layer_outcomes[arm]["losses"] == 0
        )
    paper_strength_pass = all(checks.values())
    verdict = (
        "PASS_E2_STAGED_PORTFOLIO_PAPER_STRENGTH"
        if paper_strength_pass
        else "HOLD_E2_STAGED_PORTFOLIO_NOT_PAPER_STRONG"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    task_rows = [
        {
            "scope": "instance_seed_descriptive",
            "comparison": f"MV-HGS-SP_vs_{arm}",
            **task_outcomes[arm],
        }
        for arm in ARMS
    ]
    instance_rows = [
        {
            "scope": "instance_five_seed_mean_primary",
            "comparison": f"MV-HGS-SP_vs_{arm}",
            **instance_outcomes[arm],
        }
        for arm in ARMS
    ]
    write_csv(OUT / "task_pair_outcomes.csv", task_rows)
    write_csv(OUT / "instance_pair_outcomes.csv", instance_rows)
    write_csv(OUT / "layer_pair_outcomes.csv", layer_rows)
    summary = {
        "schema": "resetp.e2-staged-result-strength-summary.v1",
        "task_pair_outcomes": task_outcomes,
        "instance_pair_outcomes": instance_outcomes,
        "layer_pair_outcomes": layer_outcomes,
        "overall_mean_cost_reduction_percent": reductions,
        "strict_improvements_over_protected_stage_1": (
            strict_stage_1_improvements
        ),
        "strict_route_fusion_improvements_descriptive_only": (
            route_fusion_improvements
        ),
        "paper_strength_checks": checks,
    }
    write_json(OUT / "result_summary.json", summary)
    decision = {
        "schema": "resetp.e2-staged-result-strength-decision.v1",
        "verdict": verdict,
        "integrity_pass": True,
        "paper_strength_pass": paper_strength_pass,
        "integrity_checks": integrity_checks,
        "paper_strength_checks": checks,
        "formal_preregistration_sha256": sha256(
            FORMAL_PREREGISTRATION
        ),
        "audit_preregistration_sha256": sha256(
            AUDIT_PREREGISTRATION
        ),
        "formal_raw_sha256": sha256(FULL / "raw_runs.csv"),
        "independent_replay_decision_sha256": sha256(
            REPLAY / "decision.json"
        ),
        "route_fusion_superadditivity_claim_allowed": False,
        "formal_e3_search_allowed": False,
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e2-staged-result-strength-metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    FORMAL_PREREGISTRATION,
                    AUDIT_PREREGISTRATION,
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
        "# Staged-portfolio E2 result-strength audit\n\n"
        f"Decision: `{verdict}`.\n\n"
        "This zero-search audit applies only the thresholds frozen before "
        "formal completion. Route-fusion-only improvements are counted for "
        "description and never used to revive the rejected stable "
        "superadditivity claim. Any failed criterion keeps the formal data "
        "but blocks S3--S5, manuscript replacement and E3.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name not in {"artifact_hashes.json", "done.json"}
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
                "*.tmp"
            ],
            "artifacts": artifacts,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.e2-staged-strength-done.v1",
            "verdict": verdict,
            "decision_sha256": sha256(OUT / "decision.json"),
            "result_summary_sha256": sha256(
                OUT / "result_summary.json"
            ),
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if paper_strength_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
