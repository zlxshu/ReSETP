#!/usr/bin/env python3
"""Backfill selection metadata on the completed 2026-08-15 suite health rows."""

from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "solver/reports/depot_pair_search_28cells_20260815"
OUTPUT = REPO / "data/ChinaInstances/china81_final_suite_v2_20260815"
HEALTH_FIELDS = (
    "source",
    "source_root",
    "instance_root",
    "witness_status",
    "checker_violation_count",
    "formal_search_allowed",
    "search_evaluations",
    "depot_count",
    "depot_pair_road_distance_km",
    "mixed_fleet_two_sides_status",
    "candidate_eligible",
    "candidate_elimination_reasons",
    "source_candidate_id",
    "selected_status",
    "selected_candidate_rank_in_cell",
    "main_case",
    "candidate_pool_total",
    "candidate_eligible_count",
    "contestability_lower_gate",
    "contestability_upper_gate",
    "edf_witness_gate",
    "mixed_fleet_two_sides_gate",
    "formal_search_evaluations",
    "verdict",
    "depot_pair_road_distance_km_round_trip",
    "depot_pair_road_distance_detail",
)


def read_selected() -> tuple[dict[tuple[str, str, str], dict[str, str]], dict[tuple[str, str, str], Counter[str]], dict[tuple[str, str, str], int]]:
    selected: dict[tuple[str, str, str], dict[str, str]] = {}
    elimination_counts: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    eligible_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    with (REPORT / "selected_cells.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            key = (row["region"], row["customer_count"], row["replicate"])
            selected[key] = row
    with (REPORT / "depot_pair_search_log.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            key = (row["region"], row["customer_count"], row["replicate"])
            if row["eligible"] == "1":
                eligible_counts[key] += 1
            elif row["elimination_reason"]:
                elimination_counts[key][row["elimination_reason"]] += 1
            if row["candidate_id"] == selected[key]["selected_candidate_id"]:
                selected[key]["log_row"] = row
    return selected, elimination_counts, eligible_counts


def repair(path: Path, selected: dict, elimination_counts: dict, eligible_counts: dict) -> None:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    for field in HEALTH_FIELDS:
        if field not in fields:
            fields.append(field)
    by_id = {item["selected_candidate_id"]: (key, item) for key, item in selected.items()}
    for row in rows:
        if row.get("instance_id") not in by_id:
            continue
        key, selection = by_id[row["instance_id"]]
        log = selection["log_row"]
        distance = log["depot_pair_road_distance_km_round_trip"]
        depot_count = str(len(log["depot_ids"].split("|")))
        row.update(
            {
                "source": "DEPOTSEARCH",
                "source_root": "data/ChinaInstances/china81_final_suite_v2_20260815",
                "instance_root": f"data/ChinaInstances/china81_final_suite_v2_20260815/instances/{row['instance_id']}",
                "witness_status": log["witness_status"],
                "checker_violation_count": log["checker_violation_count"],
                "formal_search_allowed": "false",
                "search_evaluations": "0",
                "depot_count": depot_count,
                "depot_pair_road_distance_km": distance,
                "mixed_fleet_two_sides_status": log["mixed_fleet_two_sides_status"],
                "candidate_eligible": "1",
                "candidate_elimination_reasons": "",
                "source_candidate_id": row["instance_id"],
                "selected_status": "SELECTED_ELIGIBLE",
                "selected_candidate_rank_in_cell": "1",
                "main_case": "1" if key == ("jjj", "50", "01") else "0",
                "candidate_pool_total": selection["candidate_count"],
                "candidate_eligible_count": str(eligible_counts[key]),
                "candidate_eliminated_reason_distribution": json.dumps(
                    dict(sorted(elimination_counts[key].items())),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "contestability_lower_gate": "NOT_APPLIED_BY_DEPOT_SEARCH_RULE",
                "contestability_upper_gate": "NOT_APPLIED_BY_DEPOT_SEARCH_RULE",
                "edf_witness_gate": "PASS",
                "mixed_fleet_two_sides_gate": "PASS",
                "formal_search_evaluations": "0",
                "verdict": "PASS_DEPOT_SEARCH_SELECTED",
                "depot_pair_road_distance_km_round_trip": distance,
                "depot_pair_road_distance_detail": log["depot_pair_road_distance_detail"],
            }
        )
    tmp = path.with_suffix(path.suffix + ".repair_tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def main() -> int:
    selected, elimination_counts, eligible_counts = read_selected()
    repair(REPORT / "suite_health_v2.csv", selected, elimination_counts, eligible_counts)
    repair(OUTPUT / "suite_health_v2.csv", selected, elimination_counts, eligible_counts)
    print(f"repaired_health_rows={len(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
