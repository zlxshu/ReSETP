#!/usr/bin/env python3
"""Three-task one-seed gate for mechanism-aware initialisation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
V8_RUNNER = HERE / "run_v8_interleaved_microgate.py"
SPEC = importlib.util.spec_from_file_location("v8_gate_helpers", V8_RUNNER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {V8_RUNNER}")
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)

from v9_mechanism_seeded_solver import run_mechanism_alns_v9_seeded  # noqa: E402


GATE.OUT = HERE / "mechanism_v9_seeded_microgate"


def main() -> int:
    rows = []
    comparisons = []
    for instance in GATE.INSTANCES:
        bundle = GATE.BUNDLES / instance
        baseline = GATE.run_mechanism_alns_v7(
            bundle,
            seed=GATE.SEED,
            eval_budget=GATE.BUDGET,
            prices=GATE.PRICES,
        )
        candidate = run_mechanism_alns_v9_seeded(
            bundle,
            seed=GATE.SEED,
            eval_budget=GATE.BUDGET,
            prices=GATE.PRICES,
            seed_count=4,
            per_seed_budget=10,
        )
        baseline_row = GATE.row(instance, baseline)
        candidate_row = GATE.row(instance, candidate)
        rows.extend((baseline_row, candidate_row))
        delta = candidate_row["recomputed_cost"] - baseline_row["recomputed_cost"]
        activity = candidate.mechanism_activity
        seed_active = sum(
            int(item["joint_improvements"]) + int(item["carbon_improvements"]) > 0
            for item in activity["seed_summaries"]
        )
        comparisons.append(
            {
                "instance": instance,
                "baseline_v7_cost": baseline_row["recomputed_cost"],
                "candidate_v9_cost": candidate_row["recomputed_cost"],
                "candidate_minus_baseline": delta,
                "strict_win": delta < -GATE.TOL,
                "nonloss": delta <= GATE.TOL,
                "selected_seed_index": activity["selected_seed_index"],
                "mechanism_active_seed_count": seed_active,
            }
        )
    failures = [
        f"{item['instance']}:{item['algorithm']}"
        for item in rows
        if not item["feasible"]
        or not item["cost_match"]
        or int(item["evaluations"]) != GATE.BUDGET
    ]
    wins = sum(item["strict_win"] for item in comparisons)
    nonloss = sum(item["nonloss"] for item in comparisons)
    diverse = sum(item["selected_seed_index"] != 0 for item in comparisons)
    active = sum(item["mechanism_active_seed_count"] > 0 for item in comparisons)
    strong = not failures and wins >= 2 and nonloss == 3 and diverse >= 1 and active >= 2
    decision = {
        "verdict": (
            "GO_V9_THREE_SEED_DEVELOPMENT"
            if strong
            else "STOP_MECHANISM_AWARE_MULTISEED"
        ),
        "strong_positive": strong,
        "strict_win_count": wins,
        "nonloss_count": nonloss,
        "nondefault_seed_selected_instance_count": diverse,
        "mechanism_active_instance_count": active,
        "failure_tasks": failures,
        "predeclared_gate": {
            "strict_wins_minimum": 2,
            "nonloss_required": 3,
            "nondefault_seed_selected_minimum": 1,
            "active_instances_minimum": 2,
        },
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.mechanism-v9-seeded-microgate.v1",
        "instances": list(GATE.INSTANCES),
        "seed": GATE.SEED,
        "complete_route_evaluation_budget": GATE.BUDGET,
        "seed_count": 4,
        "per_seed_budget": 10,
        "continuation_budget": 60,
        "battery_kwh": 280.0,
        "claim_boundary": (
            "One-seed development microgate only. It tests whether mechanism-"
            "aware seed competition is worth a three-seed follow-up."
        ),
    }
    GATE.OUT.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    GATE.atomic_text(GATE.OUT / "raw_runs.csv", buffer.getvalue())
    GATE.atomic_json(GATE.OUT / "comparisons.json", comparisons)
    GATE.atomic_json(GATE.OUT / "metadata.json", metadata)
    GATE.atomic_json(GATE.OUT / "decision.json", decision)
    GATE.atomic_text(
        GATE.OUT / "report.md",
        "# 机制感知强初始化最小门\n\n"
        f"结论：`{decision['verdict']}`。严格胜 {wins}/3，"
        f"不退步 {nonloss}/3，非默认起点被选中 {diverse}/3。\n\n"
        "四份短搜索先经车型—充电—碳时刻修复，再选最好起点进入一次连续主搜索。"
        "本门不授权正式试验。\n",
    )
    hashes = {
        path.name: GATE.sha256(path)
        for path in sorted(GATE.OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    GATE.atomic_json(GATE.OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
