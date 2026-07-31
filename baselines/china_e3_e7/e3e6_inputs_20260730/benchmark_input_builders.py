#!/usr/bin/env python3
"""Wall-clock comparison for equivalent input-mapping constructors only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from time import perf_counter

import build_inputs as builder


CASES = (
    ("cn-cy-50c-01-V2-LOCATIONS", 25),
    ("cn-jjj-100c-01-V2-LOCATIONS", 50),
    ("cn-jjj-150c-01-V2-LOCATIONS", 25),
)


def normalize_legacy(
    mapping: dict[str, str] | None,
    audit: dict[str, object],
) -> tuple[str, dict[str, str] | None, object]:
    status = "PASS" if mapping is not None else "INFEASIBLE"
    routes = audit.get("route_groups_by_depot")
    return status, mapping, routes


def main() -> None:
    builder.verify_protected()
    builder.compile_cpp()
    runner = builder.load_runner()
    rows = []
    for instance_id, intensity in CASES:
        bundle = runner.e3.load_bundle(instance_id)
        original, _target, selected, _ineligible, failure = (
            builder.prepare_selection(runner, bundle, intensity)
        )
        if failure is not None:
            raise RuntimeError(
                f"benchmark selection unexpectedly failed: {failure}"
            )

        old_started = perf_counter()
        old_mapping, _old_rank, old_audit = (
            runner._legacy_dfs_lexicographic_global_assignment(
                bundle,
                original,
                selected,
            )
        )
        old_seconds = perf_counter() - old_started

        new_started = perf_counter()
        new_result = builder.fast_assignment(
            runner,
            bundle,
            intensity,
        )
        new_seconds = perf_counter() - new_started

        old_status, old_mapping, old_routes = normalize_legacy(
            old_mapping,
            old_audit,
        )
        new_status = new_result["status"]
        same = (
            old_status == new_status
            and old_mapping == new_result["mapping"]
            and old_routes == new_result["route_groups"]
        )
        if not same:
            raise RuntimeError(
                f"HALT_BENCHMARK_EQUIVALENCE:{instance_id}:{intensity}"
            )
        row = {
            "unit": builder.unit_name(instance_id, intensity),
            "old_python_dfs_seconds": old_seconds,
            "new_cpp_dfs_seconds": new_seconds,
            "speedup_old_over_new": old_seconds / new_seconds,
            "status": new_status,
            "core_fields_equal": True,
        }
        rows.append(row)
        print(
            f"BENCHMARK unit={row['unit']} "
            f"old={old_seconds:.6f}s new={new_seconds:.6f}s "
            f"speedup={row['speedup_old_over_new']:.3f}x",
            flush=True,
        )

    builder.atomic_json(
        builder.HERE / "benchmark.json",
        {
            "schema":
                "resetp.e3e6-input-builder-benchmark.v1",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "scope":
                "input mapping and frozen First-Fit feasibility only",
            "formal_effect_search_started": False,
            "objective_evaluations": 0,
            "cases": rows,
        },
    )
    builder.verify_protected()


if __name__ == "__main__":
    main()
