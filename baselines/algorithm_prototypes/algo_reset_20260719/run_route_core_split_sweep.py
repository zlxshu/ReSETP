#!/usr/bin/env python3
"""Final cheap split diagnosis after the 1s+1s route-core gate failed."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
GATE_PATH = BASE / "run_route_core_microgate.py"
SPEC = importlib.util.spec_from_file_location("route_core_gate", GATE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {GATE_PATH}")
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)

BASELINE_OUT = BASE / "route_core_microgate"
OUT = BASE / "route_core_split_sweep"
ALLOCATIONS = ((1.5, 0.5), (1.8, 0.2))
TOL = 1e-8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def main() -> int:
    with (BASELINE_OUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        baseline_rows = list(csv.DictReader(handle))
    baselines = {
        (row["instance"], row["algorithm"]): row
        for row in baseline_rows
        if row["algorithm"] in {"pyvrp_0_12_2_hgs", "project_alns"}
    }
    GATE.OUT = OUT
    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for hgs_seconds, alns_seconds in ALLOCATIONS:
        split_name = f"hgs{hgs_seconds:.1f}_alns{alns_seconds:.1f}"
        for name in GATE.INSTANCES:
            contract = GATE.HELPERS.bundle_contract(name)
            initial = GATE.HELPERS.deterministic_common_initial_solution(
                contract["bundle"].instance,
                capacity=contract["capacity"],
            )
            seed_row, seed_solution = GATE.run_external(
                name=name,
                algorithm=f"{split_name}_seed",
                python=GATE.PY_HGS,
                seconds=hgs_seconds,
                contract=contract,
                initial=initial,
            )
            hybrid_row, _ = GATE.run_alns(
                name=name,
                algorithm=split_name,
                seconds=alns_seconds,
                contract=contract,
                initial=seed_solution,
            )
            hybrid_row["time_limit_seconds"] = 2.0
            hybrid_row["elapsed_seconds"] = (
                float(seed_row["elapsed_seconds"])
                + float(hybrid_row["elapsed_seconds"])
            )
            rows.extend((seed_row, hybrid_row))
            hybrid_score = float(hybrid_row["lexicographic_score"])
            hgs_score = float(
                baselines[(name, "pyvrp_0_12_2_hgs")]["lexicographic_score"]
            )
            alns_score = float(
                baselines[(name, "project_alns")]["lexicographic_score"]
            )
            comparisons.append(
                {
                    "allocation": split_name,
                    "instance": name,
                    "hybrid_score": hybrid_score,
                    "hgs_score": hgs_score,
                    "alns_score": alns_score,
                    "strict_hgs_win": hybrid_score < hgs_score - TOL,
                    "strict_alns_win": hybrid_score < alns_score - TOL,
                    "strict_double_win": hybrid_score < min(hgs_score, alns_score) - TOL,
                }
            )
    summaries = {}
    for hgs_seconds, alns_seconds in ALLOCATIONS:
        split_name = f"hgs{hgs_seconds:.1f}_alns{alns_seconds:.1f}"
        selected = [
            item for item in comparisons if item["allocation"] == split_name
        ]
        aggregate_hybrid = sum(item["hybrid_score"] for item in selected)
        aggregate_hgs = sum(item["hgs_score"] for item in selected)
        aggregate_alns = sum(item["alns_score"] for item in selected)
        summaries[split_name] = {
            "strict_hgs_wins": sum(item["strict_hgs_win"] for item in selected),
            "strict_alns_wins": sum(item["strict_alns_win"] for item in selected),
            "strict_double_wins": sum(item["strict_double_win"] for item in selected),
            "aggregate_hybrid": aggregate_hybrid,
            "aggregate_hgs": aggregate_hgs,
            "aggregate_alns": aggregate_alns,
            "aggregate_beats_both": (
                aggregate_hybrid < min(aggregate_hgs, aggregate_alns) - TOL
            ),
        }
    strong = [
        name
        for name, summary in summaries.items()
        if summary["strict_double_wins"] >= 4
        and summary["strict_hgs_wins"] >= 5
        and summary["strict_alns_wins"] >= 5
        and summary["aggregate_beats_both"]
    ]
    decision = {
        "verdict": (
            "GO_HOMBERGER_12X3_WITH_SPLIT"
            if strong
            else "STOP_SEQUENTIAL_HGS_ALNS_ROUTE_CORE"
        ),
        "passing_allocations": strong,
        "summaries": summaries,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "next_action_if_stop": (
            "Keep genuine HGS as the route-core strong baseline; move algorithm "
            "innovation to in-search mechanism specialists that HGS cannot express."
        ),
    }
    metadata = {
        "schema_version": "resetp.algo-reset.route-core-split-sweep.v1",
        "allocations_seconds": [list(value) for value in ALLOCATIONS],
        "instances": list(GATE.INSTANCES),
        "seed": GATE.SEED,
        "baseline_source_sha256": sha256(BASELINE_OUT / "raw_runs.csv"),
        "success_rule": (
            "at least 4/6 strict double wins, 5/6 strict wins against each "
            "component, and aggregate strict win against both"
        ),
        "claim_boundary": (
            "Final one-seed split diagnosis only; no paper or formal claim."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "comparisons.json", comparisons)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        "# HGS 与 ALNS 时间分工止损门\n\n"
        f"结论：`{decision['verdict']}`。\n\n"
        + "\n".join(
            f"- {name}: 双赢 {value['strict_double_wins']}/6，"
            f"胜HGS {value['strict_hgs_wins']}/6，"
            f"胜ALNS {value['strict_alns_wins']}/6。"
            for name, value in summaries.items()
        )
        + "\n\n这只是单种子开发诊断，不授权正式试验。\n",
    )
    hashes = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
