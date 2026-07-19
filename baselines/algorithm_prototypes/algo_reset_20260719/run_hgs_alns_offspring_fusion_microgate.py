#!/usr/bin/env python3
"""One-seed gate for HGS offspring educated by project ALNS."""

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
SOURCE = BASE / "run_route_core_microgate.py"
SPEC = importlib.util.spec_from_file_location("route_core_gate", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {SOURCE}")
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)

BASELINE_OUT = BASE / "route_core_microgate"
OUT = BASE / "hgs_alns_offspring_fusion_microgate"
EDUCATION_EVALS = 2
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
            algorithm="hgs_with_project_alns_offspring_education",
            python=GATE.PY_HGS,
            seconds=GATE.TOTAL_SECONDS,
            contract=contract,
            initial=initial,
            alns_education_evals=EDUCATION_EVALS,
        )
        rows.append(fused_row)
        hgs = float(
            baselines[(name, "pyvrp_0_12_2_hgs")]["lexicographic_score"]
        )
        alns = float(
            baselines[(name, "project_alns")]["lexicographic_score"]
        )
        fused = float(fused_row["lexicographic_score"])
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
                "project_alns_complete_evaluations": int(
                    education.get("project_alns_complete_evaluations", 0)
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
            "GO_FUSION_THREE_SEED_DEVELOPMENT"
            if strong
            else "STOP_PROJECT_ALNS_OFFSPRING_EDUCATOR"
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
        "next_if_stop": (
            "Keep the offspring-education architecture but replace the weak "
            "project ALNS educator with mature sequence removal plus regret insertion."
        ),
    }
    metadata = {
        "schema_version": "resetp.algo-reset.hgs-alns-offspring-fusion.v1",
        "instances": list(GATE.INSTANCES),
        "seed": GATE.SEED,
        "equal_wall_clock_seconds": GATE.TOTAL_SECONDS,
        "education_complete_evaluations_per_offspring": EDUCATION_EVALS,
        "architecture": (
            "HGS route improvement -> project ALNS education -> HGS route "
            "improvement -> population insertion"
        ),
        "source_basis": [
            "Vidal et al. 2012 HGS education",
            "Zhao et al. 2025 HGS-IRP RI-DSI-RI",
            "HGS-IRP commit 61af0f43166719322f41916c36967bdeef01990c",
        ],
        "baseline_raw_runs_sha256": sha256(BASELINE_OUT / "raw_runs.csv"),
        "claim_boundary": (
            "One-seed development microgate. It can reject this educator or "
            "justify a three-seed development follow-up, never a paper claim."
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
        "# HGS 子代内嵌 ALNS 教育最小门\n\n"
        f"结论：`{decision['verdict']}`。双赢 {double_wins}/6，"
        f"胜HGS {hgs_wins}/6，胜ALNS {alns_wins}/6，"
        f"教育真实被接受 {active}/6。\n\n"
        "融合顺序是“路线改进—ALNS教育—路线改进—回群体”，"
        "不是先后跑两台算法。只作单种子开发判断。\n",
    )
    hashes = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    atomic_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
