#!/usr/bin/env python3
"""Independent no-search replay of the staged-portfolio formal witnesses."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v7_small_archive_ledger_20260724",
)
CAMPAIGN_CONFIGS = {
    "corrected_china81_rerun_v5_staged_portfolio_20260724": {
        "preregistration": "full_witness_replay_preregistration_v2.json",
        "formal_verdict": "PASS_D6_CORRECTED_CHINA81_E2_STAGED_RAW",
        "require_v7_ledger": False,
    },
    "corrected_china81_rerun_v7_small_archive_ledger_20260724": {
        "preregistration": "full_witness_replay_preregistration_v3.json",
        "formal_verdict": (
            "PASS_D6_CORRECTED_CHINA81_E2_STAGED_V7_"
            "SMALL_ARCHIVE_LEDGER"
        ),
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
OUT = CAMPAIGN / "full_witness_replay"
PREREGISTRATION = (
    CAMPAIGN / str(CAMPAIGN_CONFIG["preregistration"])
)
FORMAL_DIR = REPO / "baselines/china_e3_e7"
OLD_REPLAY_DIR = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_20260723"
)
for path in (
    REPO,
    REPO / "solver/src",
    FORMAL_DIR,
    OLD_REPLAY_DIR,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from formal_e3_runner import (  # noqa: E402
    _bundle_input_file_manifest,
    _require_depot_charge_before_departure,
    _require_depot_fleet_caps,
    _require_single_day_charging,
    _settlement_trace,
    payload_sha256,
)
from replay_corrected_d6_witnesses import (  # noqa: E402
    load_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import evaluate  # noqa: E402


ARMS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
EXPECTED_TASKS = 405
EXPECTED_SOLUTIONS = 1620
EXPECTED_COMPLETE_ATTEMPTS = 280
EXPECTED_ITERATIONS_PER_VIEW = 25_000


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
        raise ValueError("cannot write empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _validate_preregistration() -> dict[str, Any]:
    payload = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    if (
        payload.get("campaign_name") != CAMPAIGN_NAME
        or payload.get("operation")
        != "NO_SEARCH_INDEPENDENT_REPLAY_ONLY"
        or payload.get("expected_tasks") != EXPECTED_TASKS
        or payload.get("expected_solutions") != EXPECTED_SOLUTIONS
        or payload.get("search_evaluations") != 0
    ):
        raise RuntimeError("witness replay preregistration mismatch")
    for relative, expected in payload["source_hashes"].items():
        source = REPO / relative
        if not source.is_file() or sha256(source) != expected:
            raise RuntimeError(
                f"witness replay source drift: {relative}"
            )
    return payload


def _source_rows() -> list[dict[str, str]]:
    decision = json.loads(
        (FULL / "decision.json").read_text(encoding="utf-8")
    )
    if decision.get("verdict") != CAMPAIGN_CONFIG["formal_verdict"]:
        raise RuntimeError("staged formal full gate is not PASS")
    with (FULL / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != EXPECTED_TASKS:
        raise RuntimeError(
            f"expected {EXPECTED_TASKS} source rows, found {len(rows)}"
        )
    keys = [(row["instance_id"], int(row["seed"])) for row in rows]
    task_ids = [row["task_id"] for row in rows]
    if len(set(keys)) != EXPECTED_TASKS or len(set(task_ids)) != (
        EXPECTED_TASKS
    ):
        raise RuntimeError("duplicate formal task key")
    seeds_by_instance: dict[str, Counter[int]] = {}
    for instance_id, seed in keys:
        seeds_by_instance.setdefault(instance_id, Counter())[seed] += 1
    expected_seeds = Counter({1: 1, 2: 1, 3: 1, 4: 1, 5: 1})
    if (
        len(seeds_by_instance) != 81
        or any(counts != expected_seeds for counts in seeds_by_instance.values())
    ):
        raise RuntimeError("formal matrix is not 81 instances x seeds 1--5")
    def violates_frozen_ledger(row: dict[str, str]) -> bool:
        common_failure = (
            row["status"] != "PASS"
            or int(row["complete_candidate_attempts"])
            != EXPECTED_COMPLETE_ATTEMPTS
            or int(row["total_iterations_per_view"])
            != EXPECTED_ITERATIONS_PER_VIEW
            or row["wallclock_safety_triggered"].lower() == "true"
            or row["warm_route_types_preserved"].lower() != "true"
            or row["history_archive_ledger_complete"].lower() != "true"
        )
        if common_failure:
            return True
        if not bool(CAMPAIGN_CONFIG["require_v7_ledger"]):
            return False
        return (
            int(row["search_complete_candidate_attempts"])
            + int(row["budget_padding_rechecks"])
            != EXPECTED_COMPLETE_ATTEMPTS
            or row["historical_archive_selection_complete"].lower()
            != "true"
            or int(row["historical_selected_count"]) <= 0
        )

    if any(violates_frozen_ledger(row) for row in rows):
        raise RuntimeError("formal source ledger violates frozen invariants")
    return rows


def _task_dir(source: dict[str, str]) -> Path:
    return (
        FULL
        / "tasks"
        / (
            f"D6-E2-STAGED__{source['instance_id']}"
            f"__seed{source['seed']}"
        )
    )


def main() -> int:
    _validate_preregistration()
    source_rows = _source_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_dir = OUT / "input_manifests"
    manifest_hash_by_instance: dict[str, str] = {}
    bundle_by_instance: dict[str, Any] = {}
    output: list[dict[str, Any]] = []
    for task_index, source in enumerate(source_rows, start=1):
        instance_id = source["instance_id"]
        bundle = bundle_by_instance.get(instance_id)
        if bundle is None:
            bundle = load_china81_bundle(REPO, instance_id)
            bundle_by_instance[instance_id] = bundle
            manifest = _bundle_input_file_manifest(bundle)
            write_json(
                manifest_dir / f"{instance_id}.json",
                {
                    "schema": "resetp.china81-bundle-input-bytes.v1",
                    "instance_id": instance_id,
                    "source_paths": dict(bundle.source_paths),
                    "files": manifest,
                    "manifest_sha256": payload_sha256(manifest),
                },
            )
            manifest_hash_by_instance[instance_id] = payload_sha256(
                manifest
            )
        task_dir = _task_dir(source)
        witness_path = task_dir / "solution_witnesses.json"
        if sha256(witness_path) != source["witness_sha256"]:
            raise RuntimeError(f"witness hash mismatch: {task_dir.name}")
        witness = json.loads(witness_path.read_text(encoding="utf-8"))
        path_identity_hash = payload_sha256(dict(bundle.source_paths))
        if path_identity_hash != source["input_manifest_sha256"]:
            raise RuntimeError(
                f"input path identity mismatch: {task_dir.name}"
            )
        for arm in ARMS:
            solution = annotate_cross_site_services(
                load_solution(witness[arm]),
                bundle.customer_home_depot,
            )
            try:
                _require_depot_fleet_caps(solution, bundle)
                fleet_ok = True
            except RuntimeError:
                fleet_ok = False
            try:
                _require_single_day_charging(solution)
                day_ok = True
            except RuntimeError:
                day_ok = False
            try:
                _require_depot_charge_before_departure(
                    solution,
                    bundle,
                )
                departure_ok = True
            except RuntimeError:
                departure_ok = False
            direct_violations = check_solution(
                solution,
                bundle.instance,
                bundle.prices,
            )
            direct = evaluate(
                solution,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
            )
            objective, breakdown, exact_violations = exact_china81_score(
                solution,
                bundle,
            )
            recorded_cost = float(source[f"{arm}_cost"])
            recorded_emissions = float(
                source[f"{arm}_emissions_kg"]
            )
            cost_equal = (
                math.isclose(
                    objective,
                    recorded_cost,
                    rel_tol=0.0,
                    abs_tol=1.0e-9,
                )
                and math.isclose(
                    float(direct["total_cost"]),
                    recorded_cost,
                    rel_tol=0.0,
                    abs_tol=1.0e-9,
                )
            )
            emissions_equal = math.isclose(
                float(breakdown["E_total"]),
                recorded_emissions,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
            trace = _settlement_trace(solution, bundle)
            day_offsets = sorted(
                {
                    int(action.charge_day_offset)
                    for action in solution.charging_actions
                }
            )
            passed = bool(
                not direct_violations
                and not exact_violations
                and cost_equal
                and emissions_equal
                and fleet_ok
                and day_ok
                and departure_ok
                and all(value == 0 for value in day_offsets)
            )
            output.append(
                {
                    "task_id": source["task_id"],
                    "instance_id": instance_id,
                    "seed": int(source["seed"]),
                    "arm": arm,
                    "status": "PASS" if passed else "FAIL",
                    "recorded_cost": recorded_cost,
                    "replayed_cost": objective,
                    "cost_equal": cost_equal,
                    "recorded_emissions_kg": recorded_emissions,
                    "replayed_emissions_kg": float(
                        breakdown["E_total"]
                    ),
                    "emissions_equal": emissions_equal,
                    "direct_violation_count": len(direct_violations),
                    "exact_violation_count": len(exact_violations),
                    "all_charge_day_offsets_zero": all(
                        value == 0 for value in day_offsets
                    ),
                    "all_charging_within_registered_day": day_ok,
                    "all_depot_charging_finishes_before_departure": (
                        departure_ok
                    ),
                    "all_depot_fleet_caps_respected": fleet_ok,
                    "input_file_manifest_sha256": (
                        manifest_hash_by_instance[instance_id]
                    ),
                    "path_identity_sha256": path_identity_hash,
                    "settlement_trace_sha256": payload_sha256(trace),
                }
            )
        if task_index % 25 == 0:
            print(
                f"[D6-STAGED-REPLAY] {task_index}/405 tasks replayed",
                flush=True,
            )
    write_csv(OUT / "raw_runs.csv", output)
    passed = bool(
        len(output) == EXPECTED_SOLUTIONS
        and len(
            {(row["task_id"], row["arm"]) for row in output}
        )
        == EXPECTED_SOLUTIONS
        and len(manifest_hash_by_instance) == 81
        and all(row["status"] == "PASS" for row in output)
    )
    decision = {
        "schema": (
            "resetp.d6-e2-staged-full-witness-replay.decision.v1"
        ),
        "verdict": (
            "PASS_D6_STAGED_FULL_WITNESS_REPLAY"
            if passed
            else "HALT_D6_STAGED_FULL_WITNESS_REPLAY"
        ),
        "search_executions": 0,
        "task_count": EXPECTED_TASKS,
        "solution_count": len(output),
        "unique_task_arm_count": len(
            {(row["task_id"], row["arm"]) for row in output}
        ),
        "instance_input_manifest_count": len(
            manifest_hash_by_instance
        ),
        "all_costs_reproduced": all(
            row["cost_equal"] for row in output
        ),
        "all_emissions_reproduced": all(
            row["emissions_equal"] for row in output
        ),
        "all_full_model_feasible": all(
            int(row["direct_violation_count"]) == 0
            and int(row["exact_violation_count"]) == 0
            for row in output
        ),
        "all_static_charge_day_offsets_zero": all(
            row["all_charge_day_offsets_zero"] for row in output
        ),
        "all_static_charging_within_registered_day": all(
            row["all_charging_within_registered_day"]
            for row in output
        ),
        "all_depot_charging_finishes_before_departure": all(
            row["all_depot_charging_finishes_before_departure"]
            for row in output
        ),
        "all_depot_fleet_caps_respected": all(
            row["all_depot_fleet_caps_respected"]
            for row in output
        ),
        "joint_settlement_policy": (
            "diesel by route-origin city; electricity and carbon by charging "
            "node city, 2025-02-12 and half-hour slot; fail closed"
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": (
                "resetp.d6-e2-staged-full-witness-replay.metadata.v1"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "campaign_name": CAMPAIGN_NAME,
            "preregistration_sha256": sha256(PREREGISTRATION),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    FULL / "raw_runs.csv",
                    FULL / "decision.json",
                    PREREGISTRATION,
                    FORMAL_DIR / "release_v6_config.py",
                    FORMAL_DIR / "formal_e3_runner.py",
                    REPO / "solver/src/setp_solver/china81.py",
                    REPO
                    / "solver/src/setp_solver/"
                    "china81_completion.py",
                    REPO / "solver/src/setp_solver/cost.py",
                    REPO / "solver/src/setp_solver/check.py",
                    REPO / "solver/src/setp_solver/prices.py",
                    REPO / "solver/src/setp_solver/solution.py",
                    REPO
                    / "solver/src/setp_solver/"
                    "instance_loader.py",
                    REPO / "solver/src/setp_solver/charging_curve.py",
                    Path(__file__).resolve(),
                )
            },
        },
    )
    (OUT / "report.md").write_text(
        "# Staged-portfolio full witness replay\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "All 1,620 saved solutions were loaded independently and checked "
        "without search against the current corrected input bytes. Costs, "
        "emissions, feasibility, date/slot settlement, depot charging order "
        "and finite-fleet limits were replayed from the saved witnesses.\n",
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
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.d6-e2-staged-replay-done.v1",
            "verdict": decision["verdict"],
            "solution_count": len(output),
            "raw_runs_sha256": sha256(OUT / "raw_runs.csv"),
            "decision_sha256": sha256(OUT / "decision.json"),
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
