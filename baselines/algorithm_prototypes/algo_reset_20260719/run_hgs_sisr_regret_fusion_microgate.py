#!/usr/bin/env python3
"""One-seed gate for HGS offspring educated by SISR plus regret-2 repair."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from typing import Any


BASE = Path(__file__).resolve().parent
SOURCE = BASE / "run_route_core_microgate.py"
SPEC = importlib.util.spec_from_file_location("route_core_gate", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {SOURCE}")
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)

BASELINE_OUT = BASE / "route_core_microgate"
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--education-interval", type=int, default=1)
    parser.add_argument("--output-suffix", default="")
    args = parser.parse_args()
    interval = max(1, int(args.education_interval))
    out_name = "hgs_sisr_regret_fusion_microgate"
    if args.output_suffix:
        out_name += f"_{args.output_suffix}"
    out = BASE / out_name
    with (BASELINE_OUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        baseline_rows = list(csv.DictReader(handle))
    baselines = {
        (row["instance"], row["algorithm"]): row
        for row in baseline_rows
        if row["algorithm"] in {"pyvrp_0_12_2_hgs", "project_alns"}
    }
    GATE.OUT = out
    rows = []
    comparisons = []
    for name in GATE.INSTANCES:
        contract = GATE.HELPERS.bundle_contract(name)
        initial = GATE.HELPERS.deterministic_common_initial_solution(
            contract["bundle"].instance,
            capacity=contract["capacity"],
        )
        fused_row, _ = GATE.run_external(
            name=name,
            algorithm="hgs_with_sisr_regret_offspring_education",
            python=GATE.PY_HGS,
            seconds=GATE.TOTAL_SECONDS,
            contract=contract,
            initial=initial,
            educator="sisr_regret",
            education_interval=interval,
        )
        rows.append(fused_row)
        fused = float(fused_row["lexicographic_score"])
        hgs = float(baselines[(name, "pyvrp_0_12_2_hgs")]["lexicographic_score"])
        alns = float(baselines[(name, "project_alns")]["lexicographic_score"])
        education = json.loads(str(fused_row["education"]))
        comparisons.append(
            {
                "instance": name,
                "fused_score": fused,
                "pure_hgs_score": hgs,
                "pure_alns_score": alns,
                "strict_hgs_win": fused < hgs - TOL,
                "strict_alns_win": fused < alns - TOL,
                "strict_double_win": fused < min(hgs, alns) - TOL,
                "education_calls": int(education.get("education_calls", 0)),
                "education_accepted": int(education.get("education_accepted", 0)),
                "sequence_removed_customers": int(
                    education.get("sequence_removed_customers", 0)
                ),
            }
        )

    failures = [
        f"{row['instance']}:{row['algorithm']}"
        for row in rows
        if row["status"] != "OK"
    ]
    double_wins = sum(item["strict_double_win"] for item in comparisons)
    hgs_wins = sum(item["strict_hgs_win"] for item in comparisons)
    alns_wins = sum(item["strict_alns_win"] for item in comparisons)
    active = sum(item["education_accepted"] > 0 for item in comparisons)
    aggregate_fused = sum(item["fused_score"] for item in comparisons)
    aggregate_hgs = sum(item["pure_hgs_score"] for item in comparisons)
    aggregate_alns = sum(item["pure_alns_score"] for item in comparisons)
    strong = (
        not failures
        and double_wins >= 4
        and hgs_wins >= 5
        and alns_wins >= 5
        and active >= 2
        and aggregate_fused < min(aggregate_hgs, aggregate_alns) - TOL
    )
    decision = {
        "verdict": (
            "GO_SISR_REGRET_THREE_SEED_DEVELOPMENT"
            if strong
            else "STOP_SISR_REGRET_OFFSPRING_EDUCATOR"
        ),
        "strong_positive": strong,
        "strict_double_win_count": double_wins,
        "strict_hgs_win_count": hgs_wins,
        "strict_alns_win_count": alns_wins,
        "education_active_instance_count": active,
        "aggregate_scores": {
            "fused": aggregate_fused,
            "pure_hgs": aggregate_hgs,
            "pure_alns": aggregate_alns,
        },
        "failure_tasks": failures,
        "predeclared_gate": {
            "strict_double_wins_minimum": 4,
            "strict_hgs_wins_minimum": 5,
            "strict_alns_wins_minimum": 5,
            "education_active_instances_minimum": 2,
            "aggregate_strictly_beats_both": True,
        },
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.algo-reset.hgs-sisr-regret-fusion.v1",
        "instances": list(GATE.INSTANCES),
        "seed": GATE.SEED,
        "equal_wall_clock_seconds": GATE.TOTAL_SECONDS,
        "education_interval": interval,
        "architecture": (
            "HGS route improvement -> sequence removal and regret-2 repair -> "
            "HGS route improvement -> population insertion"
        ),
        "source_basis": [
            "Christiaens and Vanden Berghe 2020 SISR, doi:10.1287/trsc.2019.0914",
            "Wouda and Lan 2023 ALNS, doi:10.21105/joss.05028",
            "Voigt et al. 2025 ALNS review, doi:10.1016/j.ejor.2024.05.033",
            "Vidal 2022 HGS-CVRP, doi:10.1016/j.cor.2021.105643",
        ],
        "baseline_raw_runs_sha256": sha256(BASELINE_OUT / "raw_runs.csv"),
        "claim_boundary": (
            "One-seed development microgate. It can reject this educator or "
            "justify a three-seed follow-up, never a paper claim."
        ),
    }
    out.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(out / "raw_runs.csv", buffer.getvalue())
    atomic_json(out / "comparisons.json", comparisons)
    atomic_json(out / "metadata.json", metadata)
    atomic_json(out / "decision.json", decision)
    atomic_text(
        out / "report.md",
        "# HGS 内嵌成段移除与后悔修复最小门\n\n"
        f"结论：`{decision['verdict']}`。双赢 {double_wins}/6，"
        f"胜 HGS {hgs_wins}/6，胜 ALNS {alns_wins}/6，"
        f"新教育被真正接受 {active}/6。\n\n"
        "这是 HGS 子代内部的融合，不是两台算法先后串行。"
        "只作单种子开发判断。\n",
    )
    hashes = {
        path.name: sha256(path)
        for path in sorted(out.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    atomic_json(out / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
