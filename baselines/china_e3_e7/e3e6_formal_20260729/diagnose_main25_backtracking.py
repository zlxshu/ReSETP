#!/usr/bin/env python3
"""Input-only diagnosis of the main 25% mismatch construction HALT."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_e3e6_formal.py"
SPEC = importlib.util.spec_from_file_location("_e3e6_diagnostic_runner", RUNNER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import E3/E6 runner")
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def selected_customers(bundle: Any, intensity: int) -> list[dict[str, Any]]:
    original = dict(bundle.customer_home_depot)
    target = round(len(original) * intensity / 100)
    allocations = m.e3.allocation_counts(original, target)
    selected: list[dict[str, Any]] = []
    for owner in sorted(allocations):
        candidates: list[dict[str, Any]] = []
        for customer_id, registered_owner in original.items():
            if registered_owner != owner:
                continue
            ranking = m._directed_depot_ranking(bundle, customer_id)
            if ranking[1] == owner:
                continue
            digest = hashlib.sha256(
                (
                    f"{m.TASK_ID}|{bundle.instance_id}|{intensity}|"
                    f"{owner}|{customer_id}"
                ).encode("utf-8")
            ).hexdigest()
            candidates.append(
                {
                    "customer_id": customer_id,
                    "owner": owner,
                    "ranking": ranking,
                    "rank_hash": digest,
                }
            )
        candidates.sort(key=lambda row: (row["rank_hash"], row["customer_id"]))
        selected.extend(candidates[: allocations[owner]])
    selected.sort(key=lambda row: (row["rank_hash"], row["customer_id"]))
    return selected


def greedy_trace(bundle: Any, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapping = dict(bundle.customer_home_depot)
    trace: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        attempts: list[dict[str, Any]] = []
        accepted = None
        for destination in item["ranking"][1:]:
            if destination == item["owner"]:
                continue
            trial = dict(mapping)
            trial[item["customer_id"]] = destination
            probe = m._fleet_probe(bundle, trial)
            attempts.append(
                {
                    "destination": destination,
                    "absolute_distance_rank": item["ranking"].index(destination) + 1,
                    "probe": probe,
                }
            )
            if probe["feasible"]:
                mapping = trial
                accepted = destination
                break
        trace.append(
            {
                "index": index,
                "customer_id": item["customer_id"],
                "owner": item["owner"],
                "ranking": item["ranking"],
                "accepted_destination": accepted,
                "attempts": attempts,
            }
        )
        if accepted is None:
            break
    return trace


def lexicographic_global_search(
    bundle: Any,
    selected: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, list[int] | None, dict[str, Any]]:
    mapping = dict(bundle.customer_home_depot)
    chosen: list[int] = []
    leaves = 0
    failed_prefix_counts: dict[str, int] = {}

    def visit(index: int) -> tuple[dict[str, str], list[int]] | None:
        nonlocal leaves
        if index == len(selected):
            leaves += 1
            probe = m._fleet_probe(bundle, mapping)
            if probe["feasible"]:
                return dict(mapping), list(chosen)
            return None
        item = selected[index]
        customer_id = item["customer_id"]
        old = mapping[customer_id]
        for absolute_rank, destination in enumerate(item["ranking"], start=1):
            if absolute_rank == 1 or destination == item["owner"]:
                continue
            mapping[customer_id] = destination
            chosen.append(absolute_rank)
            before = leaves
            found = visit(index + 1)
            branch_leaves = leaves - before
            if index >= 28:
                key = f"prefix_{index + 1:02d}_{customer_id}_rank_{absolute_rank}"
                failed_prefix_counts[key] = branch_leaves
            if found is not None:
                return found
            chosen.pop()
        mapping[customer_id] = old
        return None

    found = visit(0)
    return (
        (None, None, {"leaf_assignments_checked": leaves, "failed_tail_branch_leaf_counts": failed_prefix_counts})
        if found is None
        else (found[0], found[1], {"leaf_assignments_checked_before_first_feasible": leaves, "failed_tail_branch_leaf_counts": failed_prefix_counts})
    )


def main() -> int:
    intensity = 25
    bundle = m.e3.load_bundle(m.MAIN_INSTANCE)
    selected = selected_customers(bundle, intensity)
    trace = greedy_trace(bundle, selected)
    mapping, rank_vector, search_audit = lexicographic_global_search(bundle, selected)
    payload: dict[str, Any] = {
        "schema": "resetp.e3e6.input-backtracking-diagnostic.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": m.MAIN_INSTANCE,
        "mismatch_intensity_nominal_pct": intensity,
        "result_values_read": False,
        "fixed_customer_order_preserved": True,
        "distance_rankings_preserved": True,
        "d2a_caps_preserved": True,
        "reassignment_count_preserved": True,
        "selected_customer_count": len(selected),
        "ordered_selected_customers": [
            {
                "index": index,
                **item,
            }
            for index, item in enumerate(selected, start=1)
        ],
        "prefix_greedy": {
            "status": "HALT",
            "trace": trace,
            "halt_index": trace[-1]["index"],
            "halt_customer_id": trace[-1]["customer_id"],
        },
        "global_search": search_audit,
    }
    if mapping is None or rank_vector is None:
        payload["diagnosis"] = "GLOBAL_INFEASIBLE_UNDER_APPROVED_RULE"
        payload["status"] = "HALT"
    else:
        completed_bundle = m.e3.with_responsibility(bundle, mapping)
        solution, common_initial_audit = m.e3.build_common_initial(completed_bundle)
        final_probe = m._fleet_probe(bundle, mapping)
        changes = []
        for index, (item, absolute_rank) in enumerate(zip(selected, rank_vector), start=1):
            if absolute_rank > 2:
                changes.append(
                    {
                        "index": index,
                        "customer_id": item["customer_id"],
                        "owner": item["owner"],
                        "absolute_distance_rank": absolute_rank,
                        "destination": item["ranking"][absolute_rank - 1],
                    }
                )
        payload.update(
            {
                "diagnosis": "PREFIX_GREEDY_FALSE_HALT_GLOBAL_COMPLETION_EXISTS",
                "status": "PASS_IMPLEMENTATION_ERROR_CONFIRMED",
                "lexicographically_first_feasible_rank_vector": rank_vector,
                "fallbacks": changes,
                "final_fleet_probe": final_probe,
                "common_initial_audit": common_initial_audit,
                "responsibility_map_sha256": m.e3.canonical_sha256(mapping),
                "initial_solution_sha256": m.e3.canonical_sha256(m.e3.solution_payload(solution)),
            }
        )
        first_difference = next(
            (
                row
                for row in trace
                if row["accepted_destination"] is not None
                and mapping[row["customer_id"]] != row["accepted_destination"]
            ),
            None,
        )
        payload["first_prior_locally_accepted_choice_that_differs_from_global_completion"] = first_difference
    out = HERE / "diagnostics/main25_backtracking_certificate.json"
    m.e3.write_json(out, payload)
    print(json.dumps({
        "status": payload["status"],
        "diagnosis": payload["diagnosis"],
        "leaf_checks": next(iter([value for key, value in search_audit.items() if key.startswith("leaf_assignments_checked")]), None),
        "fallbacks": payload.get("fallbacks", []),
        "certificate": str(out),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if mapping is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
