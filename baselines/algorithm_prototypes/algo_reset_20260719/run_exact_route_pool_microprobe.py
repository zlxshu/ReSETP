#!/usr/bin/env python3
"""Budget 0/1/2/5 functionality probe for exact multi-source route recombination."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path

from exact_route_pool_recombiner import PoolRoute, exact_recombine
from setp_solver.solution import Route


OUT = Path(__file__).resolve().parent / "exact_route_pool_microprobe"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, payload: object) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def record(customers: str, score: float, source: str) -> PoolRoute:
    return PoolRoute(
        route=Route(
            vehicle_id=f"{source}-{customers}",
            vehicle_type="cv",
            home_depot_id="D0",
            node_sequence=["D0", *customers, "D0"],
        ),
        customers=frozenset(customers),
        additive_score=score,
        source=source,
    )


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refuse to overwrite non-empty output: {OUT}")
    parents = [
        [
            record("AB", 10.0, "HGS"),
            record("C", 20.0, "HGS"),
            record("D", 20.0, "HGS"),
        ],
        [
            record("A", 20.0, "ALNS"),
            record("B", 20.0, "ALNS"),
            record("CD", 10.0, "ALNS"),
        ],
    ]
    rows = []
    for budget in (0, 1, 2, 5):
        available = min(budget, len(parents))
        records = [
            route
            for parent in parents[:available]
            for route in parent
        ]
        result = (
            exact_recombine(records, "ABCD", time_limit_seconds=0.1)
            if budget > 0
            else None
        )
        covered = (
            sorted(
                customer
                for route in result.solution.routes
                for customer in route.node_sequence
                if customer != "D0"
            )
            if result
            else []
        )
        rows.append(
            {
                "budget": budget,
                "source_parents_available": available,
                "complete_recombination_calls": int(budget > 0),
                "candidate_found": int(result is not None),
                "additive_score": result.additive_score if result else "",
                "selected_sources": (
                    "|".join(result.selected_sources) if result else ""
                ),
                "coverage_exact": int(covered == list("ABCD")) if result else 0,
            }
        )
    failures = []
    if rows[0]["complete_recombination_calls"] != 0:
        failures.append("budget_zero_called_solver")
    if rows[1]["additive_score"] != 50.0:
        failures.append("single_parent_score_differs")
    if rows[2]["additive_score"] != 20.0 or rows[3]["additive_score"] != 20.0:
        failures.append("multi_parent_exact_score_differs")
    if set(str(rows[2]["selected_sources"]).split("|")) != {"HGS", "ALNS"}:
        failures.append("multi_parent_solution_does_not_mix_sources")
    decision = {
        "verdict": (
            "PASS_EXACT_ROUTE_POOL_FUNCTION_ACCOUNTING"
            if not failures
            else "FAIL_EXACT_ROUTE_POOL_FUNCTION_ACCOUNTING"
        ),
        "failures": failures,
        "performance_claim_allowed": False,
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.exact-route-pool-microprobe.v1",
        "purpose": "artificial functionality and accounting only",
        "sources": [
            "Kelly and Xu 1999, doi:10.1287/ijoc.11.2.161",
            "Dumez et al. 2021, doi:10.1016/j.ejtl.2021.100040",
            "Hiermann et al. 2019, doi:10.1016/j.ejor.2018.06.025",
        ],
        "solver": "scipy.optimize.milp",
        "nonadditive_terms": (
            "not represented in master; every assembled solution requires "
            "full ReSETP evaluation and a parent-preserving monotone envelope"
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        "# 精确路线仓库功能小门\n\n"
        f"判定：`{decision['verdict']}`。预算0不调用；只给HGS母解时"
        "人工总分50；同时给HGS与ALNS路线后，精确重组取两边各一条路线，"
        "人工总分20且客户恰好覆盖一次。本包不含真实性能主张。\n",
    )
    atomic_json(
        OUT / "artifact_hashes.json",
        {
            path.name: sha256(path)
            for path in sorted(OUT.iterdir())
            if path.is_file() and path.name != "artifact_hashes.json"
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
