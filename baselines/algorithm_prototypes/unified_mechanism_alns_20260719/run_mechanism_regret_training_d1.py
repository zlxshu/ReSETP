#!/usr/bin/env python3
"""Training-only diagnosis of the model-aware regret constructor on seen D1."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (REPO / "solver/src", REPO / "models/src", HERE, LEGACY, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from initial_pool import result_rows, solution_payload  # noqa: E402
from mechanism_regret_initializer import (  # noqa: E402
    build_and_score_mechanism_regret_pool,
)
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from terminal_completion import apply_terminal_completion  # noqa: E402


BUNDLES = HERE / "blind_d1_bundles"
OUT = HERE / "mechanism_regret_training_d1"
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
SEED = 1
TOL = 1.0e-9


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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite training evidence: {OUT}")
    manifest = json.loads(
        (BUNDLES / "manifest.json").read_text(encoding="utf-8")
    )
    instances = [str(item["instance_id"]) for item in manifest["instances"]]
    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    failures: list[str] = []
    started = time.perf_counter()
    for instance_id in instances:
        try:
            pool, ledgers = build_and_score_mechanism_regret_pool(
                BUNDLES / instance_id,
                seed=SEED,
                prices=PRICES,
            )
            for row in result_rows(pool):
                rows.append(
                    {
                        "instance_id": instance_id,
                        "seed": SEED,
                        **row,
                        "construction_ledger": json.dumps(
                            asdict(ledgers[row["label"]]),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                )
            anchor_terminal = apply_terminal_completion(
                BUNDLES / instance_id,
                pool.anchor.solution,
                prices=PRICES,
            )
            winner_terminal = apply_terminal_completion(
                BUNDLES / instance_id,
                pool.best.solution,
                prices=PRICES,
            )
            improvement = (
                (pool.anchor.raw_cost - pool.best.raw_cost)
                / pool.anchor.raw_cost
                * 100.0
            )
            terminal_improvement = (
                (anchor_terminal.cost - winner_terminal.cost)
                / anchor_terminal.cost
                * 100.0
            )
            comparisons.append(
                {
                    "instance_id": instance_id,
                    "anchor_cost": pool.anchor.raw_cost,
                    "winner_cost": pool.best.raw_cost,
                    "winner_label": pool.best.label,
                    "strict_win": pool.best.raw_cost < pool.anchor.raw_cost - TOL,
                    "improvement_percent": improvement,
                    "anchor_terminal_cost": anchor_terminal.cost,
                    "winner_terminal_cost": winner_terminal.cost,
                    "terminal_nonloss": (
                        winner_terminal.cost <= anchor_terminal.cost + TOL
                    ),
                    "terminal_improvement_percent": terminal_improvement,
                    "candidate_evaluations": pool.candidate_evaluations,
                    "reference_replays": pool.reference_replays,
                    "unique_route_structures": len(
                        {item.route_signature for item in pool.entries}
                    ),
                    "ledgers": {
                        label: asdict(ledger)
                        for label, ledger in ledgers.items()
                    },
                }
            )
            witnesses[instance_id] = {
                "anchor_initial": solution_payload(pool.anchor.solution),
                "winner_initial": solution_payload(pool.best.solution),
                "anchor_terminal": solution_payload(anchor_terminal.solution),
                "winner_terminal": solution_payload(winner_terminal.solution),
            }
        except Exception as exc:
            failures.append(f"{instance_id}:{type(exc).__name__}:{exc}")

    median_improvement = (
        statistics.median(
            item["improvement_percent"] for item in comparisons
        )
        if comparisons
        else float("-inf")
    )
    signal = (
        not failures
        and len(comparisons) == len(instances)
        and all(item["strict_win"] for item in comparisons)
        and all(item["terminal_nonloss"] for item in comparisons)
        and median_improvement >= 0.5
    )
    decision = {
        "verdict": (
            "TRAINING_SIGNAL_FREEZE_FOR_FRESH_GATE"
            if signal
            else "TRAINING_STOP_MODEL_AWARE_REGRET"
        ),
        "training_signal": signal,
        "seen_d1_training_data": True,
        "strict_win_count": sum(item["strict_win"] for item in comparisons),
        "terminal_nonloss_count": sum(
            item["terminal_nonloss"] for item in comparisons
        ),
        "median_improvement_percent": median_improvement,
        "failures": failures,
        "formal_search_allowed": False,
        "stage2_allowed": False,
        "claim_boundary": (
            "Seen D1 training diagnosis only. It may select a frozen design "
            "for a new dataset, but cannot confirm performance."
        ),
    }
    metadata = {
        "schema_version": "resetp.mechanism-regret-training-d1.v1",
        "instances": instances,
        "seed": SEED,
        "battery_kwh": PRICES.B_battery_kwh,
        "candidate_source_sha256": sha256(
            HERE / "mechanism_regret_initializer.py"
        ),
        "elapsed_seconds": time.perf_counter() - started,
        "dataset_already_seen": True,
        "formal_l_main_activated": False,
        "stage2_activated": False,
    }

    OUT.mkdir(parents=True)
    fields = [
        "instance_id",
        "seed",
        "label",
        "family",
        "type_mode",
        "objective",
        "raw_cost",
        "feasible",
        "violation_count",
        "route_count",
        "ev_route_count",
        "charging_action_count",
        "full_signature",
        "route_signature",
        "in_archive",
        "is_anchor",
        "is_best",
        "construction_ledger",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(OUT / "raw_runs.csv", buffer.getvalue())
    atomic_json(OUT / "comparisons.json", comparisons)
    atomic_json(OUT / "solution_witnesses.json", witnesses)
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(OUT / "decision.json", decision)
    atomic_text(
        OUT / "report.md",
        "# 模型感知全局后悔构造：D1 训练诊断\n\n"
        f"结论：`{decision['verdict']}`。严格胜 "
        f"{decision['strict_win_count']}/{len(instances)}，共同终局后不退步 "
        f"{decision['terminal_nonloss_count']}/{len(instances)}，中位改善 "
        f"{median_improvement:.6f}%。\n\n"
        "D1 已经看过结果，因此这里只能训练和选设计，不能确认性能，也不授权"
        "阶段二或正式试验。\n",
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
