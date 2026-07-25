#!/usr/bin/env python3
"""Run the single frozen six-instance performance falsification gate."""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from candidate_core import (
    candidate_trace_row,
    generate_pair_candidates,
    replace_pair_skeleton,
    select_route_pairs,
)
from common import (
    ENGINEERING,
    OUTPUT,
    artifact_hashes,
    load_bundle,
    load_registered_solutions,
    peak_rss_bytes,
    read_json,
    set_single_thread_environment,
    sha256,
    solution_payload,
    verify_registration,
    write_csv,
    write_json,
)
from pair_core import customers_in_route
from setp_solver.check import check_solution
from setp_solver.china81_completion import (
    complete_china81_route_skeleton,
    exact_china81_score,
)


def directed_adjacencies(solution: Any, bundle: Any) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for route in solution.routes:
        customers = customers_in_route(route, bundle)
        result.update(zip(customers, customers[1:]))
    return result


def exact_replay(solution: Any, bundle: Any, label: str) -> float:
    objective, _, violations = exact_china81_score(solution, bundle)
    direct = check_solution(solution, bundle.instance, bundle.prices)
    if violations or direct:
        raise RuntimeError(
            f"{label} infeasible: exact={len(violations)}, direct={len(direct)}"
        )
    return float(objective)


def run_one(spec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    set_single_thread_environment()
    started = time.perf_counter()
    bundle = load_bundle(spec["instance_id"])
    start, parents = load_registered_solutions(spec)
    start_objective = exact_replay(start, bundle, "start")
    if not math.isclose(
        start_objective,
        float(spec["start_expected_objective"]),
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("registered HGS-M start objective drift")
    parent_adjacencies = set().union(
        *(directed_adjacencies(parent, bundle) for parent in parents)
    )
    ranked, duals, columns = select_route_pairs(start, parents, bundle)
    total_states = 0
    evaluation_count = 0
    best_solution = start
    best_objective = start_objective
    best_trace: dict[str, Any] | None = None
    seen_structures: set[tuple[Any, ...]] = set()
    trace_rows: list[dict[str, Any]] = []
    for first, second, pressure in ranked:
        candidates, expanded = generate_pair_candidates(
            start,
            (first, second),
            bundle,
            k=int(config["k"]),
            top_per_direction=int(config["top_candidates_per_direction"]),
            state_limit=int(config["max_dp_states_per_instance"]) - total_states,
        )
        total_states += expanded
        for candidate in candidates:
            if (
                time.perf_counter() - started
                > float(config["instance_wallclock_safety_seconds"])
            ):
                raise TimeoutError("registered 90-second safety limit reached")
            structure = (candidate.first, candidate.second)
            if structure in seen_structures:
                continue
            seen_structures.add(structure)
            if evaluation_count >= int(
                config["max_complete_evaluations_per_instance"]
            ):
                break
            evaluation_count += 1
            row = {
                **candidate_trace_row((first, second), pressure, candidate),
                "evaluation_index": evaluation_count,
                "status": "INFEASIBLE_OR_ERROR",
                "objective": None,
                "strict_improvement": False,
                "error": "",
            }
            try:
                skeleton = replace_pair_skeleton(
                    start,
                    (first, second),
                    candidate,
                )
                completion = complete_china81_route_skeleton(skeleton, bundle)
                objective = exact_replay(
                    completion.solution,
                    bundle,
                    f"candidate {evaluation_count}",
                )
                if (
                    time.perf_counter() - started
                    > float(config["instance_wallclock_safety_seconds"])
                ):
                    raise TimeoutError(
                        "registered 90-second safety limit reached"
                    )
                if not math.isclose(
                    objective,
                    float(completion.objective),
                    rel_tol=0.0,
                    abs_tol=1.0e-9,
                ):
                    raise RuntimeError("completion/exact objective mismatch")
                strict = objective < start_objective - float(
                    config["strict_improvement_tolerance"]
                )
                row.update(
                    {
                        "status": "FEASIBLE",
                        "objective": objective,
                        "strict_improvement": strict,
                    }
                )
                if objective < best_objective - float(
                    config["strict_improvement_tolerance"]
                ):
                    best_solution = completion.solution
                    best_objective = objective
                    best_trace = dict(row)
            except (IndexError, KeyError, RuntimeError, TypeError, ValueError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            trace_rows.append(row)
    final_objective = exact_replay(best_solution, bundle, "output")
    if not math.isclose(
        final_objective,
        best_objective,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("selected output objective drift")
    strict_improvement = final_objective < start_objective - float(
        config["strict_improvement_tolerance"]
    )
    new_adjacencies = directed_adjacencies(best_solution, bundle) - parent_adjacencies
    accepted_outside_pool = bool(strict_improvement and new_adjacencies)
    improvement_pct = 100.0 * (start_objective - final_objective) / start_objective
    wall_seconds = time.perf_counter() - started
    trace_path = OUTPUT / "traces" / f"{spec['instance_id']}.json"
    witness_path = OUTPUT / "witnesses" / f"{spec['instance_id']}.json"
    write_json(trace_path, {"rows": trace_rows})
    write_json(
        witness_path,
        {
            "schema": "resetp.dual-guided-resource-order-witness.v1",
            "instance_id": spec["instance_id"],
            "start_seed": spec["start_seed"],
            "start_objective": start_objective,
            "output_objective": final_objective,
            "strict_improvement": strict_improvement,
            "accepted_trace": best_trace,
            "start": solution_payload(start),
            "output": solution_payload(best_solution),
        },
    )
    return {
        "instance_id": spec["instance_id"],
        "status": "OK",
        "start_seed": spec["start_seed"],
        "start_objective": start_objective,
        "output_objective": final_objective,
        "absolute_improvement": start_objective - final_objective,
        "relative_improvement_pct": improvement_pct,
        "strict_improvement": strict_improvement,
        "improvement_at_least_005_pct": improvement_pct >= 0.05 - 1.0e-12,
        "accepted_outside_v7_pool_adjacency": accepted_outside_pool,
        "new_adjacency_count": len(new_adjacencies),
        "material_order_and_membership_change": bool(
            not strict_improvement
            or (
                best_trace is not None
                and best_trace["first"]
                and best_trace["second"]
            )
        ),
        "complete_candidate_evaluations": evaluation_count,
        "dp_states": total_states,
        "route_pool_columns": len(columns),
        "lp_primal_residual": duals.primal_residual,
        "lp_stationarity_residual": duals.stationarity_residual,
        "positive_scarcity_resources": sum(
            resource.scarcity > 0.0 for resource in duals.resources
        ),
        "operator_wall_seconds": wall_seconds,
        "hgs_m_cpu_seconds": float(spec["start_hgs_m_cpu_seconds"]),
        "operator_hgs_cpu_fraction": (
            wall_seconds / float(spec["start_hgs_m_cpu_seconds"])
        ),
        "peak_rss_bytes": peak_rss_bytes(),
        "violation_count": 0,
        "trace_path": trace_path.relative_to(Path(__file__).resolve().parents[3]).as_posix(),
        "witness_path": witness_path.relative_to(Path(__file__).resolve().parents[3]).as_posix(),
        "error": "",
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"G0 output exists: {OUTPUT}")
    engineering = read_json(ENGINEERING / "decision.json")
    if (
        engineering["verdict"]
        != "PASS_ZERO_OBJECTIVE_ENGINEERING_AND_SIX_WORKER_RESOURCE_GATE"
    ):
        raise RuntimeError("engineering/resource gate did not pass")
    OUTPUT.mkdir(parents=True)
    registration = verify_registration()
    config = registration["config"]
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.dual-guided-resource-order-g0.v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "workers": int(config["workers"]),
            "registration_sha256": sha256(
                Path(__file__).resolve().parent / "g0_registration_v1.json"
            ),
            "engineering_decision_sha256": sha256(
                ENGINEERING / "decision.json"
            ),
            "config": config,
            "claim_boundary": registration["claim_boundary"],
        },
    )
    rows = []
    failures = []
    with ProcessPoolExecutor(max_workers=int(config["workers"])) as pool:
        futures = {
            pool.submit(run_one, spec, config): spec
            for spec in registration["inputs"]
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                message = f"{spec['instance_id']}: {type(exc).__name__}: {exc}"
                failures.append(message)
                rows.append(
                    {
                        "instance_id": spec["instance_id"],
                        "status": "ERROR",
                        "violation_count": 1,
                        "error": message,
                    }
                )
    rows.sort(key=lambda row: row["instance_id"])
    write_csv(OUTPUT / "raw_runs.csv", rows)
    write_json(
        OUTPUT / "decision_search.json",
        {
            "schema": "resetp.dual-guided-resource-order-search-terminal.v1",
            "status": "SEARCH_COMPLETE_PENDING_INDEPENDENT_REPLAY",
            "rows": len([row for row in rows if row["status"] == "OK"]),
            "failures": failures,
        },
    )
    (OUTPUT / "report_search.md").write_text(
        "# G0 search terminal\n\n"
        "The frozen six-task search is complete. Final PASS/STOP is withheld "
        "until the independent replay process finishes.\n",
        encoding="utf-8",
    )
    write_json(OUTPUT / "artifact_hashes_search.json", artifact_hashes(OUTPUT))
    print(json.dumps({"status": "SEARCH_COMPLETE_PENDING_REPLAY"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
