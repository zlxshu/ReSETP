#!/usr/bin/env python3
"""Development-only diagnosis of representative-instance route diversity.

This script does not produce formal experiment evidence. It reruns one sealed
configuration in an isolated child process and records why route-pool
recombination does or does not improve the best complete single-view solution.
"""

from __future__ import annotations

import collections
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import traceback
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (
    REPO / "solver/src",
    PROTOTYPE,
    REPO / "baselines/e2_final_campaign_20260720",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

OUT = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "algorithm_repair_diagnostic_20260724"
)
RESULT = (
    OUT
    / "representative_seed1_route_diversity_after_archive_reuse.json"
)


def _route_set_key(completion: Any) -> tuple[Any, ...]:
    return tuple(
        sorted(
            (
                route.vehicle_type,
                route.home_depot_id,
                tuple(route.node_sequence),
            )
            for route in completion.solution.routes
        )
    )


def _worker(result_path: str) -> None:
    try:
        import run_corrected_china81_d6 as runner
        import route_pool_sp
        from setp_solver.china81 import load_china81_bundle

        bundle = load_china81_bundle(
            REPO,
            "cn-prd-50c-01-V2-LOCATIONS",
        )
        initial = runner._load_initial(
            "cn-prd-50c-01-V2-LOCATIONS"
        )
        run = route_pool_sp.run_hgs_route_pool_recombination(
            bundle,
            initial,
            seed=1,
            hgs_seconds_per_view=None,
            exact_elites_per_view=8,
            max_archive_candidates_per_view=24,
            sp_time_limit_seconds=5.0,
            hard_home_depot_lock=False,
            max_hgs_iterations_per_view=5_000,
            wallclock_safety_seconds_per_view=180.0,
        )
        records = route_pool_sp._route_pool_records(
            bundle,
            run.view_epochs,
            hard_home_depot_lock=False,
        )
        by_view = collections.Counter(
            record.source_view for record in records
        )
        views: dict[str, Any] = {}
        for mode, epoch in run.view_epochs.items():
            mode_records = [
                record
                for record in records
                if record.source_view == mode
            ]
            views[mode] = {
                "population_size": epoch.stats["population_size"],
                "unique_feasible_population_size": epoch.stats[
                    "unique_feasible_population_size"
                ],
                "unique_proxy_population_size": epoch.stats[
                    "unique_proxy_population_size"
                ],
                "archive_candidates_completed": epoch.stats[
                    "archive_candidates_completed"
                ],
                "selected_exact_objectives": epoch.stats[
                    "selected_exact_objectives"
                ],
                "hgs_iterations": epoch.stats["hgs_iterations"],
                "elite_count": len(epoch.elite_completions),
                "archive_completion_count": len(
                    epoch.archive_completions
                ),
                "unique_elite_solution_sets": len(
                    {
                        _route_set_key(completion)
                        for completion in epoch.elite_completions
                    }
                ),
                "unique_archive_solution_sets": len(
                    {
                        _route_set_key(completion)
                        for completion in epoch.archive_completions
                    }
                ),
                "unique_route_columns": len(
                    {
                        (
                            record.route.vehicle_type,
                            record.route.home_depot_id,
                            record.customers,
                        )
                        for record in mode_records
                    }
                ),
                "route_customer_count_distribution": dict(
                    sorted(
                        collections.Counter(
                            len(record.customers)
                            for record in mode_records
                        ).items()
                    )
                ),
            }
        payload = {
            "status": "PASS_DIAGNOSTIC",
            "formal_evidence": False,
            "instance_id": "cn-prd-50c-01-V2-LOCATIONS",
            "seed": 1,
            "selected_source": run.stats["selected_source"],
            "best_parent_objective": run.stats[
                "best_parent_objective"
            ],
            "final_objective": run.stats["final_objective"],
            "route_pool_size": run.stats["route_pool_size"],
            "route_records_by_first_source_view": dict(by_view),
            "views": views,
            "route_pool_solver": run.stats["route_pool_mip"],
        }
    except BaseException as exc:
        payload = {
            "status": "HALT_DIAGNOSTIC_EXCEPTION",
            "formal_evidence": False,
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    Path(result_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    context = mp.get_context("spawn")
    process = context.Process(target=_worker, args=(str(RESULT),))
    process.start()
    process.join(timeout=240)
    if process.is_alive():
        process.terminate()
        process.join()
        RESULT.write_text(
            json.dumps(
                {
                    "status": "HALT_DIAGNOSTIC_TIMEOUT",
                    "formal_evidence": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 2
    if not RESULT.is_file():
        RESULT.write_text(
            json.dumps(
                {
                    "status": "HALT_DIAGNOSTIC_CHILD_EXIT",
                    "formal_evidence": False,
                    "child_exit_code": process.exitcode,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 3
    print(RESULT.read_text(encoding="utf-8"))
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    return 0 if payload["status"] == "PASS_DIAGNOSTIC" else 1


if __name__ == "__main__":
    raise SystemExit(main())
