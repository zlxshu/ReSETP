from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

import build_three_shift_instance as base
from setp_instance_lab.config import ScenarioConfig
from setp_instance_lab.generator import generate_scenario
from setp_instance_lab.io import write_scenario_bundle
from setp_instance_lab.models import Node, Scenario
from setp_instance_lab.validation import validate_scenario


DEFAULT_TARGETS = (150, 200)
DEFAULT_CHILD_BASES = ("E-UK100_01", "E-UK100_02", "E-UK100_03")
DEFAULT_CHILD_SEEDS = (1, 2, 3)
DEFAULT_SHIFTS = (0.0, 9.0 * 3600.0, 18.0 * 3600.0)
MAX_ISOLATED_SHARE = 0.15


@dataclass(frozen=True)
class ScaleChildSpec:
    base_id: str
    seed: int
    shift_seconds: float
    n_customers: int
    merged_id: str

    @property
    def scenario_id(self) -> str:
        return f"{self.merged_id}__{self.base_id}_n{self.n_customers}_seed{self.seed}_24h_20251113"


@dataclass(frozen=True)
class CountPlan:
    target: int
    n_customers_by_child: tuple[int, int, int]
    predicted_kept_customer_count: int
    predicted_third_shift_kept: int
    exact_hit: bool
    trials: tuple[dict[str, Any], ...]


