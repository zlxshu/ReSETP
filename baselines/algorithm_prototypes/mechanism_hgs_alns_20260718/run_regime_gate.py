#!/usr/bin/env python3
"""Validate the multi-depot-only activation rule under equal budgets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
for path in (REPO / "solver/src", HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from prototype import independent_cost, run_combined, run_outer_search, run_pure_alns  # noqa: E402
from regime_switch import activation_decision  # noqa: E402


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=int, default=100)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("bundles", nargs="+", type=Path)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    seeds = [int(item) for item in args.seeds.split(",") if item.strip()]
    rows: list[dict[str, Any]] = []
    for raw_bundle in args.bundles:
        bundle = raw_bundle.resolve()
        switch = activation_decision(bundle)
        for seed in seeds:
            alns = run_pure_alns(bundle, seed=seed, eval_budget=args.budget)
            hgs = run_outer_search(bundle, seed=seed, eval_budget=args.budget)
            routed = (
                run_combined(
                    bundle,
                    seed=seed,
                    eval_budget=args.budget,
                    outer_share=0.01,
                    inner_basins=1,
                )
                if switch["enabled"]
                else run_pure_alns(bundle, seed=seed, eval_budget=args.budget)
            )
            costs = {
                "pure_alns": independent_cost(bundle, alns.best_solution),
                "pure_hgs_style_outer": independent_cost(bundle, hgs.best_solution),
                "regime_routed": independent_cost(bundle, routed.best_solution),
            }
            rows.append(
                {
                    "instance": bundle.name,
                    "seed": seed,
                    "switch_enabled": switch["enabled"],
                    "switch_reasons": json.dumps(switch["reasons"], sort_keys=True),
                    "result_fields_read": switch["result_fields_read"],
                    "budget": args.budget,
                    "alns_evaluations": alns.evaluations,
                    "hgs_evaluations": hgs.evaluations,
                    "routed_evaluations": routed.evaluations,
                    "alns_cost": costs["pure_alns"],
                    "hgs_cost": costs["pure_hgs_style_outer"],
                    "routed_cost": costs["regime_routed"],
                    "beats_alns": costs["regime_routed"] < costs["pure_alns"] - 1e-9,
                    "beats_hgs": costs["regime_routed"] < costs["pure_hgs_style_outer"] - 1e-9,
                    "matches_alns_when_disabled": (
                        abs(costs["regime_routed"] - costs["pure_alns"]) <= 1e-9
                        if not switch["enabled"]
                        else True
                    ),
                    "all_feasible": alns.feasible and hgs.feasible and routed.feasible,
                    "budgets_exact": (
                        alns.evaluations == args.budget
                        and hgs.evaluations == args.budget
                        and routed.evaluations == args.budget
                    ),
                }
            )
    enabled = [row for row in rows if row["switch_enabled"]]
    disabled = [row for row in rows if not row["switch_enabled"]]
    enabled_double_wins = sum(row["beats_alns"] and row["beats_hgs"] for row in enabled)
    accounting = all(row["budgets_exact"] and row["all_feasible"] and not row["result_fields_read"] for row in rows)
    disabled_safe = all(row["matches_alns_when_disabled"] for row in disabled)
    strong = accounting and bool(enabled) and enabled_double_wins == len(enabled) and disabled_safe
    decision = {
        "decision": "STRONG_MULTIDEPOT_SWITCH_SIGNAL" if strong else "HOLD_MULTIDEPOT_SWITCH",
        "strong_effect": strong,
        "formal_search_allowed": False,
        "enabled_tasks": len(enabled),
        "enabled_double_wins": enabled_double_wins,
        "disabled_tasks": len(disabled),
        "disabled_exact_alns_matches": sum(row["matches_alns_when_disabled"] for row in disabled),
        "accounting_passed": accounting,
        "rule": "Enabled tasks must beat both pure arms; disabled tasks must exactly match pure ALNS.",
    }
    fields = list(rows[0])
    with (out / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write_json(
        out / "metadata.json",
        {
            "development_only": True,
            "formal_search_allowed": False,
            "budget": args.budget,
            "seeds": seeds,
            "bundles": [str(path.resolve().relative_to(REPO)) for path in args.bundles],
            "activation_rule": "explicit multidepot contract AND at least two depots AND no multi-shift marker",
        },
    )
    write_json(out / "decision.json", decision)
    (out / "report.md").write_text(
        "\n".join(
            [
                "# Multi-depot-only HGS--ALNS switch gate",
                "",
                f"- Decision: `{decision['decision']}`",
                f"- Enabled double wins: {enabled_double_wins}/{len(enabled)}",
                f"- Disabled exact ALNS matches: {decision['disabled_exact_alns_matches']}/{len(disabled)}",
                "- Formal search remains forbidden.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_json(
        out / "artifact_hashes.json",
        {
            path.name: sha256(path)
            for path in sorted(out.iterdir())
            if path.is_file() and path.name != "artifact_hashes.json"
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if accounting else 1


if __name__ == "__main__":
    raise SystemExit(main())
