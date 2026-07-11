"""Audit the frozen E2 hybrid-vs-LNS losses before any recovery experiment."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import statistics


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "baselines/e2_alns/e2_submission_20260711/carbon_280"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/e2_loss_recovery_20260711"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _loss_class(gain_pct: float, route_delta: int, ev_route_delta: int) -> str:
    if gain_pct <= -5.0:
        return "large_stochastic_tail"
    if route_delta > 0:
        return "extra_route_or_partition"
    if route_delta < 0 and ev_route_delta < 0:
        return "fleet_energy_mix_tradeoff"
    if gain_pct > -0.5:
        return "near_tie"
    return "route_fleet_structure"


def run() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(SOURCE_DIR / "raw_runs.csv")
    selected = {
        (row["instance"], int(row["seed"]), row["algorithm"]): row
        for row in rows
        if row["algorithm"] in {"staged_hybrid_carbon_aware", "LNS"}
    }
    pairs: list[dict[str, object]] = []
    for instance, seed, algorithm in sorted(selected):
        if algorithm != "staged_hybrid_carbon_aware":
            continue
        hybrid = selected[(instance, seed, algorithm)]
        lns = selected[(instance, seed, "LNS")]
        hybrid_cost = float(hybrid["best_cost"])
        lns_cost = float(lns["best_cost"])
        gain_pct = (lns_cost - hybrid_cost) / lns_cost * 100.0
        route_delta = int(hybrid["route_count"]) - int(lns["route_count"])
        ev_route_delta = int(hybrid["ev_route_count"]) - int(lns["ev_route_count"])
        staged = json.loads(hybrid["operator_counts_json"]).get("staged_chain", {})
        pairs.append(
            {
                "instance": instance,
                "seed": seed,
                "hybrid_cost": hybrid_cost,
                "lns_cost": lns_cost,
                "gain_vs_lns_pct": gain_pct,
                "outcome": "WIN" if gain_pct > 1e-9 else "TIE" if abs(gain_pct) <= 1e-9 else "LOSS",
                "loss_class": "" if gain_pct >= -1e-9 else _loss_class(gain_pct, route_delta, ev_route_delta),
                "route_delta": route_delta,
                "ev_route_delta": ev_route_delta,
                "cv_emissions_delta": float(hybrid["E_cv_direct"]) - float(lns["E_cv_direct"]),
                "ev_emissions_delta": float(hybrid["E_ev_indirect"]) - float(lns["E_ev_indirect"]),
                "carbon_cost_delta": float(hybrid["cost_carbon"]) - float(lns["cost_carbon"]),
                "runtime_ratio": float(hybrid["elapsed_seconds"]) / float(lns["elapsed_seconds"]),
                "best_stage": staged.get("best_phase"),
                "phase_best_costs": json.dumps(staged.get("phase_best_objs", []), separators=(",", ":")),
            }
        )
    losses = [row for row in pairs if row["outcome"] == "LOSS"]
    summaries: list[dict[str, object]] = []
    for instance in sorted({str(row["instance"]) for row in pairs}):
        current = [row for row in pairs if row["instance"] == instance]
        gains = [float(row["gain_vs_lns_pct"]) for row in current]
        summaries.append(
            {
                "instance": instance,
                "wins": sum(value > 1e-9 for value in gains),
                "ties": sum(abs(value) <= 1e-9 for value in gains),
                "losses": sum(value < -1e-9 for value in gains),
                "mean_gain_pct": statistics.mean(gains),
                "median_gain_pct": statistics.median(gains),
                "worst_gain_pct": min(gains),
            }
        )
    _write_csv(OUTPUT_DIR / "all_pairs.csv", pairs)
    _write_csv(OUTPUT_DIR / "loss_pairs.csv", losses)
    _write_csv(OUTPUT_DIR / "per_instance_summary.csv", summaries)
    decision = {
        "verdict": "E2_LOSS_RECOVERY_GATE_REQUIRED",
        "source_is_frozen_e2": True,
        "pair_count": len(pairs),
        "wins": sum(row["outcome"] == "WIN" for row in pairs),
        "ties": sum(row["outcome"] == "TIE" for row in pairs),
        "losses": len(losses),
        "mean_loss_pct": statistics.mean(float(row["gain_vs_lns_pct"]) for row in losses),
        "losses_worse_than_5pct": sum(float(row["gain_vs_lns_pct"]) <= -5.0 for row in losses),
        "losses_with_extra_routes": sum(int(row["route_delta"]) > 0 for row in losses),
        "losses_best_in_middle_stage": sum(int(row["best_stage"]) == 2 for row in losses),
        "recovery_hypothesis": "split the 3200-evaluation strong middle stage into two independently seeded 1600-evaluation basins, restart the second basin from the first basin best, and preserve the 400+3200+400 total budget",
        "short_gate": {
            "stage_a_budget": 1600,
            "compare": ["existing staged chain", "restart staged chain"],
            "development_pairs": "six losses at least 2pct plus three existing wins as anti-regression guards",
            "promotion_rule": "restart candidate improves mean loss-pair cost, turns at least two losses into wins/ties, and degrades no guard pair by more than 2pct",
        },
        "formal_validation_rule": "after the short gate, use unseen seeds before rerunning the paper seeds; do not claim recovery from development pairs alone",
    }
    _write_json(OUTPUT_DIR / "decision.json", decision)
    _write_json(
        OUTPUT_DIR / "metadata.json",
        {
            "schema_version": "setp-e2-loss-recovery-audit.v1",
            "source_raw_runs": str((SOURCE_DIR / "raw_runs.csv").relative_to(REPO_ROOT)),
            "source_commit": "0124623e347cd2a6a5548e07e0af66e16d3b634b",
            "battery_kwh": 280.0,
            "eval_budget": 4000,
            "protected_contract_changed": False,
        },
    )
    report = f"""# E2 loss-recovery audit

The frozen E2 result has {decision['wins']} wins, {decision['ties']} ties, and {decision['losses']} losses against LNS.  The mean loss magnitude is {abs(float(decision['mean_loss_pct'])):.3f}%, while {decision['losses_worse_than_5pct']} losses exceed 5%.

The losses are not one defect.  Some use extra routes, one large 150c loss uses fewer routes but a much worse fleet/emissions mix, and nine of fifteen losses finish with their best solution in the middle strong-search stage.  The first bounded recovery hypothesis is therefore a restart of the strong middle stage, not another parameter sweep.

No frozen E2 row is rewritten by this audit.  The candidate must first pass an equal-budget 1600-evaluation short gate, then unseen-seed validation, before any full paper matrix is rerun.  A smaller budget would leave no meaningful strong middle stage after the fixed 400-evaluation opening and closing stages.
"""
    (OUTPUT_DIR / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        str(path.relative_to(OUTPUT_DIR)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(OUTPUT_DIR.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    _write_json(OUTPUT_DIR / "artifact_hashes.json", hashes)
    return decision


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
