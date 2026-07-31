#!/usr/bin/env python3
"""Independent structural and numerical verification for E6 fairness v2."""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNNER_PATH = HERE / "run_e6_fairness_v3.py"


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_e6v2_verification_runner", RUNNER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("HALT_CHECKER_IMPORT_SPEC")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    runner = load_runner()
    if (HERE / "done.json").exists():
        raise RuntimeError(
            "HALT_DONE_EXISTS_BEFORE_INDEPENDENT_VERIFICATION"
        )
    environment = runner.preflight(1)
    e3_runner, e3, _ = runner.load_modules()
    raw_rows = read_csv(HERE / "raw_runs.csv")
    member_rows = read_csv(HERE / "member_ledger.csv")
    pool_summary = read_csv(HERE / "candidate_pool_summary.csv")
    instance_summary = read_csv(HERE / "instance_summary.csv")
    if (
        len(raw_rows) != 60
        or len(member_rows) != 120
        or len(pool_summary) != 20
        or len(instance_summary) != 2
    ):
        raise RuntimeError(
            "HALT_CHECKER_DENOMINATOR:"
            f"{len(raw_rows)}:{len(member_rows)}:"
            f"{len(pool_summary)}:{len(instance_summary)}"
        )
    raw_by_key = {
        (row["instance_id"], int(row["seed"]), row["state"]): row
        for row in raw_rows
    }
    if len(raw_by_key) != 60:
        raise RuntimeError("HALT_CHECKER_DUPLICATE_RAW_STATE_KEY")
    verification_rows: list[dict[str, Any]] = []
    candidate_count = 0
    event_count = 0
    fair_count_total = 0
    natural_total = 0
    fallback_total = 0
    for instance_id, sample_role in runner.INSTANCES:
        bundle = e3.load_bundle(instance_id)
        for seed in runner.SEEDS:
            status_path = runner.unit_status_path(instance_id, seed)
            pool_path = runner.candidate_pool_path(instance_id, seed)
            status = runner.read_json(status_path)
            pool = runner.read_json(pool_path)
            if status.get("status") != "PASS":
                raise RuntimeError(
                    f"HALT_CHECKER_UNIT_STATUS:{instance_id}:{seed}"
                )
            if status["candidate_pool_sha256"] != runner.sha256(
                pool_path
            ):
                raise RuntimeError(
                    f"HALT_CHECKER_POOL_FILE_HASH:{instance_id}:{seed}"
                )
            claimed_pool_id = pool.pop("candidate_pool_id")
            observed_pool_id = runner.canonical_sha256(pool)
            pool["candidate_pool_id"] = claimed_pool_id
            if claimed_pool_id != observed_pool_id:
                raise RuntimeError(
                    f"HALT_CHECKER_POOL_ID:{instance_id}:{seed}"
                )
            if not all(status["bitwise_comparisons"].values()):
                raise RuntimeError(
                    f"HALT_CHECKER_BITWISE:{instance_id}:{seed}"
                )
            events = list(pool["evaluation_events"])
            candidates = list(pool["candidates"])
            if len(events) != int(
                pool["full_evaluation_event_count"]
            ):
                raise RuntimeError(
                    f"HALT_CHECKER_EVENT_COUNT:{instance_id}:{seed}"
                )
            if len(candidates) != int(
                pool["unique_candidate_pool_size"]
            ):
                raise RuntimeError(
                    f"HALT_CHECKER_POOL_COUNT:{instance_id}:{seed}"
                )
            hashes = {
                row["solution_sha256"] for row in candidates
            }
            if len(hashes) != len(candidates):
                raise RuntimeError(
                    f"HALT_CHECKER_DUPLICATE_CANDIDATE:{instance_id}:{seed}"
                )
            if any(
                event["solution_sha256"] not in hashes
                for event in events
            ):
                raise RuntimeError(
                    f"HALT_CHECKER_EVENT_BODY_LINK:{instance_id}:{seed}"
                )
            if sorted(
                int(event["evaluation_index"]) for event in events
            ) != sorted(
                int(index)
                for candidate in candidates
                for index in candidate["evaluation_indices"]
            ):
                raise RuntimeError(
                    f"HALT_CHECKER_EVENT_INDEX_COVERAGE:"
                    f"{instance_id}:{seed}"
                )
            baseline_profit = {
                depot: float(value)
                for depot, value in pool[
                    "baseline_I_member_profit"
                ].items()
            }
            fair: list[dict[str, Any]] = []
            max_member_cost_error = 0.0
            for candidate in candidates:
                if runner.canonical_sha256(
                    candidate["solution"]
                ) != candidate["solution_sha256"]:
                    raise RuntimeError(
                        f"HALT_CHECKER_CANDIDATE_SOLUTION_HASH:"
                        f"{instance_id}:{seed}:"
                        f"{candidate['candidate_id']}"
                    )
                metrics = runner.state_metrics(
                    e3_runner,
                    e3,
                    bundle,
                    candidate["solution"],
                    baseline_profit,
                )
                if metrics["solution_sha256"] != candidate[
                    "solution_sha256"
                ]:
                    raise RuntimeError(
                        f"HALT_CHECKER_CANDIDATE_ROUNDTRIP:"
                        f"{instance_id}:{seed}:"
                        f"{candidate['candidate_id']}"
                    )
                objective_error = abs(
                    float(metrics["total_cost_cny"])
                    - float(candidate["complete_objective"])
                )
                max_member_cost_error = max(
                    max_member_cost_error, objective_error
                )
                if objective_error > 1.0e-8:
                    raise RuntimeError(
                        f"HALT_CHECKER_CANDIDATE_OBJECTIVE:"
                        f"{instance_id}:{seed}:"
                        f"{candidate['candidate_id']}:"
                        f"{objective_error}"
                    )
                for depot, profit in metrics["profits"].items():
                    stored = float(
                        candidate["member_profit"][depot]
                    )
                    if not math.isclose(
                        profit,
                        stored,
                        rel_tol=1.0e-12,
                        abs_tol=1.0e-9,
                    ):
                        raise RuntimeError(
                            f"HALT_CHECKER_MEMBER_PROFIT:"
                            f"{instance_id}:{seed}:"
                            f"{candidate['candidate_id']}:{depot}"
                        )
                if (
                    bool(metrics["all_members_no_worse_than_I"])
                    != bool(candidate["participation_satisfied"])
                ):
                    raise RuntimeError(
                        f"HALT_CHECKER_PARTICIPATION:"
                        f"{instance_id}:{seed}:"
                        f"{candidate['candidate_id']}"
                    )
                if candidate["participation_satisfied"]:
                    fair.append(candidate)
            if len(fair) != int(
                pool["participation_satisfying_candidate_count"]
            ):
                raise RuntimeError(
                    f"HALT_CHECKER_FAIR_COUNT:{instance_id}:{seed}"
                )
            selected = (
                min(
                    fair,
                    key=lambda row: (
                        float(row["complete_objective"]),
                        row["solution_sha256"],
                    ),
                )
                if fair
                else None
            )
            selected_id = (
                None if selected is None else selected["candidate_id"]
            )
            if selected_id != pool["selected_f_candidate_id"]:
                raise RuntimeError(
                    f"HALT_CHECKER_F_SELECTION:{instance_id}:{seed}"
                )
            fallback = selected is None
            if fallback != bool(pool["f_fallback_to_I"]):
                raise RuntimeError(
                    f"HALT_CHECKER_F_FALLBACK:{instance_id}:{seed}"
                )
            selected_path = (
                HERE
                / "formal/f_selected"
                / f"{runner.stem(instance_id, seed)}__F.json"
            )
            selected_payload = runner.read_json(selected_path)
            expected_hash = (
                pool["baseline_I_solution_sha256"]
                if fallback
                else selected["solution_sha256"]
            )
            if selected_payload["solution_sha256"] != expected_hash:
                raise RuntimeError(
                    f"HALT_CHECKER_SELECTED_F_HASH:"
                    f"{instance_id}:{seed}"
                )
            i_row = raw_by_key[(instance_id, seed, "I")]
            u_row = raw_by_key[(instance_id, seed, "U")]
            f_row = raw_by_key[(instance_id, seed, "F")]
            if u_row["all_members_no_worse_than_I"] == "True":
                natural_total += 1
            if fallback:
                fallback_total += 1
                if f_row["source_solution_sha256"] != i_row[
                    "source_solution_sha256"
                ]:
                    raise RuntimeError(
                        f"HALT_CHECKER_F_NOT_I:{instance_id}:{seed}"
                    )
            if f_row["all_members_no_worse_than_I"] != "True":
                raise RuntimeError(
                    f"HALT_CHECKER_F_PARTICIPATION:{instance_id}:{seed}"
                )
            candidate_count += len(candidates)
            event_count += len(events)
            fair_count_total += len(fair)
            verification_rows.append(
                {
                    "instance_id": instance_id,
                    "sample_role": sample_role,
                    "seed": seed,
                    "status": "PASS",
                    "bitwise_identical": True,
                    "full_evaluation_event_count": len(events),
                    "unique_candidate_pool_size": len(candidates),
                    "participation_satisfying_candidate_count": len(fair),
                    "selected_f_candidate_id": selected_id or "",
                    "f_fallback_to_I": fallback,
                    "max_member_cost_closure_abs_error":
                        max_member_cost_error,
                }
            )
            print(
                f"{runner.now_iso()} VERIFY PASS {instance_id} "
                f"seed={seed:02d} events={len(events)} "
                f"pool={len(candidates)} fair={len(fair)} "
                f"F={'I_FALLBACK' if fallback else selected_id}",
                flush=True,
            )
    decision = runner.read_json(HERE / "decision.json")
    if int(decision["units_naturally_pareto"]) != natural_total:
        raise RuntimeError("HALT_CHECKER_NATURAL_PARETO_COUNT")
    if int(decision["units_f_equals_i"]) != fallback_total:
        raise RuntimeError("HALT_CHECKER_FALLBACK_COUNT")
    if int(decision["candidate_full_evaluation_events"]) != event_count:
        raise RuntimeError("HALT_CHECKER_TOTAL_EVENT_COUNT")
    if int(decision["candidate_pool_unique_total"]) != candidate_count:
        raise RuntimeError("HALT_CHECKER_TOTAL_POOL_COUNT")
    if int(
        decision["participation_satisfying_candidates_total"]
    ) != fair_count_total:
        raise RuntimeError("HALT_CHECKER_TOTAL_FAIR_COUNT")
    runner.write_csv(
        HERE / "verification_rows.csv", verification_rows
    )
    verification = {
        "schema": "resetp.e6-fairness-v3.independent-verification.v1",
        "task_id": runner.TASK_ID,
        "created_at_utc": runner.now_iso(),
        "status": "PASS",
        "verified_units": 20,
        "joint_rerun_bitwise_identical_units": 20,
        "candidate_full_evaluation_events_verified": event_count,
        "candidate_unique_solutions_verified": candidate_count,
        "participation_satisfying_candidates_verified": fair_count_total,
        "units_naturally_pareto": natural_total,
        "units_f_equals_i": fallback_total,
        "raw_state_rows_verified": len(raw_rows),
        "member_rows_verified": len(member_rows),
        "protected_hashes": environment["protected_hashes"],
        "e3_manifest_failures": environment[
            "e3_verification"
        ]["e3_manifest_failures"],
        "verification_rows_sha256": runner.sha256(
            HERE / "verification_rows.csv"
        ),
    }
    verification["verification_id"] = runner.canonical_sha256(
        verification
    )
    runner.atomic_json(
        HERE / "independent_verification.json", verification
    )
    print(
        f"{runner.now_iso()} INDEPENDENT VERIFICATION PASS "
        f"units=20 events={event_count} pool={candidate_count} "
        f"fair={fair_count_total} natural={natural_total} "
        f"F_equals_I={fallback_total}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    for name, value in {
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
    }.items():
        os.environ.setdefault(name, value)
    raise SystemExit(main())
