#!/usr/bin/env python3
"""Read-only structural audit for the 09l mixed-band question.

This script does not optimize and does not modify model semantics. It joins
the source-bound battery screen with E2 instance geography/facility structure
to identify plausible non-battery drivers of CV/EV fleet composition.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from setp_solver.cost import ev_arc_energy_kwh
from setp_solver.prices import DEFAULT_PRICES


REPO = Path(__file__).resolve().parents[2]
INSTANCE_ROOT = REPO / "models/data_bundle/generated_instances/e2_benchmark"
SOURCE_BOUND_DIR = REPO / "baselines/e2_alns/source_bound_mixed_band_gate_data"
OUTPUT_DIR = REPO / "baselines/e2_alns/structural_mixed_band_investigation_data"
REPORT = REPO / "baselines/e2_alns/structural_mixed_band_investigation.md"
PRACTICAL_LOW = 0.20
PRACTICAL_HIGH = 0.80
FOCUS_MIN_SIZE = 75


@dataclass(frozen=True)
class InstanceRef:
    path: Path
    family: str
    instance: str
    size: int
    replicate: int


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    instance_rows = [instance_structure(row) for row in iter_instances()]
    write_csv(OUTPUT_DIR / "instance_structure.csv", instance_rows)

    winner_rows = read_csv(SOURCE_BOUND_DIR / "stage_a_winners.csv")
    joined_rows = join_winners_with_structure(winner_rows, instance_rows)
    focus_rows = [row for row in joined_rows if int(row["size"]) >= FOCUS_MIN_SIZE]
    write_csv(OUTPUT_DIR / "stage_a_75_200_joined.csv", focus_rows)

    candidate_focus = candidate_focus_summary(focus_rows)
    write_csv(OUTPUT_DIR / "candidate_75_200_summary.csv", candidate_focus)

    family_focus = family_size_summary(focus_rows)
    write_csv(OUTPUT_DIR / "family_size_75_200_summary.csv", family_focus)

    structure_summary = structure_by_family_size(instance_rows)
    write_csv(OUTPUT_DIR / "instance_structure_by_family_size.csv", structure_summary)

    correlations = driver_correlations(focus_rows)
    write_csv(OUTPUT_DIR / "driver_correlations.csv", correlations)

    failure_examples = select_failure_examples(focus_rows)
    write_csv(OUTPUT_DIR / "failure_examples_75_200.csv", failure_examples)

    write_json(
        OUTPUT_DIR / "metadata.json",
        {
            "verdict": "STRUCTURAL_AUDIT_ONLY",
            "interpretation": (
                "Read-only geography/facility audit. It can rank hypotheses, "
                "but cannot replace a full optimization gate."
            ),
            "instance_count": len(instance_rows),
            "joined_focus_rows": len(focus_rows),
            "source_bound_input": str(SOURCE_BOUND_DIR),
            "focus_size_min": FOCUS_MIN_SIZE,
            "practical_band": [PRACTICAL_LOW, PRACTICAL_HIGH],
        },
    )
    write_report(instance_rows, candidate_focus, family_focus, structure_summary, correlations, failure_examples)
    print(f"wrote {REPORT}")
    print(f"wrote {OUTPUT_DIR}")
    return 0


def iter_instances() -> list[InstanceRef]:
    refs: list[InstanceRef] = []
    for path in sorted(INSTANCE_ROOT.glob("*/*")):
        if not path.is_dir() or not (path / "instance.json").exists():
            continue
        match = re.match(r"e2-(?P<family>vanilla|multidepot|threeshift)-(?P<size>\d+)c-(?P<rep>\d+)$", path.name)
        if not match:
            continue
        refs.append(
            InstanceRef(
                path=path,
                family=match.group("family"),
                instance=path.name,
                size=int(match.group("size")),
                replicate=int(match.group("rep")),
            )
        )
    return refs


def instance_structure(ref: InstanceRef) -> dict[str, Any]:
    instance = json.loads((ref.path / "instance.json").read_text())
    manifest = json.loads((ref.path / "scenario_manifest.json").read_text())
    nodes = instance["nodes"]
    distance_matrix = np.load(ref.path / "distance_matrix.npy")

    customer_idx = [idx for idx, node in enumerate(nodes) if node["node_type"].lower() == "c"]
    depot_idx = [idx for idx, node in enumerate(nodes) if node["node_type"].lower() == "d"]
    station_idx = [idx for idx, node in enumerate(nodes) if node["node_type"].lower() == "f"]
    customer_coords = np.array([[float(nodes[idx]["x"]), float(nodes[idx]["y"])] for idx in customer_idx])
    depot_coords = np.array([[float(nodes[idx]["x"]), float(nodes[idx]["y"])] for idx in depot_idx])
    station_coords = np.array([[float(nodes[idx]["x"]), float(nodes[idx]["y"])] for idx in station_idx])

    c_to_d = distance_matrix[np.ix_(customer_idx, depot_idx)]
    c_to_f = distance_matrix[np.ix_(customer_idx, station_idx)] if station_idx else np.full((len(customer_idx), 1), np.nan)
    c_to_c = distance_matrix[np.ix_(customer_idx, customer_idx)].astype(float)
    np.fill_diagonal(c_to_c, np.inf)
    finite_pairs = c_to_c[np.isfinite(c_to_c)]

    nearest_depot = np.min(c_to_d, axis=1)
    nearest_station = np.min(c_to_f, axis=1)
    nearest_customer = np.min(c_to_c, axis=1)
    bbox_diag = math.hypot(
        float(customer_coords[:, 0].max() - customer_coords[:, 0].min()),
        float(customer_coords[:, 1].max() - customer_coords[:, 1].min()),
    )
    depot_separation = pairwise_min_distance(depot_coords)
    station_separation = pairwise_min_distance(station_coords)
    station_at_depot_count = count_station_at_depot(station_coords, depot_coords)
    demands = np.array([float(nodes[idx]["demand"]) for idx in customer_idx], dtype=float)
    tw_widths = np.array([float(nodes[idx]["due_time"]) - float(nodes[idx]["ready_time"]) for idx in customer_idx], dtype=float)
    service_times = np.array([float(nodes[idx]["service_time"]) for idx in customer_idx], dtype=float)

    roundtrip_nearest_depot = 2.0 * nearest_depot
    roundtrip_empty_kwh = np.array([ev_arc_energy_kwh(float(distance), 0.0, DEFAULT_PRICES) for distance in roundtrip_nearest_depot])
    one_way_empty_kwh = np.array([ev_arc_energy_kwh(float(distance), 0.0, DEFAULT_PRICES) for distance in nearest_depot])

    cfg = manifest.get("config", {})
    meta = instance.get("metadata", {})
    return {
        "instance": ref.instance,
        "family": ref.family,
        "size": ref.size,
        "replicate": ref.replicate,
        "customers": len(customer_idx),
        "depots": len(depot_idx),
        "stations": len(station_idx),
        "station_at_depot_count": station_at_depot_count,
        "station_per_customer": safe_div(len(station_idx), len(customer_idx)),
        "depot_per_customer": safe_div(len(depot_idx), len(customer_idx)),
        "bbox_diag_km": km(bbox_diag),
        "nearest_depot_p50_km": pct_km(nearest_depot, 50),
        "nearest_depot_p75_km": pct_km(nearest_depot, 75),
        "nearest_depot_p90_km": pct_km(nearest_depot, 90),
        "nearest_depot_max_km": km(float(np.max(nearest_depot))),
        "nearest_station_p50_km": pct_km(nearest_station, 50),
        "nearest_station_p75_km": pct_km(nearest_station, 75),
        "nearest_station_p90_km": pct_km(nearest_station, 90),
        "nearest_station_max_km": km(float(np.max(nearest_station))),
        "nearest_customer_p50_km": pct_km(nearest_customer, 50),
        "nearest_customer_p90_km": pct_km(nearest_customer, 90),
        "pairwise_p50_km": pct_km(finite_pairs, 50),
        "pairwise_p90_km": pct_km(finite_pairs, 90),
        "pairwise_max_km": km(float(np.max(finite_pairs))),
        "depot_min_separation_km": km(depot_separation),
        "station_min_separation_km": km(station_separation),
        "roundtrip_depot_empty_kwh_p75": pct(roundtrip_empty_kwh, 75),
        "roundtrip_depot_empty_kwh_p90": pct(roundtrip_empty_kwh, 90),
        "roundtrip_depot_empty_kwh_max": float(np.max(roundtrip_empty_kwh)),
        "oneway_depot_empty_kwh_p90": pct(one_way_empty_kwh, 90),
        "customer_demand_mean": float(np.mean(demands)),
        "customer_demand_p90": pct(demands, 90),
        "time_window_width_mean_h": float(np.mean(tw_widths)) / 3600.0,
        "time_window_width_p25_h": pct(tw_widths, 25) / 3600.0,
        "service_time_mean_min": float(np.mean(service_times)) / 60.0,
        "manifest_num_cv": meta.get("num_cv", cfg.get("num_cv", "")),
        "manifest_num_ev": meta.get("num_ev", cfg.get("num_ev", "")),
        "station_strategy": cfg.get("station_strategy", ""),
        "depot_strategy": cfg.get("depot_strategy", ""),
    }


def join_winners_with_structure(winner_rows: list[dict[str, str]], instance_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_instance = {row["instance"]: row for row in instance_rows}
    joined: list[dict[str, Any]] = []
    for row in winner_rows:
        structure = by_instance.get(row["instance"])
        if not structure:
            continue
        merged: dict[str, Any] = dict(row)
        for key, value in structure.items():
            if key not in merged:
                merged[key] = value
            else:
                merged[f"structure_{key}"] = value
        share = float(row["winner_ev_route_share"])
        merged["route_share_in_practical_band"] = PRACTICAL_LOW <= share <= PRACTICAL_HIGH
        merged["route_share_regime"] = route_share_regime(share)
        manifest_ev = parse_float(merged.get("manifest_num_ev", "nan"))
        manifest_cv = parse_float(merged.get("manifest_num_cv", "nan"))
        merged["winner_ev_routes_over_manifest_ev"] = (
            float(row["winner_ev_route_count"]) > manifest_ev if not math.isnan(manifest_ev) else ""
        )
        merged["winner_cv_routes_over_manifest_cv"] = (
            float(row["winner_cv_route_count"]) > manifest_cv if not math.isnan(manifest_cv) else ""
        )
        joined.append(merged)
    return joined


def candidate_focus_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[float(row["battery_kwh"])].append(row)
    out: list[dict[str, Any]] = []
    for battery, group in sorted(groups.items()):
        shares = [float(row["winner_ev_route_share"]) for row in group]
        pass_count = sum(PRACTICAL_LOW <= share <= PRACTICAL_HIGH for share in shares)
        out.append(
            {
                "battery_kwh": battery,
                "rows_75_200": len(group),
                "pass_count_75_200": pass_count,
                "pass_rate_75_200": safe_div(pass_count, len(group)),
                "mean_ev_route_share": mean(shares),
                "min_ev_route_share": min(shares),
                "max_ev_route_share": max(shares),
                "all_cv_count": sum(row["winner_composition"] == "all_cv" for row in group),
                "all_ev_count": sum(row["winner_composition"] == "all_ev" for row in group),
                "ev_heavy_count": sum(row["winner_composition"] == "ev_heavy_mixed" for row in group),
                "balanced_count": sum(row["winner_composition"] == "balanced_mixed" for row in group),
                "cv_heavy_count": sum(row["winner_composition"] == "cv_heavy_mixed" for row in group),
                "rows_ev_routes_over_manifest_ev": sum(str(row["winner_ev_routes_over_manifest_ev"]) == "True" for row in group),
                "rows_cv_routes_over_manifest_cv": sum(str(row["winner_cv_routes_over_manifest_cv"]) == "True" for row in group),
            }
        )
    return out


def family_size_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[float, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(float(row["battery_kwh"]), row["category"], int(row["size"]))].append(row)
    out: list[dict[str, Any]] = []
    for (battery, family, size), group in sorted(groups.items()):
        shares = [float(row["winner_ev_route_share"]) for row in group]
        out.append(
            {
                "battery_kwh": battery,
                "family": family,
                "size": size,
                "winner_rows": len(group),
                "mean_ev_route_share": mean(shares),
                "pass_rate": mean([1.0 if PRACTICAL_LOW <= share <= PRACTICAL_HIGH else 0.0 for share in shares]),
                "route_share_regime": route_share_regime(mean(shares)),
                "mean_nearest_depot_p90_km": mean_float(group, "nearest_depot_p90_km"),
                "mean_nearest_station_p90_km": mean_float(group, "nearest_station_p90_km"),
                "mean_pairwise_p90_km": mean_float(group, "pairwise_p90_km"),
                "mean_station_per_customer": mean_float(group, "station_per_customer"),
            }
        )
    return out


def structure_by_family_size(instance_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in instance_rows:
        groups[(row["family"], int(row["size"]))].append(row)
    fields = [
        "station_per_customer",
        "depot_per_customer",
        "bbox_diag_km",
        "nearest_depot_p90_km",
        "nearest_station_p90_km",
        "nearest_customer_p50_km",
        "pairwise_p90_km",
        "roundtrip_depot_empty_kwh_p90",
        "roundtrip_depot_empty_kwh_max",
        "manifest_num_cv",
        "manifest_num_ev",
    ]
    out: list[dict[str, Any]] = []
    for (family, size), group in sorted(groups.items()):
        row: dict[str, Any] = {"family": family, "size": size, "replicates": len(group)}
        row["depots"] = mean_float(group, "depots")
        row["stations"] = mean_float(group, "stations")
        for field in fields:
            row[field] = mean_float(group, field)
        out.append(row)
    return out


def driver_correlations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = [
        "size",
        "station_per_customer",
        "depot_per_customer",
        "bbox_diag_km",
        "nearest_depot_p90_km",
        "nearest_station_p90_km",
        "nearest_customer_p50_km",
        "pairwise_p90_km",
        "roundtrip_depot_empty_kwh_p90",
    ]
    out: list[dict[str, Any]] = []
    for battery in sorted({float(row["battery_kwh"]) for row in rows}):
        group = [row for row in rows if abs(float(row["battery_kwh"]) - battery) < 1e-9]
        y = np.array([float(row["winner_ev_route_share"]) for row in group], dtype=float)
        for metric in metrics:
            x = np.array([float(row[metric]) for row in group], dtype=float)
            out.append(
                {
                    "battery_kwh": battery,
                    "metric": metric,
                    "n": len(group),
                    "pearson_with_ev_route_share": pearson(x, y),
                }
            )
    return out


def select_failure_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for battery in [81.0, 89.0, 100.0, 113.0, 123.9, 280.0]:
        group = [row for row in rows if abs(float(row["battery_kwh"]) - battery) < 1e-9]
        for row in sorted(group, key=lambda item: (abs(float(item["winner_ev_route_share"]) - 0.5), item["instance"]))[:4]:
            selected.append(example_row(row, "near_balanced"))
        for row in sorted(group, key=lambda item: (float(item["winner_ev_route_share"]), item["instance"]))[:3]:
            selected.append(example_row(row, "cv_side"))
        for row in sorted(group, key=lambda item: (-float(item["winner_ev_route_share"]), item["instance"]))[:3]:
            selected.append(example_row(row, "ev_side"))
    dedup: dict[tuple[str, float, str], dict[str, Any]] = {}
    for row in selected:
        dedup[(row["instance"], float(row["battery_kwh"]), row["example_type"])] = row
    return list(dedup.values())


def example_row(row: dict[str, Any], example_type: str) -> dict[str, Any]:
    fields = [
        "battery_kwh",
        "category",
        "size",
        "instance",
        "winner_ev_route_share",
        "winner_ev_customer_share",
        "winner_ev_demand_share",
        "winner_ev_distance_share",
        "winner_composition",
        "winner_variant",
        "nearest_depot_p90_km",
        "nearest_station_p90_km",
        "nearest_customer_p50_km",
        "pairwise_p90_km",
        "roundtrip_depot_empty_kwh_p90",
        "station_per_customer",
    ]
    return {"example_type": example_type, **{field: row[field] for field in fields}}


def write_report(
    instance_rows: list[dict[str, Any]],
    candidate_focus: list[dict[str, Any]],
    family_focus: list[dict[str, Any]],
    structure_summary: list[dict[str, Any]],
    correlations: list[dict[str, Any]],
    failure_examples: list[dict[str, Any]],
) -> None:
    best_focus = sorted(candidate_focus, key=lambda row: (-float(row["pass_rate_75_200"]), abs(float(row["mean_ev_route_share"]) - 0.5)))[:8]
    structure_focus = [row for row in structure_summary if int(row["size"]) >= FOCUS_MIN_SIZE]
    top_corr = sorted(correlations, key=lambda row: -abs(float(row["pearson_with_ev_route_share"])))[:12]

    lines = [
        "# 09m Structural Mixed-Band Investigation",
        "",
        "Status: read-only structural audit; no parameter/default/model semantics changed.",
        "",
        "## Plain-Language Verdict",
        "",
        (
            "The 75-200 customer range does not look like a single clean battery-capacity problem. "
            "Existing 09l screen rows show some near-balanced pockets, but failures alternate between "
            "CV-side collapse and EV-heavy collapse depending on family, size, and facility layout. "
            "The strongest next hypotheses are therefore operational/geographic: station/depot coverage, "
            "public-charging availability, route eligibility, and EV fleet/charger capacity limits."
        ),
        "",
        "## Scope",
        "",
        f"- Instance structure audited: {len(instance_rows)} / 69 E2 instances.",
        f"- Joined 09l Stage A rows restricted to {FOCUS_MIN_SIZE}-200 customers.",
        "- 09l rows are screen evidence only: `-01`, seed 1, eval_budget 1000. They rank hypotheses but do not certify a paper setting.",
        "",
        "## Best 75-200 Battery Pockets From Existing 09l Screen",
        "",
        "| battery | pass rows | pass rate | mean EV route share | min-max | counts |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for row in best_focus:
        lines.append(
            "| "
            f"{float(row['battery_kwh']):.1f} | "
            f"{int(row['pass_count_75_200'])}/{int(row['rows_75_200'])} | "
            f"{float(row['pass_rate_75_200']):.3f} | "
            f"{float(row['mean_ev_route_share']):.3f} | "
            f"{float(row['min_ev_route_share']):.3f}-{float(row['max_ev_route_share']):.3f} | "
            f"allCV={int(row['all_cv_count'])}, balanced={int(row['balanced_count'])}, EVheavy={int(row['ev_heavy_count'])}, allEV={int(row['all_ev_count'])}; "
            f"EVroutes>manifestEV={int(row['rows_ev_routes_over_manifest_ev'])} |"
        )

    lines.extend(
        [
            "",
            "## Geography And Facility Structure, 75-200",
            "",
            "| family | size | depots | stations | stations/customer | bbox km | depot p90 km | station p90 km | nearest-customer p50 km | pairwise p90 km |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in structure_focus:
        lines.append(
            "| "
            f"{row['family']} | {int(row['size'])} | "
            f"{float(row['depots']):.1f} | {float(row['stations']):.1f} | "
            f"{float(row['station_per_customer']):.3f} | "
            f"{float(row['bbox_diag_km']):.1f} | "
            f"{float(row['nearest_depot_p90_km']):.1f} | "
            f"{float(row['nearest_station_p90_km']):.1f} | "
            f"{float(row['nearest_customer_p50_km']):.1f} | "
            f"{float(row['pairwise_p90_km']):.1f} |"
        )

    lines.extend(
        [
            "",
            "## Critical Fleet-Count Finding",
            "",
            (
                "The current search/checker uses an unbounded fleet policy: `infer_fleet_limits()` returns "
                "1,000,000 CV/EV as a diagnostic default, and `check.py` explicitly says fleet count is no longer "
                "a hard feasibility cap. Existing instance metadata still records values such as `num_cv=10` and "
                "`num_ev=10`, but the optimizer can return dozens of EV routes. This is probably the cleanest "
                "operational explanation for the 280kWh EV-dominant result: modern EVs are cheap enough, and the "
                "model is effectively allowed to buy/use as many EV routes as fixed cost permits."
            ),
            "",
            (
                "This does not mean we should silently re-enable a hard cap. It means the next diagnostic should "
                "treat EV availability/capital budget as a first-class, source-backed scenario variable, then test "
                "whether realistic EV fleet limits keep 75-200 customer instances in the 20%-80% practical mixed band."
            ),
            "",
            "## Strongest Correlation Clues",
            "",
            "| battery | metric | n | Pearson vs EV route share |",
            "|---:|---|---:|---:|",
        ]
    )
    for row in top_corr:
        lines.append(
            f"| {float(row['battery_kwh']):.1f} | {row['metric']} | {int(row['n'])} | {float(row['pearson_with_ev_route_share']):.3f} |"
        )

    lines.extend(
        [
            "",
            "## What This Means",
            "",
            (
                "1. Size alone is not the right explanatory variable. The 75, 100, 150, and 200 groups "
                "share similar geographic envelopes, while customer density increases and station coverage improves as size grows."
            ),
            (
                "2. Some batteries create mixed pockets, but the same battery can be all-CV in one family-size cell "
                "and EV-heavy in another. That is exactly the pattern expected when geography/facility design or operational rules, "
                "not battery alone, is controlling the split."
            ),
            (
                "3. The next honest route is not to tune another unsupported battery value. The next gate should test "
                "source-backed operational mechanisms that can make CV and EV specialize naturally: charger capacity, "
                "public-station scarcity/eligibility, EV fleet-count or capital limits, and long-route EV eligibility."
            ),
            "",
            "## Next Hypotheses To Test",
            "",
            "| priority | hypothesis | why it is plausible | next check |",
            "|---:|---|---|---|",
            (
                "| 1 | EV fleet/capital limit | Current checker/search is unbounded while real fleets have finite EV stock; "
                "09h/09l EV-heavy solutions often use far more EV routes than `num_ev` metadata. | Evidence matrix for mixed-fleet papers and real fleet adoption ratios, then in-memory `SearchPolicy(max_ev=...)` gate. |"
            ),
            (
                "| 2 | Charger capacity / depot charging capacity | `check.py` enforces station slot capacity, but generated depots have very large charger counts; this may make overnight/depot charging too easy. | Audit actual charging concurrency and run source-backed depot/public charger-cap scenarios. |"
            ),
            (
                "| 3 | Public station availability and placement | Station/customer ratio stays about 0.105 and nearest-station p90 improves at larger sizes, which may push large cases EV-heavy. | In-memory station-scarcity or station-eligibility counterfactual, justified by infrastructure evidence. |"
            ),
            (
                "| 4 | Long-route EV eligibility | Cross-city route lengths may make some routes operationally unsuitable for EV despite theoretical charging feasibility. | Label route distance/duration bands and test EV-forbidden long-route policy as a diagnostic, not default. |"
            ),
            (
                "| 5 | Economic proxies | Public electricity price, occupancy fee, fixed cost, and depot electricity price can alter EV/CV tradeoffs. | Reuse 09f/09h fixed replay, then only reopt source-backed near-flips. |"
            ),
            "",
            "## Files",
            "",
            f"- `{OUTPUT_DIR / 'instance_structure.csv'}`",
            f"- `{OUTPUT_DIR / 'instance_structure_by_family_size.csv'}`",
            f"- `{OUTPUT_DIR / 'stage_a_75_200_joined.csv'}`",
            f"- `{OUTPUT_DIR / 'candidate_75_200_summary.csv'}`",
            f"- `{OUTPUT_DIR / 'family_size_75_200_summary.csv'}`",
            f"- `{OUTPUT_DIR / 'driver_correlations.csv'}`",
            f"- `{OUTPUT_DIR / 'failure_examples_75_200.csv'}`",
            f"- `{OUTPUT_DIR / 'metadata.json'}`",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def route_share_regime(share: float) -> str:
    if share <= 1e-9:
        return "all_cv"
    if share < PRACTICAL_LOW:
        return "cv_heavy"
    if share <= PRACTICAL_HIGH:
        return "practical_mixed"
    if share < 1.0 - 1e-9:
        return "ev_heavy"
    return "all_ev"


def count_station_at_depot(stations: np.ndarray, depots: np.ndarray) -> int:
    if len(stations) == 0 or len(depots) == 0:
        return 0
    distances = np.sqrt(((stations[:, None, :] - depots[None, :, :]) ** 2).sum(axis=2))
    return int(np.sum(np.min(distances, axis=1) < 1.0))


def pairwise_min_distance(coords: np.ndarray) -> float:
    if len(coords) < 2:
        return 0.0
    distances = np.sqrt(((coords[:, None, :] - coords[None, :, :]) ** 2).sum(axis=2))
    np.fill_diagonal(distances, np.inf)
    return float(np.min(distances))


def pct(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q))


def pct_km(values: np.ndarray, q: float) -> float:
    return km(pct(values, q))


def km(value_m: float) -> float:
    return float(value_m) / 1000.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def mean_float(rows: list[dict[str, Any]], key: str) -> float:
    return mean([float(row[key]) for row in rows])


def safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else float("nan")


def parse_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


if __name__ == "__main__":
    raise SystemExit(main())
