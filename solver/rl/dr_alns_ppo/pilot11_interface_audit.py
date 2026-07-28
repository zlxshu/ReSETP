from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


CURRENT_BLOCK_INTERFACE: dict[str, Any] = {
    "obs_dim": 24,
    "action_heads": ["destroy", "repair", "q_ratio", "threshold_ratio", "exploration_ratio", "search_control"],
    "known_limits": [
        "No route sequence state",
        "No customer time-window feature table",
        "No direct charging strategy head",
        "No learned repair insertion decision",
    ],
    "source_files": [
        "solver/rl/dr_alns_ppo/block_env.py",
        "solver/rl/dr_alns_ppo/action_space.py",
    ],
}


REQUIRED_LITERATURE_SIGNALS: list[dict[str, str]] = [
    {
        "name": "route_sequence_state",
        "source": "Wang CEVRP / current-solution graph-state DR-ALNS references",
        "current_status": "missing",
        "resetp_candidate_source": "Solution.routes[].node_sequence",
        "first_audit_step": "Trace whether different route sequences collapse into the same 19-feature observation.",
        "why_it_matters": "Operator value depends on current route structure.",
    },
    {
        "name": "customer_time_window_state",
        "source": "PPO-ALNS VRPTW observation dictionary",
        "current_status": "missing",
        "resetp_candidate_source": "instance.json customer demand, service, and time-window fields",
        "first_audit_step": "Extract per-customer feasibility pressure and compare it with block gains.",
        "why_it_matters": "Repair and insertion quality depends on demand, service, and time windows.",
    },
    {
        "name": "vehicle_energy_state",
        "source": "EVRP and fleet-routing DRL literature",
        "current_status": "missing",
        "resetp_candidate_source": "vehicle table, route vehicle_type, and solution charging_actions",
        "first_audit_step": "Map route-level CV/EV energy pressure before adding an energy-aware policy head.",
        "why_it_matters": "EV charging and carbon decisions require vehicle-specific energy context.",
    },
    {
        "name": "charging_strategy_control",
        "source": "CEVRP DRL-ALNS energy operator head",
        "current_status": "missing",
        "resetp_candidate_source": "setp_solver.search.candidates charging repair functions",
        "first_audit_step": "Audit existing charging repair entry points before exposing a policy action.",
        "why_it_matters": "Carbon and energy phases need an action that directly affects charging behavior.",
    },
    {
        "name": "acceptance_or_stop_control",
        "source": "Reijnen DR-ALNS and PPO-ALNS acceptance/stop actions",
        "current_status": "present",
        "resetp_candidate_source": "block search-control head with continue/stop/restart plus threshold ratio",
        "first_audit_step": "Verify short PPO runs actually sample stop/restart and do not collapse to continue.",
        "why_it_matters": "The policy needs direct control over accepting worse candidates or stopping search.",
    },
    {
        "name": "learned_repair_or_insertion_control",
        "source": "Neural LNS / learned repair routing literature",
        "current_status": "missing",
        "resetp_candidate_source": "candidate insertion scoring and repair operators",
        "first_audit_step": "Keep as a separate research branch because it changes the learner role.",
        "why_it_matters": "High-upside neural LNS gains often come from repair/construction, not only selection.",
    },
    {
        "name": "q_threshold_exploration_control",
        "source": "Pilot09/Pilot10 meta headroom",
        "current_status": "present",
        "resetp_candidate_source": "action_space.py BLOCK_Q_RATIOS/BLOCK_THRESHOLD_RATIOS/BLOCK_EXPLORATION_RATIOS",
        "first_audit_step": "Use best static/tuned meta as the comparison bar for any future dynamic policy.",
        "why_it_matters": "Static tuning helps, but dynamic policy did not beat best static meta.",
    },
]


def build_gap_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for signal in REQUIRED_LITERATURE_SIGNALS:
        status = "present" if signal["current_status"] == "present" else "missing"
        rows.append(
            {
                "name": signal["name"],
                "status": status,
                "source": signal["source"],
                "resetp_candidate_source": signal["resetp_candidate_source"],
                "first_audit_step": signal["first_audit_step"],
                "why_it_matters": signal["why_it_matters"],
            }
        )
    return rows


def classify_gate(rows: list[dict[str, str]]) -> dict[str, object]:
    missing = [row["name"] for row in rows if row["status"] == "missing"]
    return {
        "status": "NEEDS_INTERFACE_REDESIGN" if missing else "NO_INTERFACE_GAP",
        "missing_count": len(missing),
        "missing": missing,
        "recommended_first_audit": ["charging_strategy_control"],
        "long_training_allowed": False,
        "baseline_rule": "future DR must beat best static/tuned meta, not default AlphaUCB",
    }


def write_audit_report(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = build_gap_rows()
    gate = classify_gate(rows)
    payload: dict[str, object] = {
        "current_interface": CURRENT_BLOCK_INTERFACE,
        "gap_rows": rows,
        "gate": gate,
    }

    (output_dir / "pilot11_interface_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_gap_csv(output_dir / "pilot11_interface_gap_rows.csv", rows)
    (output_dir / "pilot11_interface_audit.md").write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _write_gap_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["name", "status", "source", "resetp_candidate_source", "first_audit_step", "why_it_matters"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(payload: dict[str, object]) -> str:
    current = payload["current_interface"]
    gate = payload["gate"]
    rows = payload["gap_rows"]
    assert isinstance(current, dict)
    assert isinstance(gate, dict)
    assert isinstance(rows, list)

    lines = [
        "# Pilot11 Interface Audit",
        "",
        f"Gate: `{gate['status']}`",
        f"Long training allowed: `{gate['long_training_allowed']}`",
        f"Baseline rule: {gate['baseline_rule']}",
        "",
        "## Current Block Interface",
        "",
        f"- Observation dimension: `{current['obs_dim']}`",
        f"- Action heads: `{', '.join(str(head) for head in current['action_heads'])}`",
        "",
        "## Gap Rows",
        "",
    ]
    for row in rows:
        assert isinstance(row, dict)
        lines.extend(
            [
                f"### {row['name']}",
                "",
                f"- Status: `{row['status']}`",
                f"- Literature/source basis: {row['source']}",
                f"- ReSETP candidate source: {row['resetp_candidate_source']}",
                f"- First audit step: {row['first_audit_step']}",
                f"- Why it matters: {row['why_it_matters']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write the Pilot11 no-training interface audit report.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot11_interface_audit"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    write_audit_report(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