def choose_child_counts(
    target: int,
    kept_count_for_third_n: Callable[[int], int],
    *,
    max_child_n: int = 100,
    preferred_child_n: int | None = None,
) -> CountPlan:
    """Choose pre-merge child sizes; never delete customers after merging."""

    preferred = int(preferred_child_n or {150: 66, 200: 88}.get(int(target), max(1, round(int(target) / 2.27))))
    exact_candidates: list[tuple[tuple[float, int, int, int], tuple[int, int, int], int, dict[str, Any]]] = []
    nearest_candidates: list[tuple[tuple[float, int, int, int], tuple[int, int, int], int, dict[str, Any]]] = []
    trials: list[dict[str, Any]] = []
    for n3 in range(1, int(max_child_n) + 1):
        kept3 = int(kept_count_for_third_n(n3))
        needed_first_two = int(target) - kept3
        trial = {
            "n3": n3,
            "kept3": kept3,
            "needed_first_two_for_exact": needed_first_two,
            "feasible_exact_first_two": 2 <= needed_first_two <= 2 * int(max_child_n),
        }
        trials.append(trial)
        if 2 <= needed_first_two <= 2 * int(max_child_n):
            n1 = max(1, min(int(max_child_n), needed_first_two // 2))
            n2 = needed_first_two - n1
            if n2 > int(max_child_n):
                n2 = int(max_child_n)
                n1 = needed_first_two - n2
            if 1 <= n1 <= int(max_child_n) and 1 <= n2 <= int(max_child_n):
                score = (
                    abs(n1 - preferred) + abs(n2 - preferred) + abs(n3 - preferred),
                    abs(n1 - n2),
                    abs(n3 - preferred),
                    n3,
                )
                exact_candidates.append((score, (n1, n2, n3), target, trial))
        for n1 in (max(1, min(int(max_child_n), needed_first_two // 2)), preferred):
            n1 = max(1, min(int(max_child_n), int(n1)))
            n2 = max(1, min(int(max_child_n), int(target) - kept3 - n1))
            predicted = n1 + n2 + kept3
            score = (
                abs(predicted - int(target)) * 1_000.0 + abs(n1 - preferred) + abs(n2 - preferred) + abs(n3 - preferred),
                abs(n1 - n2),
                abs(n3 - preferred),
                n3,
            )
            nearest_candidates.append((score, (n1, n2, n3), predicted, trial))
    if exact_candidates:
        _, counts, predicted, _ = min(exact_candidates, key=lambda item: item[0])
        return CountPlan(int(target), counts, int(predicted), int(kept_count_for_third_n(counts[2])), True, tuple(trials))
    _, counts, predicted, _ = min(nearest_candidates, key=lambda item: item[0])
    return CountPlan(int(target), counts, int(predicted), int(kept_count_for_third_n(counts[2])), False, tuple(trials))


def build_scale_instances(
    targets: list[int],
    *,
    output_root: str | Path,
    report_dir: str | Path,
    max_child_n: int = 100,
) -> dict[str, Any]:
    output_root = Path(output_root)
    report_dir = Path(report_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for target in targets:
        plan = choose_child_counts(
            int(target),
            lambda n3: _third_shift_kept_count(int(n3)),
            max_child_n=max_child_n,
        )
        result = _build_one_target(int(target), plan, output_root)
        results.append(result)
        rows.append(result["instance_stats"])
        _write_json(report_dir / f"target_{target}_trial_plan.json", {
            "target": int(target),
            "n_customers_by_child": list(plan.n_customers_by_child),
            "predicted_kept_customer_count": plan.predicted_kept_customer_count,
            "predicted_third_shift_kept": plan.predicted_third_shift_kept,
            "exact_hit": plan.exact_hit,
            "trials": list(plan.trials),
        })
    manifest = {
        "schema_version": "setp-alns-scale-crush-generation.v1",
        "build_note": "Parameterized L-main three-shift build; final customer count is controlled before merge, not by post-hoc customer deletion.",
        "semantic_guards": [
            "Original build_three_shift_instance.py is not modified.",
            "No dynamic_events.tsv is generated.",
            "Post-merge customer deletion is forbidden except the L-main third-shift due_time > 86400 rule.",
        ],
        "carbon_anchor_utc": base.CARBON_ANCHOR_UTC,
        "carbon_source": str(base.CARBON_SOURCE),
        "horizon_seconds": base.HORIZON_SECONDS,
        "results": results,
    }
    _write_json(report_dir / "generation_manifest.json", manifest)
    _write_csv(report_dir / "instance_stats.csv", rows)
    (report_dir / "generation_report.md").write_text(_generation_report(manifest, rows), encoding="utf-8")
    return manifest


def _third_shift_kept_count(n_customers: int) -> int:
    spec = ScaleChildSpec(DEFAULT_CHILD_BASES[2], DEFAULT_CHILD_SEEDS[2], DEFAULT_SHIFTS[2], int(n_customers), "scale-count-probe")
    scenario = generate_scenario(_config(spec, cluster_std_ratio=0.12))
    return sum(
        1
        for customer in scenario.nodes
        if customer.node_type.lower() == "c"
        and float(customer.due_time) + float(spec.shift_seconds) <= base.HORIZON_SECONDS + 1e-9
    )


def _build_one_target(target: int, plan: CountPlan, output_root: Path) -> dict[str, Any]:
    merged_id = f"E-UK24h-三班-{target}"
    specs = tuple(
        ScaleChildSpec(base_id, seed, shift, n, merged_id)
        for base_id, seed, shift, n in zip(DEFAULT_CHILD_BASES, DEFAULT_CHILD_SEEDS, DEFAULT_SHIFTS, plan.n_customers_by_child, strict=True)
    )
    child_rows = _build_children(specs, output_root)
    merged_row = _build_merged(merged_id, child_rows, output_root)
    report = {
        "schema_version": "setp-scale-three-shift-build.v1",
        "requested_customer_count": int(target),
        "actual_customer_count": int(merged_row["manifest"]["kept_customer_count"]),
        "exact_hit": int(merged_row["manifest"]["kept_customer_count"]) == int(target),
        "count_plan": {
            "n_customers_by_child": list(plan.n_customers_by_child),
            "predicted_kept_customer_count": plan.predicted_kept_customer_count,
            "predicted_third_shift_kept": plan.predicted_third_shift_kept,
            "exact_hit": plan.exact_hit,
        },
        "carbon_anchor_utc": base.CARBON_ANCHOR_UTC,
        "horizon_seconds": base.HORIZON_SECONDS,
        "children": [_summary_child(row) for row in child_rows],
        "merged": merged_row["manifest"],
    }
    report_path = Path(merged_row["output_dir"]) / "three_shift_build_report.json"
    _write_json(report_path, report)
    base._attach_extra_file_to_manifest(Path(merged_row["output_dir"]), "three_shift_build_report_json", report_path)
    stats = _instance_stats(target, Path(merged_row["output_dir"]), merged_row["manifest"])
    return {
        "requested_customer_count": int(target),
        "actual_customer_count": int(merged_row["manifest"]["kept_customer_count"]),
        "exact_hit": int(merged_row["manifest"]["kept_customer_count"]) == int(target),
        "merged_id": merged_id,
        "output_dir": str(merged_row["output_dir"]),
        "child_counts": list(plan.n_customers_by_child),
        "instance_stats": stats,
    }


def _build_children(specs: tuple[ScaleChildSpec, ...], output_root: Path) -> list[dict[str, Any]]:
    first_scenario = generate_scenario(_config(specs[0], cluster_std_ratio=0.12))
    facility_layout = {node.node_id: node for node in first_scenario.nodes if node.node_type.lower() in {"d", "f"}}
    rows: list[dict[str, Any]] = []
    for spec in specs:
        scenario, config, adjustment = _generate_child_with_retries(spec, facility_layout)
        output_dir = output_root / spec.scenario_id
        _reset_output_dir(output_dir)
        payload = config.to_dict()
        payload.update(
            {
                "base_id": spec.base_id,
                "scale_target_child_n_customers": spec.n_customers,
                "u0_adjustment": adjustment,
                "facility_layout_source": specs[0].scenario_id,
                "facility_layout_policy": "reuse first shift depots/stations; regenerate distances before validation",
                "max_isolated_customer_share_for_u0": MAX_ISOLATED_SHARE,
            }
        )
        paths = write_scenario_bundle(scenario, output_dir, config=payload, export_dynamic=False)
        rows.append({"spec": spec, "config": config, "scenario": scenario, "output_dir": str(output_dir), "paths": paths, "adjustment": adjustment})
    return rows


def _generate_child_with_retries(
    spec: ScaleChildSpec,
    facility_layout: dict[str, Node],
) -> tuple[Scenario, ScenarioConfig, dict[str, Any]]:
    tried: list[dict[str, Any]] = []
    for cluster_std_ratio in (0.12, 0.08, 0.06):
        config = _config(spec, cluster_std_ratio=cluster_std_ratio)
        raw_scenario = generate_scenario(config)
        scenario = base._with_shared_facility_layout(raw_scenario, config, facility_layout)
        tried.append(
            {
                "cluster_std_ratio": cluster_std_ratio,
                "validation_passed": scenario.validation.get("passed"),
                "isolated_customer_share": scenario.validation.get("isolated_customer_share"),
            }
        )
        if scenario.validation.get("passed") and float(scenario.validation.get("isolated_customer_share", 1.0)) <= MAX_ISOLATED_SHARE:
            adjustment = {
                "reason": "scale build uses L-main U0 synthetic coordinates with empirical demand/time windows",
                "coord_mode": "synthetic",
                "demand_mode": "empirical",
                "time_window_mode": "empirical",
                "empirical_exact_base": False,
                "cluster_std_ratio": cluster_std_ratio,
                "tried": tried,
            }
            scenario.metadata.update({"u0_adjustment": adjustment})
            return scenario, config, adjustment
    raise RuntimeError(f"Scale U0 failed for {spec.base_id} n={spec.n_customers}: {tried}")


def _config(spec: ScaleChildSpec, *, cluster_std_ratio: float) -> ScenarioConfig:
    return ScenarioConfig(
        scenario_id=spec.scenario_id,
        seed=spec.seed,
        base_instance_path=str(base.RAW_ROOT / f"{spec.base_id}.txt"),
        n_depots=2,
        n_stations=3,
        n_customers=int(spec.n_customers),
        num_cv=10,
        num_ev=10,
        coord_mode="synthetic",
        demand_mode="empirical",
        time_window_mode="empirical",
        empirical_exact_base=False,
        cluster_std_ratio=cluster_std_ratio,
        max_isolated_customer_share=MAX_ISOLATED_SHARE,
        horizon_start=0.0,
        horizon_end=base.HORIZON_SECONDS,
        depot_due_time=base.HORIZON_SECONDS,
        carbon_alignment_mode="fixed_utc_anchor",
        carbon_time_anchor_utc=base.CARBON_ANCHOR_UTC,
        carbon_profile_path=str(base.CARBON_SOURCE),
    )


def _build_merged(merged_id: str, child_rows: list[dict[str, Any]], output_root: Path) -> dict[str, Any]:
    source_layout = {
        node.node_id: node
        for node in child_rows[0]["scenario"].nodes
        if node.node_type.lower() in {"d", "f"}
    }
    base._assert_facility_layouts_match(child_rows, source_layout)
    nodes: list[Node] = []
    for node_id in sorted((node_id for node_id in source_layout if node_id.startswith("D")), key=base._natural_key):
        nodes.append(replace(source_layout[node_id], ready_time=0.0, due_time=base.HORIZON_SECONDS, service_time=0.0))

    kept_customers: list[dict[str, Any]] = []
    deleted_customers: list[dict[str, Any]] = []
    customer_idx = 1
    for row in child_rows:
        spec: ScaleChildSpec = row["spec"]
        scenario: Scenario = row["scenario"]
        for customer in [node for node in scenario.nodes if node.node_type.lower() == "c"]:
            shifted_ready = float(customer.ready_time) + spec.shift_seconds
            shifted_due = float(customer.due_time) + spec.shift_seconds
            if spec.base_id == DEFAULT_CHILD_BASES[2] and shifted_due > base.HORIZON_SECONDS + 1e-9:
                deleted_customers.append(
                    {
                        "source_base_id": spec.base_id,
                        "source_scenario_id": spec.scenario_id,
                        "source_node_id": customer.node_id,
                        "shift_seconds": spec.shift_seconds,
                        "ready_time": customer.ready_time,
                        "due_time": customer.due_time,
                        "shifted_ready_time": shifted_ready,
                        "shifted_due_time": shifted_due,
                        "reason": "shifted_due_time_exceeds_24h",
                    }
                )
                continue
            new_id = f"C{customer_idx:03d}"
            nodes.append(Node(new_id, "c", customer.x, customer.y, customer.demand, shifted_ready, shifted_due, customer.service_time))
            kept_customers.append(
                {
                    "new_node_id": new_id,
                    "source_base_id": spec.base_id,
                    "source_scenario_id": spec.scenario_id,
                    "source_node_id": customer.node_id,
                    "shift_seconds": spec.shift_seconds,
                    "ready_time": customer.ready_time,
                    "due_time": customer.due_time,
                    "shifted_ready_time": shifted_ready,
                    "shifted_due_time": shifted_due,
                }
            )
            customer_idx += 1

    for node_id in sorted((node_id for node_id in source_layout if node_id.startswith("F")), key=base._natural_key):
        nodes.append(replace(source_layout[node_id], ready_time=0.0, due_time=base.HORIZON_SECONDS, service_time=0.0))

    matrix = base._distance_matrix(nodes)
    config = ScenarioConfig(
        scenario_id=merged_id,
        seed=20251113,
        n_depots=2,
        n_stations=3,
        n_customers=len(kept_customers),
        num_cv=10,
        num_ev=10,
        coord_mode="three_shift_merge",
        demand_mode="empirical",
        time_window_mode="empirical_shifted",
        max_isolated_customer_share=MAX_ISOLATED_SHARE,
        horizon_start=0.0,
        horizon_end=base.HORIZON_SECONDS,
        depot_due_time=base.HORIZON_SECONDS,
        carbon_alignment_mode="fixed_utc_anchor",
        carbon_time_anchor_utc=base.CARBON_ANCHOR_UTC,
        carbon_profile_path=str(base.CARBON_SOURCE),
    )
    validation = validate_scenario(nodes, matrix, config)
    manifest = {
        "name": merged_id,
        "build_note": "Scale three-shift 24h merge; customer windows are shifted only.",
        "source_children": [
            {
                "source_base_id": row["spec"].base_id,
                "scenario_id": row["spec"].scenario_id,
                "seed": row["spec"].seed,
                "shift_seconds": row["spec"].shift_seconds,
                "n_customers": row["spec"].n_customers,
                "output_dir": row["output_dir"],
                "validation": row["scenario"].validation,
            }
            for row in child_rows
        ],
        "facility_layout_source": child_rows[0]["spec"].scenario_id,
        "deleted_customers": deleted_customers,
        "deleted_customer_count": len(deleted_customers),
        "kept_customer_count": len(kept_customers),
        "total_demand": sum(float(node.demand) for node in nodes if node.node_type.lower() == "c"),
        "return_deadline_seconds": base.HORIZON_SECONDS,
        "b2_safe": base.HORIZON_SECONDS <= 86_400.0,
        "validation": validation,
    }
    scenario = Scenario(
        scenario_id=merged_id,
        seed=20251113,
        nodes=nodes,
        distance_matrix=matrix,
        depot_scores=child_rows[0]["scenario"].depot_scores,
        station_scores=child_rows[0]["scenario"].station_scores,
        metadata={
            "source": "scale_three_shift_merge",
            "three_shift_manifest": manifest,
            "num_cv": 10,
            "num_ev": 10,
            "carbon_time_anchor_utc": base.CARBON_ANCHOR_UTC,
        },
    )
    scenario.validation = validation
    output_dir = output_root / merged_id
    _reset_output_dir(output_dir)
    payload = config.to_dict()
    payload.update({"source": "scale_three_shift_merge", "three_shift_manifest": manifest})
    paths = write_scenario_bundle(scenario, output_dir, config=payload, export_dynamic=False)
    manifest_path = output_dir / "three_shift_manifest.json"
    manifest_with_customers = {**manifest, "kept_customers": kept_customers}
    _write_json(manifest_path, manifest_with_customers)
    base._attach_extra_file_to_manifest(output_dir, "three_shift_manifest_json", manifest_path)
    return {"scenario": scenario, "config": config, "output_dir": str(output_dir), "paths": paths, "manifest": {**manifest_with_customers, "output_dir": str(output_dir)}}


def _instance_stats(target: int, output_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    instance = json.loads((output_dir / "instance.json").read_text(encoding="utf-8"))
    node_rows = instance.get("nodes", [])
    customer_nodes = [node for node in node_rows if str(node.get("type", node.get("node_type", ""))).lower() == "c"]
    demand = [float(node.get("demand", 0.0)) for node in customer_nodes]
    widths = [float(node.get("due_time", 0.0)) - float(node.get("ready_time", 0.0)) for node in customer_nodes]
    shift_counts: dict[str, int] = {}
    for row in manifest.get("kept_customers", []):
        key = str(int(float(row.get("shift_seconds", 0.0)) // (9.0 * 3600.0)))
        shift_counts[key] = shift_counts.get(key, 0) + 1
    ffd = first_fit_decreasing_bin_count(demand, 1600.0)
    return {
        "instance": f"Scale-{target}",
        "bundle_dir": str(output_dir),
        "requested_customer_count": int(target),
        "actual_customer_count": int(manifest.get("kept_customer_count", len(demand))),
        "exact_hit": int(manifest.get("kept_customer_count", len(demand))) == int(target),
        "total_demand": sum(demand),
        "capacity_route_lower_bound": capacity_route_lower_bound(demand, 1600.0),
        "capacity_only_ffd_route_count": int(ffd["bin_count"]),
        "capacity_only_ffd_total_slack": float(ffd["total_slack"]),
        "deleted_customer_count": int(manifest.get("deleted_customer_count", 0)),
        "kept_by_shift": json.dumps(dict(sorted(shift_counts.items())), ensure_ascii=False),
        "tw_width_min_seconds": min(widths) if widths else 0.0,
        "tw_width_mean_seconds": sum(widths) / len(widths) if widths else 0.0,
        "tw_width_median_seconds": float(np.median(widths)) if widths else 0.0,
        "tw_width_max_seconds": max(widths) if widths else 0.0,
        "dynamic_events_tsv_exists": (output_dir / "dynamic_events.tsv").exists(),
        "three_shift_manifest": str(output_dir / "three_shift_manifest.json"),
    }


def capacity_route_lower_bound(demands: list[float], capacity: float) -> int:
    if capacity <= 0:
        raise ValueError("capacity must be positive")
    return int(math.ceil(sum(float(value) for value in demands) / float(capacity)))


def first_fit_decreasing_bin_count(demands: list[float], capacity: float) -> dict[str, Any]:
    if capacity <= 0:
        raise ValueError("capacity must be positive")
    loads: list[float] = []
    for demand in sorted((float(value) for value in demands), reverse=True):
        best_idx: int | None = None
        for idx, load in enumerate(loads):
            if load + demand <= capacity + 1e-9 and (best_idx is None or load > loads[best_idx]):
                best_idx = idx
        if best_idx is None:
            loads.append(demand)
        else:
            loads[best_idx] += demand
    total = sum(float(value) for value in demands)
    return {
        "bin_count": len(loads),
        "capacity": float(capacity),
        "total_demand": total,
        "total_slack": len(loads) * float(capacity) - total,
        "loads": loads,
    }


def _summary_child(row: dict[str, Any]) -> dict[str, Any]:
    spec: ScaleChildSpec = row["spec"]
    scenario: Scenario = row["scenario"]
    return {
        "source_base_id": spec.base_id,
        "scenario_id": spec.scenario_id,
        "seed": spec.seed,
        "shift_seconds": spec.shift_seconds,
        "n_customers": spec.n_customers,
        "output_dir": row["output_dir"],
        "validation": scenario.validation,
        "adjustment": row["adjustment"],
    }


def _generation_report(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# ALNS Scale Crush Generation",
        "",
        "Scale instances use the L-main three-shift static 24h construction. No dynamic event stream is generated.",
        "",
    ]
    for row in rows:
        lines.append(
            f"- {row['instance']}: requested={row['requested_customer_count']}, actual={row['actual_customer_count']}, "
            f"exact={row['exact_hit']}, demand={float(row['total_demand']):.3f}, "
            f"capacity_lb={row['capacity_route_lower_bound']}, ffd={row['capacity_only_ffd_route_count']}, "
            f"kept_by_shift={row['kept_by_shift']}, deleted={row['deleted_customer_count']}."
        )
    lines.extend(["", "Post-merge deletion to hit a target count was not used."])
    return "\n".join(lines)


def _reset_output_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _parse_targets(text: str) -> list[int]:
    return [int(part.strip()) for part in str(text).split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build scale three-shift SETP instances.")
    parser.add_argument("--targets", default=",".join(str(item) for item in DEFAULT_TARGETS))
    parser.add_argument("--output-root", default=str(base.OUTPUT_ROOT))
    parser.add_argument("--report-dir", default=str(base.REPO_ROOT / "solver/reports/alns_scale_crush/generation"))
    parser.add_argument("--max-child-n", type=int, default=100)
    args = parser.parse_args(argv)
    result = build_scale_instances(
        _parse_targets(args.targets),
        output_root=args.output_root,
        report_dir=args.report_dir,
        max_child_n=args.max_child_n,
    )
    print(f"GATE ALNS_SCALE_GENERATION {json.dumps({'manifest': str(Path(args.report_dir) / 'generation_manifest.json'), 'targets': _parse_targets(args.targets)}, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
