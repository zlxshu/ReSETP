#!/usr/bin/env python3
"""Formal middle-responsibility E3 comparison with sealed compatibility gates.

The formal contract is deliberately narrow: nine frozen networks, the three
frozen seeds, one deterministic middle-responsibility map per network, and two
search arms.  Both arms receive the same prepared start, seed and evaluation
budget.  The open arm keeps its raw search result and, separately, a selected
result that may fall back to the fixed-responsibility arm.  Existing geographic
and mixed evidence is read only and is never overwritten.

No claim of draw-by-draw random-number equality is made.  The operator menu is
part of the treatment and therefore differs when cross-depot moves are enabled.
The reproducible control is the same seed and staged seed-generation rule.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy  # noqa: E402
from baselines.e3_ablation.e3_common_fleet_envelope_design_20260713 import (  # noqa: E402
    deterministic_routes,
)
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy  # noqa: E402
from setp_solver.algorithms.resetp_alns.kernel.winner import (  # noqa: E402
    WinnerKernelConfig,
    run_tvci_alns,
)
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution  # noqa: E402
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations  # noqa: E402
from setp_solver.search.instance_registry import FORMAL_INSTANCE_ORDER  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402


FORMAL_OUT = ROOT / "baselines/e3_ablation/e3_medium_paired_cost_formal_20260715"
PROBE_ROOT = ROOT / "baselines/e3_ablation/e3_medium_paired_cost_preflight_20260715"
MEDIUM_ROOT = ROOT / "baselines/e3_ablation/e3_medium_ownership_diagnostic_20260715"
OLD_FORMAL_ROOT = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
OWNERSHIP_ROOT = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
ENVELOPE_ROOT = ROOT / "baselines/e3_ablation/e3_common_fleet_envelope_design_v3_20260713"

CONDITION = "medium"
FORMAL_SEEDS = (1, 2, 3)
FORMAL_EVAL_BUDGET = 4000
ARMS = (("ownership_fixed", False), ("reassignment_allowed", True))
ENDPOINT_PROBE_INSTANCE = FORMAL_INSTANCE_ORDER[0]
ENDPOINT_PROBE_SEED = 1
EPS = 1e-9

SOURCE_PATHS = (
    Path(__file__).resolve(),
    ROOT / "baselines/e3_ablation/e3_v3_runner.py",
    ROOT / "baselines/e3_ablation/e3_common_fleet_envelope_design_20260713.py",
    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/prices.py",
    ROOT / "solver/src/setp_solver/solution.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
    ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
)

METRIC_NAMES = (
    "cost_fix",
    "cost_km",
    "cost_fuel",
    "cost_elec",
    "cost_occ",
    "cost_transship",
    "cost_carbon",
    "total_cost",
    "distance_total",
    "electricity_kwh",
    "E_cv_direct",
    "E_ev_indirect",
    "E_total",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    """Atomically write JSON so an interrupted job cannot leave half a cache."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = fieldnames or ordered_fieldnames(rows) or ["status"]
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def ordered_fieldnames(rows: Iterable[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for name in row:
            if name not in seen:
                seen.add(name)
                result.append(name)
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def bool_from_csv(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def serialize_violations(violations: list[Any]) -> str:
    return json.dumps(
        [asdict(item) if hasattr(item, "__dataclass_fields__") else str(item) for item in violations],
        ensure_ascii=False,
        sort_keys=True,
    )


def load_envelopes() -> list[dict[str, Any]]:
    rows = read_csv(ENVELOPE_ROOT / "fleet_envelopes.csv")
    by_instance: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("status") != "PASS":
            raise RuntimeError(f"common fleet envelope is not sealed PASS: {row.get('instance')}")
        by_instance[row["instance"]] = {
            **row,
            "source_scale": int(row["source_scale"]),
            "common_cap_cv": int(row["common_cap_cv"]),
            "common_cap_ev": int(row["common_cap_ev"]),
            "common_depot_caps": json.loads(row["common_depot_caps_json"]),
        }
    missing = [instance for instance in FORMAL_INSTANCE_ORDER if instance not in by_instance]
    if missing:
        raise RuntimeError(f"fleet envelope misses formal networks: {missing}")
    return [by_instance[instance] for instance in FORMAL_INSTANCE_ORDER]


def load_owners(instance: str, condition: str = CONDITION) -> tuple[dict[str, str], Path]:
    if condition == CONDITION:
        path = MEDIUM_ROOT / "ownership_maps" / f"{instance}__medium.csv"
    else:
        path = OWNERSHIP_ROOT / "ownership_maps" / f"{instance}__{condition}.csv"
    rows = read_csv(path)
    owners = {row["customer_id"]: row["owner_depot_id"] for row in rows}
    if len(owners) != len(rows):
        raise RuntimeError(f"duplicate customer in owner map: {path}")
    return owners, path


def sealed_bundle_dir(instance: str) -> Path:
    path = OLD_FORMAL_ROOT / "assets" / instance / "bundle"
    required = ("instance.json", "distance_matrix.npy", "carbon_profile.csv", "scenario_manifest.json")
    if any(not (path / name).is_file() for name in required):
        raise RuntimeError(f"sealed formal bundle is incomplete: {instance}")
    return path


def bundle_hashes(instance: str) -> dict[str, str]:
    directory = sealed_bundle_dir(instance)
    return {name: sha256(directory / name) for name in (
        "instance.json", "distance_matrix.npy", "carbon_profile.csv", "scenario_manifest.json"
    )}


def verify_medium_freeze(instances: Iterable[str]) -> None:
    artifacts = read_json(MEDIUM_ROOT / "artifact_hashes.json")
    freeze_path = MEDIUM_ROOT / "medium_map_freeze.json"
    if artifacts.get("medium_map_freeze.json") != sha256(freeze_path):
        raise RuntimeError("medium-map freeze file drifted")
    freeze = read_json(freeze_path)
    frozen_hashes = freeze.get("maps", freeze.get("map_hashes", freeze.get("ownership_map_hashes", {})))
    for instance in instances:
        path = MEDIUM_ROOT / "ownership_maps" / f"{instance}__medium.csv"
        relative = str(path.relative_to(MEDIUM_ROOT))
        actual = sha256(path)
        expected_artifact = artifacts.get(relative)
        expected_freeze = frozen_hashes.get(relative) or frozen_hashes.get(path.name)
        if expected_artifact != actual or expected_freeze != actual:
            raise RuntimeError(f"medium owner map is not the frozen file: {instance}")


def source_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha256(path) for path in SOURCE_PATHS}


def input_hashes(instances: Iterable[str]) -> dict[str, str]:
    paths = [
        MEDIUM_ROOT / "medium_map_freeze.json",
        MEDIUM_ROOT / "decision.json",
        MEDIUM_ROOT / "artifact_hashes.json",
        MEDIUM_ROOT / "ownership_structure.csv",
        MEDIUM_ROOT / "fallback_preview.csv",
        OLD_FORMAL_ROOT / "metadata.json",
        OLD_FORMAL_ROOT / "raw_runs.csv",
        OLD_FORMAL_ROOT / "network_summary.csv",
        OLD_FORMAL_ROOT / "paired_results.csv",
        OLD_FORMAL_ROOT / "decision.json",
        OLD_FORMAL_ROOT / "artifact_hashes.json",
        ENVELOPE_ROOT / "fleet_envelopes.csv",
        ENVELOPE_ROOT / "decision.json",
    ]
    for instance in instances:
        paths.append(MEDIUM_ROOT / "ownership_maps" / f"{instance}__medium.csv")
        paths.extend(sealed_bundle_dir(instance) / name for name in (
            "instance.json", "distance_matrix.npy", "carbon_profile.csv", "scenario_manifest.json"
        ))
    return {str(path.relative_to(ROOT)): sha256(path) for path in paths}


def build_contract(
    *,
    mode: str,
    eval_budget: int,
    instances: list[str],
    seeds: list[int],
) -> dict[str, Any]:
    verify_medium_freeze(instances)
    sources = source_hashes()
    inputs = input_hashes(instances)
    contract = {
        "schema": "setp.e3.medium_paired_cost_formal.v1",
        "mode": mode,
        "condition": CONDITION,
        "instances": list(instances),
        "seeds": list(seeds),
        "arms": {label: allow for label, allow in ARMS},
        "expected_pairs": len(instances) * len(seeds),
        "expected_search_runs": len(instances) * len(seeds) * len(ARMS),
        "eval_budget_per_arm": int(eval_budget),
        "same_start": True,
        "same_seed": True,
        "same_staged_seed_rule": True,
        "draw_by_draw_random_number_equality_claimed": False,
        "randomness_boundary": "operator menus differ because cross-depot moves are the treatment",
        "open_result_rule": "report raw 4000-evaluation search and selected min(raw open, fixed final) separately",
        "fleet_limit_semantics": "sealed old-formal global cv/ev caps; per-depot counts are readouts only",
        "fairness_enabled": False,
        "carbon_weight": 0.0,
        "carbon_price": 0.0,
        "cross_site_fee": 0.0,
        "charging_strategy": "naive immediate-feasible",
        "source_hashes": sources,
        "input_hashes": inputs,
        "old_endpoint_source_commit": read_json(OLD_FORMAL_ROOT / "metadata.json")["source_commit"],
        "formal_compatibility_gates": [
            "current-code zero-search replay of all 108 sealed endpoint solutions",
            "deterministic current-code reproduction of one geographic and one mixed pair",
        ] if mode == "formal" else [],
        "result_direction_used_as_execution_gate": False,
    }
    contract["source_fingerprint_sha256"] = payload_sha256(sources)
    contract["input_fingerprint_sha256"] = payload_sha256(inputs)
    contract["contract_sha256"] = payload_sha256(contract)
    return contract


def ensure_metadata(out: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Verify the contract before creating or changing any output file."""

    path = out / "metadata.json"
    if path.exists():
        metadata = read_json(path)
        if metadata.get("contract_sha256") != contract["contract_sha256"]:
            raise RuntimeError("existing output contract differs; refusing to overwrite or resume")
        return metadata
    out.mkdir(parents=True, exist_ok=True)
    metadata = {
        **contract,
        "source_commit_at_creation": git_head(),
        "created_at_unix": time.time(),
        "statistical_unit": "base network; seeds are averaged within network before inference",
        "old_endpoint_direct_comparability": "pending formal compatibility gates" if contract["mode"] == "formal" else "not applicable to probe",
    }
    write_json(path, metadata)
    return metadata


def solution_fingerprint(solution: Solution) -> str:
    return payload_sha256(legacy.solution_to_dict(solution))


def context_for(bundle: Any, owners: dict[str, str], *, allow_cross: bool) -> EvaluationContext:
    return EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=legacy.prices_for("M1", 0.0),
        carbon_weight=0.0,
        fairness_enabled=False,
        customer_home_depot=owners,
        allow_cross_depot=allow_cross,
    )


def cross_service_stats(solution: Solution, bundle: Any, owners: dict[str, str]) -> dict[str, Any]:
    customers = {
        node.node_id: node
        for node in bundle.instance.nodes
        if str(node.node_type).lower() == "c"
    }
    served: dict[str, str] = {}
    duplicates: list[str] = []
    for route in solution.routes:
        for customer_id in route.node_sequence[1:-1]:
            if customer_id not in customers:
                continue
            if customer_id in served:
                duplicates.append(customer_id)
            served[customer_id] = route.home_depot_id
    missing = sorted(set(customers) - set(served))
    extra = sorted(set(served) - set(customers))
    actual = {
        customer_id: depot
        for customer_id, depot in served.items()
        if owners.get(customer_id) != depot
    }
    demand = sum(float(customers[customer_id].demand) for customer_id in actual)
    total_demand = sum(float(node.demand) for node in customers.values())
    return {
        "cross_site_customer_count": len(actual),
        "cross_site_customer_share": len(actual) / max(1, len(customers)),
        "cross_site_demand_kg": demand,
        "cross_site_demand_share": demand / total_demand if total_demand > 0.0 else 0.0,
        "cross_site_customer_ids_json": json.dumps(sorted(actual), ensure_ascii=False),
        "cross_site_service_map_json": json.dumps(actual, ensure_ascii=False, sort_keys=True),
        "coverage_missing_json": json.dumps(missing, ensure_ascii=False),
        "coverage_extra_json": json.dumps(extra, ensure_ascii=False),
        "duplicate_customer_ids_json": json.dumps(sorted(duplicates), ensure_ascii=False),
        "coverage_ok": not missing and not extra and not duplicates,
    }


def prepare_checked(
    solution: Solution,
    bundle: Any,
    owners: dict[str, str],
    *,
    allow_cross: bool,
) -> dict[str, Any]:
    annotated = legacy.annotate_cross_site(solution, owners)
    context = context_for(bundle, owners, allow_cross=allow_cross)
    with legacy.strict_mode():
        prepared, certificate = prepare_solution(annotated, context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None:
        raise RuntimeError("strict preparation returned no physical schedule certificate")
    metrics, closure_error = legacy._metric_row(prepared, bundle, legacy.prices_for("M1", 0.0))
    cross = cross_service_stats(prepared, bundle, owners)
    if not cross["coverage_ok"]:
        violations.append("customer coverage is incomplete or duplicated")
    return {
        "solution": prepared,
        "certificate": certificate,
        "violations": violations,
        "metrics": metrics,
        "cost_component_error": float(closure_error),
        "cross": cross,
        "certificate_stats": legacy._certificate_stats(certificate),
        "solution_fingerprint_sha256": solution_fingerprint(prepared),
        "certificate_fingerprint_sha256": payload_sha256(certificate.as_dict()),
    }


def choose_source(
    search_cost: float,
    fallback_cost: float,
    *,
    search_label: str = "search_candidate",
    fallback_label: str = "fallback_candidate",
) -> tuple[str, bool]:
    if float(search_cost) <= float(fallback_cost) + EPS:
        return search_label, False
    return fallback_label, True


def prepare_medium_start(instance: str, out: Path) -> dict[str, Any]:
    envelope = {row["instance"]: row for row in load_envelopes()}[instance]
    bundle_dir = sealed_bundle_dir(instance)
    bundle = load_search_bundle(bundle_dir)
    owners, owner_path = load_owners(instance)
    prices = legacy.prices_for("M1", 0.0)
    routes = deterministic_routes(bundle.instance, owners, prices)
    checked = prepare_checked(Solution(routes=routes), bundle, owners, allow_cross=False)
    violations = list(checked["violations"])
    if checked["cost_component_error"] > 1e-6:
        violations.append("cost components do not close")
    if checked["cross"]["cross_site_customer_count"] != 0:
        violations.append("medium fixed-responsibility start contains cross-depot service")
    caps_ok = (
        int(checked["certificate_stats"]["physical_cv"]) <= int(envelope["common_cap_cv"])
        and int(checked["certificate_stats"]["physical_ev"]) <= int(envelope["common_cap_ev"])
    )
    if not caps_ok:
        violations.append("medium start exceeds the sealed common global fleet cap")
    if violations:
        raise RuntimeError(f"medium start failed for {instance}: {serialize_violations(violations)}")

    asset_dir = out / "assets" / instance
    solution_path = asset_dir / "medium_common_start.json"
    certificate_path = asset_dir / "medium_common_start_certificate.json"
    write_json(solution_path, legacy.solution_to_dict(checked["solution"]))
    write_json(certificate_path, checked["certificate"].as_dict())
    bundle_fingerprint = bundle_hashes(instance)
    data_fingerprint = payload_sha256(
        {
            "ownership_sha256": sha256(owner_path),
            "bundle_hashes": bundle_fingerprint,
            "fleet_envelope_sha256": sha256(ENVELOPE_ROOT / "fleet_envelopes.csv"),
        }
    )
    meta = {
        "instance": instance,
        "condition": CONDITION,
        "status": "PASS",
        "ownership_path": str(owner_path.relative_to(ROOT)),
        "ownership_sha256": sha256(owner_path),
        "bundle_dir": str(bundle_dir.relative_to(ROOT)),
        "bundle_hashes": bundle_fingerprint,
        "data_fingerprint_sha256": data_fingerprint,
        "common_cap_cv": int(envelope["common_cap_cv"]),
        "common_cap_ev": int(envelope["common_cap_ev"]),
        "per_depot_caps_readout_only_json": json.dumps(envelope["common_depot_caps"], sort_keys=True),
        "start_solution_path": str(solution_path.relative_to(ROOT)),
        "start_solution_file_sha256": sha256(solution_path),
        "start_sha256": checked["solution_fingerprint_sha256"],
        "start_certificate_path": str(certificate_path.relative_to(ROOT)),
        "start_certificate_file_sha256": sha256(certificate_path),
        "start_certificate_sha256": checked["certificate_fingerprint_sha256"],
        "cost_component_error": checked["cost_component_error"],
        **checked["certificate_stats"],
        **checked["metrics"],
    }
    write_json(asset_dir / "medium_common_start_meta.json", meta)
    return meta


def prepare_medium_starts(instances: list[str], out: Path) -> list[dict[str, Any]]:
    rows = [prepare_medium_start(instance, out) for instance in instances]
    write_csv(out / "start_preflight.csv", rows)
    return rows


def build_pair_specs(
    instances: list[str],
    seeds: list[int],
    start_rows: list[dict[str, Any]],
    contract_sha256: str,
) -> list[dict[str, Any]]:
    starts = {row["instance"]: row for row in start_rows}
    return [
        {
            "pair_id": f"{instance}__medium__seed{seed}",
            "instance": instance,
            "condition": CONDITION,
            "seed": int(seed),
            "start_sha256": starts[instance]["start_sha256"],
            "start_certificate_sha256": starts[instance]["start_certificate_sha256"],
            "data_fingerprint_sha256": starts[instance]["data_fingerprint_sha256"],
            "contract_sha256": contract_sha256,
        }
        for instance in instances
        for seed in seeds
    ]


def write_task_manifest(out: Path, specs: list[dict[str, Any]], eval_budget: int) -> None:
    rows = [
        {
            **spec,
            "arm": arm,
            "allow_reassignment": allow,
            "eval_budget": int(eval_budget),
            "same_start_group": spec["pair_id"],
            "random_seed": int(spec["seed"]),
            "random_control": "same seed and staged seed rule; not draw-by-draw equality",
        }
        for spec in specs
        for arm, allow in ARMS
    ]
    write_csv(out / "task_manifest.csv", rows)


def old_artifact_verified(relative: str, artifact_hashes: dict[str, str]) -> Path:
    path = OLD_FORMAL_ROOT / relative
    expected = artifact_hashes.get(relative)
    if expected is None or not path.is_file() or sha256(path) != expected:
        raise RuntimeError(f"sealed old formal artifact is missing or drifted: {relative}")
    return path


def float_equal(left: float, right: float, tolerance: float = 1e-7) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def replay_old_endpoint_solutions(out: Path) -> dict[str, Any]:
    """Re-evaluate all 108 sealed endpoint solutions with the current referee."""

    raw_path = OLD_FORMAL_ROOT / "raw_runs.csv"
    artifact_hashes = read_json(OLD_FORMAL_ROOT / "artifact_hashes.json")
    old_artifact_verified("raw_runs.csv", artifact_hashes)
    raw_rows = read_csv(raw_path)
    replay_rows: list[dict[str, Any]] = []
    for old in raw_rows:
        run_id = old["run_id"]
        instance = old["instance"]
        condition = old["condition"]
        owners, owner_path = load_owners(instance, condition)
        bundle = load_search_bundle(sealed_bundle_dir(instance))
        solution_relative = f"solutions/{run_id}.json"
        certificate_relative = f"certificates/{run_id}.json"
        solution_path = old_artifact_verified(solution_relative, artifact_hashes)
        certificate_path = old_artifact_verified(certificate_relative, artifact_hashes)
        old_solution_payload = read_json(solution_path)
        old_certificate_payload = read_json(certificate_path)
        checked = prepare_checked(
            legacy.solution_from_dict(old_solution_payload),
            bundle,
            owners,
            allow_cross=bool_from_csv(old["allow_reassignment"]),
        )
        metric_diffs = {
            name: float(checked["metrics"][name]) - float(old[name])
            for name in METRIC_NAMES
            if name in old and old[name] != ""
        }
        stats_diffs: dict[str, float] = {}
        for name in (
            "physical_cv", "physical_ev", "physical_total", "trip_count",
            "vehicle_work_hours", "between_trip_gap_hours", "max_trips_per_vehicle",
        ):
            if name in old and old[name] != "":
                stats_diffs[name] = float(checked["certificate_stats"][name]) - float(old[name])
        certificate_exact = checked["certificate_fingerprint_sha256"] == payload_sha256(old_certificate_payload)
        solution_exact = checked["solution_fingerprint_sha256"] == payload_sha256(old_solution_payload)
        pass_row = (
            not checked["violations"]
            and checked["cost_component_error"] <= 1e-6
            and all(float_equal(value, 0.0) for value in metric_diffs.values())
            and all(float_equal(value, 0.0) for value in stats_diffs.values())
            and certificate_exact
            and solution_exact
            and sha256(owner_path) == old["ownership_sha256"]
        )
        replay_rows.append(
            {
                "run_id": run_id,
                "instance": instance,
                "condition": condition,
                "seed": int(old["seed"]),
                "arm": old["arm"],
                "status": "PASS" if pass_row else "HALT",
                "solution_payload_exact": solution_exact,
                "certificate_payload_exact": certificate_exact,
                "metric_max_abs_diff": max((abs(value) for value in metric_diffs.values()), default=0.0),
                "certificate_stat_max_abs_diff": max((abs(value) for value in stats_diffs.values()), default=0.0),
                "cost_component_error": checked["cost_component_error"],
                "violation_count": len(checked["violations"]),
                "violations_json": serialize_violations(checked["violations"]),
                "metric_diffs_json": json.dumps(metric_diffs, sort_keys=True),
                "certificate_stat_diffs_json": json.dumps(stats_diffs, sort_keys=True),
            }
        )
    write_csv(out / "compatibility" / "old_solution_replay.csv", replay_rows)
    passed = sum(row["status"] == "PASS" for row in replay_rows)
    decision = {
        "status": "PASS" if len(replay_rows) == passed == 108 else "HALT",
        "expected_solution_count": 108,
        "replayed_solution_count": len(replay_rows),
        "passed_solution_count": passed,
        "search_executed": False,
        "claim": "current-code costs, schedules and saved solutions are unchanged" if passed == 108 else "old endpoints are not directly reusable",
    }
    write_json(out / "compatibility" / "old_solution_replay_decision.json", decision)
    return decision


def search_candidate(
    *,
    bundle_dir: Path,
    owners: dict[str, str],
    start: Solution,
    seed: int,
    eval_budget: int,
    allow_cross: bool,
) -> dict[str, Any]:
    bundle = load_search_bundle(bundle_dir)
    prices = legacy.prices_for("M1", 0.0)
    started = time.perf_counter()
    with legacy.strict_mode():
        result = run_tvci_alns(
            bundle_dir,
            config=WinnerKernelConfig(
                seed=int(seed),
                eval_budget=int(eval_budget),
                max_runtime_seconds=max(600.0, float(eval_budget) * 0.5),
                require_charging_signal=False,
            ),
            initial_solution=start,
            prices=prices,
            charging_strategy="naive",
            policy=SearchPolicy(
                require_charging_signal=False,
                max_cv=int(bundle.instance.num_cv or 0),
                max_ev=int(bundle.instance.num_ev or 0),
                allow_cross_depot=allow_cross,
                enable_cross_depot_operator=True,
            ),
            carbon_weight=0.0,
            fairness_enabled=False,
            customer_home_depot=owners,
        )
    checked = prepare_checked(result["best_solution"], bundle, owners, allow_cross=allow_cross)
    return {
        "checked": checked,
        "evaluations": int(result.get("evaluations", -1)),
        "elapsed_seconds": time.perf_counter() - started,
        "score_counts": legacy.score_counts(result),
        "history_initial_cost": (
            float(result["history"][0].get("best_cost", result["history"][0].get("objective")))
            if isinstance(result.get("history"), list) and result["history"]
            and isinstance(result["history"][0], dict)
            and result["history"][0].get("best_cost", result["history"][0].get("objective")) is not None
            else None
        ),
    }


def run_endpoint_reproduction_probes(out: Path, eval_budget: int = FORMAL_EVAL_BUDGET) -> dict[str, Any]:
    """Re-run one complete old pair at each endpoint before joining three points."""

    if eval_budget != FORMAL_EVAL_BUDGET:
        raise RuntimeError("endpoint reproduction must use the sealed 4000-evaluation budget")
    old_rows = {row["run_id"]: row for row in read_csv(OLD_FORMAL_ROOT / "raw_runs.csv")}
    probe_rows: list[dict[str, Any]] = []
    instance = ENDPOINT_PROBE_INSTANCE
    for condition in ("geographic", "mixed"):
        owners, _ = load_owners(instance, condition)
        start_path = OLD_FORMAL_ROOT / "assets" / instance / f"{condition}__common_start.json"
        start_payload = read_json(start_path)
        start = legacy.solution_from_dict(start_payload)
        start_hash = payload_sha256(start_payload)
        for arm, allow_cross in ARMS:
            expected_id = f"{instance}__{condition}__seed{ENDPOINT_PROBE_SEED}__{arm}"
            expected = old_rows[expected_id]
            result = search_candidate(
                bundle_dir=sealed_bundle_dir(instance),
                owners=owners,
                start=legacy.solution_from_dict(start_payload),
                seed=ENDPOINT_PROBE_SEED,
                eval_budget=eval_budget,
                allow_cross=allow_cross,
            )
            checked = result["checked"]
            metric_diffs = {name: float(checked["metrics"][name]) - float(expected[name]) for name in METRIC_NAMES}
            solution_exact = checked["solution_fingerprint_sha256"] == payload_sha256(
                read_json(OLD_FORMAL_ROOT / "solutions" / f"{expected_id}.json")
            )
            pass_row = (
                result["evaluations"] == eval_budget
                and not checked["violations"]
                and checked["cost_component_error"] <= 1e-6
                and all(float_equal(value, 0.0) for value in metric_diffs.values())
                and solution_exact
                and start_hash == expected["start_sha256"]
            )
            solution_path = out / "compatibility" / "endpoint_probe_solutions" / f"{expected_id}.json"
            certificate_path = out / "compatibility" / "endpoint_probe_certificates" / f"{expected_id}.json"
            write_json(solution_path, legacy.solution_to_dict(checked["solution"]))
            write_json(certificate_path, checked["certificate"].as_dict())
            probe_rows.append(
                {
                    "run_id": expected_id,
                    "instance": instance,
                    "condition": condition,
                    "seed": ENDPOINT_PROBE_SEED,
                    "arm": arm,
                    "status": "PASS" if pass_row else "HALT",
                    "evaluations": result["evaluations"],
                    "expected_evaluations": eval_budget,
                    "start_sha256": start_hash,
                    "expected_start_sha256": expected["start_sha256"],
                    "solution_payload_exact": solution_exact,
                    "metric_max_abs_diff": max(abs(value) for value in metric_diffs.values()),
                    "metric_diffs_json": json.dumps(metric_diffs, sort_keys=True),
                    "violation_count": len(checked["violations"]),
                    "cost_component_error": checked["cost_component_error"],
                    "solution_path": str(solution_path.relative_to(ROOT)),
                    "solution_file_sha256": sha256(solution_path),
                    "certificate_path": str(certificate_path.relative_to(ROOT)),
                    "certificate_file_sha256": sha256(certificate_path),
                }
            )
    write_csv(out / "compatibility" / "endpoint_reproduction_probe.csv", probe_rows)
    passed = sum(row["status"] == "PASS" for row in probe_rows)
    decision = {
        "status": "PASS" if len(probe_rows) == passed == 4 else "HALT",
        "instance": instance,
        "seed": ENDPOINT_PROBE_SEED,
        "conditions": ["geographic", "mixed"],
        "expected_search_runs": 4,
        "completed_search_runs": len(probe_rows),
        "passed_search_runs": passed,
        "eval_budget_per_arm": eval_budget,
    }
    write_json(out / "compatibility" / "endpoint_reproduction_decision.json", decision)
    return decision


def load_endpoint_reproduction_decision(out: Path) -> dict[str, Any]:
    path = out / "compatibility" / "endpoint_reproduction_decision.json"
    if not path.is_file():
        return {"status": "MISSING"}
    decision = read_json(path)
    rows_path = out / "compatibility" / "endpoint_reproduction_probe.csv"
    if not rows_path.is_file() or len(read_csv(rows_path)) != 4:
        return {"status": "HALT", "reason": "endpoint probe evidence is incomplete"}
    return decision


def save_checked(
    out: Path,
    run_id: str,
    role: str,
    checked: dict[str, Any],
) -> dict[str, str]:
    solution_path = out / "solutions" / f"{run_id}__{role}.json"
    certificate_path = out / "certificates" / f"{run_id}__{role}.json"
    write_json(solution_path, legacy.solution_to_dict(checked["solution"]))
    write_json(certificate_path, checked["certificate"].as_dict())
    return {
        f"{role}_solution_path": str(solution_path.relative_to(ROOT)),
        f"{role}_solution_file_sha256": sha256(solution_path),
        f"{role}_solution_fingerprint_sha256": checked["solution_fingerprint_sha256"],
        f"{role}_certificate_path": str(certificate_path.relative_to(ROOT)),
        f"{role}_certificate_file_sha256": sha256(certificate_path),
        f"{role}_certificate_fingerprint_sha256": checked["certificate_fingerprint_sha256"],
    }


def arm_row(
    *,
    out: Path,
    spec: dict[str, Any],
    arm: str,
    allow_cross: bool,
    eval_budget: int,
    search_result: dict[str, Any],
    final_checked: dict[str, Any],
    selected_source: str,
    fallback_used: bool,
    start_meta: dict[str, Any],
    source_fingerprint_sha256: str,
) -> dict[str, Any]:
    search_checked = search_result["checked"]
    run_id = f"{spec['pair_id']}__{arm}"
    search_paths = save_checked(out, run_id, "raw_search", search_checked)
    final_paths = save_checked(out, run_id, "selected_final", final_checked)
    counts = search_result["score_counts"]
    violations = list(final_checked["violations"])
    if final_checked["cost_component_error"] > 1e-6:
        violations.append("selected cost components do not close")
    if search_checked["cost_component_error"] > 1e-6:
        violations.append("raw search cost components do not close")
    if search_result["evaluations"] != eval_budget:
        violations.append("search did not consume the exact frozen evaluation budget")
    history_initial = search_result.get("history_initial_cost")
    if history_initial is not None and not float_equal(history_initial, float(start_meta["total_cost"]), 1e-6):
        violations.append("search history did not begin at the shared start cost")
    if arm == "ownership_fixed" and final_checked["cross"]["cross_site_customer_count"] != 0:
        violations.append("fixed-responsibility final solution crosses depots")
    status = "PASS" if not violations else "HALT"
    row: dict[str, Any] = {
        "run_id": run_id,
        "pair_id": spec["pair_id"],
        "instance": spec["instance"],
        "condition": CONDITION,
        "seed": int(spec["seed"]),
        "arm": arm,
        "allow_reassignment": allow_cross,
        "status": status,
        "contract_sha256": spec["contract_sha256"],
        "source_fingerprint_sha256": source_fingerprint_sha256,
        "data_fingerprint_sha256": spec["data_fingerprint_sha256"],
        "ownership_sha256": start_meta["ownership_sha256"],
        "bundle_hashes_json": json.dumps(start_meta["bundle_hashes"], sort_keys=True),
        "same_start_group": spec["pair_id"],
        "start_sha256": spec["start_sha256"],
        "start_certificate_sha256": spec["start_certificate_sha256"],
        "start_cost": float(start_meta["total_cost"]),
        "history_initial_cost": history_initial if history_initial is not None else "",
        "random_seed": int(spec["seed"]),
        "random_control": "same seed and staged seed rule; operator menus may differ",
        "budget": int(eval_budget),
        "evaluations": int(search_result["evaluations"]),
        "elapsed_seconds": float(search_result["elapsed_seconds"]),
        "selected_source": selected_source,
        "fallback_used": fallback_used,
        "violation_count": len(violations),
        "violations_json": serialize_violations(violations),
        "cost_component_error": float(final_checked["cost_component_error"]),
        "raw_search_cost_component_error": float(search_checked["cost_component_error"]),
        "raw_search_violation_count": len(search_checked["violations"]),
        "raw_search_violations_json": serialize_violations(search_checked["violations"]),
        "cross_site_complete_candidates": int(counts.get("cross_site_complete_candidates", 0)),
        "cross_site_legal_candidates": int(counts.get("cross_site_legal_candidates", 0)),
        "cross_site_accepted_candidates": int(counts.get("cross_site_accepted_candidates", 0)),
        **search_paths,
        **final_paths,
        **final_checked["cross"],
        **final_checked["certificate_stats"],
        **final_checked["metrics"],
    }
    for name, value in search_checked["metrics"].items():
        row[f"raw_search_{name}"] = value
    for name, value in search_checked["cross"].items():
        row[f"raw_search_{name}"] = value
    for name, value in search_checked["certificate_stats"].items():
        row[f"raw_search_{name}"] = value
    return row


def referenced_file_ok(row: dict[str, Any], prefix: str) -> bool:
    try:
        for kind in ("solution", "certificate"):
            path = ROOT / row[f"{prefix}_{kind}_path"]
            if not path.is_file() or sha256(path) != row[f"{prefix}_{kind}_file_sha256"]:
                return False
            if payload_sha256(read_json(path)) != row[f"{prefix}_{kind}_fingerprint_sha256"]:
                return False
    except (KeyError, OSError, json.JSONDecodeError):
        return False
    return True


def validate_pair_payload(
    payload: dict[str, Any],
    spec: dict[str, Any],
    eval_budget: int,
) -> tuple[bool, str]:
    if payload.get("contract_sha256") != spec["contract_sha256"]:
        return False, "contract mismatch"
    if payload.get("pair_id") != spec["pair_id"] or payload.get("pair_status") != "PASS":
        return False, "pair identity/status mismatch"
    rows = payload.get("rows", [])
    if len(rows) != 2 or {row.get("arm") for row in rows} != {arm for arm, _ in ARMS}:
        return False, "pair does not contain exactly two arms"
    for row in rows:
        if (
            row.get("status") != "PASS"
            or int(row.get("evaluations", -1)) != int(eval_budget)
            or int(row.get("budget", -1)) != int(eval_budget)
            or row.get("start_sha256") != spec["start_sha256"]
            or row.get("start_certificate_sha256") != spec["start_certificate_sha256"]
            or row.get("ownership_sha256") is None
            or float(row.get("cost_component_error", math.inf)) > 1e-6
            or int(row.get("violation_count", -1)) != 0
            or not referenced_file_ok(row, "raw_search")
            or not referenced_file_ok(row, "selected_final")
        ):
            return False, f"arm evidence failed integrity: {row.get('arm')}"
    indexed = {row["arm"]: row for row in rows}
    fixed = indexed["ownership_fixed"]
    opened = indexed["reassignment_allowed"]
    if int(fixed["cross_site_customer_count"]) != 0:
        return False, "fixed arm crosses depots"
    if float(opened["total_cost"]) > float(fixed["total_cost"]) + EPS:
        return False, "selected open result is worse than fixed final"
    return True, "PASS"


def run_pair(
    spec: dict[str, Any],
    *,
    out_text: str,
    eval_budget: int,
    source_fingerprint_sha256: str,
) -> dict[str, Any]:
    out = Path(out_text)
    pair_path = out / "pairs" / f"{spec['pair_id']}.json"
    if pair_path.exists():
        try:
            cached = read_json(pair_path)
        except (OSError, json.JSONDecodeError) as exc:
            cached = {}
            reason = f"cache JSON cannot be read: {type(exc).__name__}: {exc}"
        else:
            valid, reason = validate_pair_payload(cached, spec, eval_budget)
            if valid:
                return cached
        issue = {
            "pair_id": spec["pair_id"],
            "contract_sha256": spec["contract_sha256"],
            "pair_status": "HALT",
            "reason": f"CACHE_INTEGRITY_FAILURE: {reason}",
            "rows": [],
        }
        write_json(out / "cache_integrity_failures" / f"{spec['pair_id']}.json", issue)
        return issue

    try:
        instance = spec["instance"]
        bundle_dir = sealed_bundle_dir(instance)
        bundle = load_search_bundle(bundle_dir)
        owners, _ = load_owners(instance)
        start_meta = read_json(out / "assets" / instance / "medium_common_start_meta.json")
        start_payload = read_json(out / "assets" / instance / "medium_common_start.json")
        if payload_sha256(start_payload) != spec["start_sha256"]:
            raise RuntimeError("shared start file fingerprint differs from manifest")
        if start_meta["start_certificate_sha256"] != spec["start_certificate_sha256"]:
            raise RuntimeError("shared start certificate fingerprint differs from manifest")
        start_fixed = prepare_checked(
            legacy.solution_from_dict(start_payload), bundle, owners, allow_cross=False
        )
        start_open = prepare_checked(
            legacy.solution_from_dict(start_payload), bundle, owners, allow_cross=True
        )
        if (
            start_fixed["solution_fingerprint_sha256"] != start_open["solution_fingerprint_sha256"]
            or start_fixed["certificate_fingerprint_sha256"] != start_open["certificate_fingerprint_sha256"]
            or not float_equal(start_fixed["metrics"]["total_cost"], start_open["metrics"]["total_cost"])
            or start_fixed["violations"]
            or start_open["violations"]
        ):
            raise RuntimeError("two arms do not see the same legal prepared start")

        fixed_search = search_candidate(
            bundle_dir=bundle_dir,
            owners=owners,
            start=legacy.solution_from_dict(start_payload),
            seed=int(spec["seed"]),
            eval_budget=eval_budget,
            allow_cross=False,
        )
        fixed_source, fixed_fallback = choose_source(
            float(fixed_search["checked"]["metrics"]["total_cost"]),
            float(start_fixed["metrics"]["total_cost"]),
            fallback_label="shared_start",
        )
        fixed_final = fixed_search["checked"] if not fixed_fallback else start_fixed

        open_search = search_candidate(
            bundle_dir=bundle_dir,
            owners=owners,
            start=legacy.solution_from_dict(start_payload),
            seed=int(spec["seed"]),
            eval_budget=eval_budget,
            allow_cross=True,
        )
        fixed_final_open = prepare_checked(fixed_final["solution"], bundle, owners, allow_cross=True)
        if (
            fixed_final_open["violations"]
            or not float_equal(
                fixed_final_open["metrics"]["total_cost"], fixed_final["metrics"]["total_cost"], 1e-7
            )
        ):
            raise RuntimeError("fixed final is not a legal cost-preserving fallback under the open rule")
        open_source, open_fallback = choose_source(
            float(open_search["checked"]["metrics"]["total_cost"]),
            float(fixed_final_open["metrics"]["total_cost"]),
            fallback_label="ownership_fixed_final",
        )
        open_final = open_search["checked"] if not open_fallback else fixed_final_open

        rows = [
            arm_row(
                out=out,
                spec=spec,
                arm="ownership_fixed",
                allow_cross=False,
                eval_budget=eval_budget,
                search_result=fixed_search,
                final_checked=fixed_final,
                selected_source=fixed_source,
                fallback_used=fixed_fallback,
                start_meta=start_meta,
                source_fingerprint_sha256=source_fingerprint_sha256,
            ),
            arm_row(
                out=out,
                spec=spec,
                arm="reassignment_allowed",
                allow_cross=True,
                eval_budget=eval_budget,
                search_result=open_search,
                final_checked=open_final,
                selected_source=open_source,
                fallback_used=open_fallback,
                start_meta=start_meta,
                source_fingerprint_sha256=source_fingerprint_sha256,
            ),
        ]
        payload = {
            "pair_id": spec["pair_id"],
            "contract_sha256": spec["contract_sha256"],
            "pair_status": "PASS" if all(row["status"] == "PASS" for row in rows) else "HALT",
            "raw_open_and_selected_open_reported_separately": True,
            "rows": rows,
        }
        valid, reason = validate_pair_payload(payload, spec, eval_budget)
        if not valid:
            payload["pair_status"] = "HALT"
            payload["reason"] = reason
    except Exception as exc:  # pair-level stop surface, preserved for diagnosis
        payload = {
            "pair_id": spec["pair_id"],
            "contract_sha256": spec["contract_sha256"],
            "pair_status": "HALT",
            "reason": f"{type(exc).__name__}: {exc}",
            "rows": [],
        }
    write_json(pair_path, payload)
    return payload


def exact_two_sided_sign_p(positive: int, negative: int) -> float:
    n = int(positive) + int(negative)
    if n == 0:
        return 1.0
    lower = min(int(positive), int(negative))
    tail = sum(math.comb(n, k) for k in range(lower + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values) / len(values)


def old_endpoint_network_rows() -> dict[str, dict[str, float]]:
    observed = read_csv(OLD_FORMAL_ROOT / "network_summary.csv")
    fallback = read_csv(MEDIUM_ROOT / "fallback_preview.csv")
    result: dict[str, dict[str, float]] = {}
    for instance in FORMAL_INSTANCE_ORDER:
        row: dict[str, float] = {}
        for condition in ("geographic", "mixed"):
            matches = [
                item for item in observed
                if item["instance"] == instance and item["condition"] == condition
            ]
            if len(matches) != 1:
                raise RuntimeError(f"old endpoint network summary incomplete: {instance}/{condition}")
            row[f"{condition}_observed_saving_pct"] = float(matches[0]["mean_saving_pct"])
            fallback_values = [
                float(item["fallback_preview_saving_pct"])
                for item in fallback
                if item["instance"] == instance and item["condition"] == condition
            ]
            if len(fallback_values) != 3:
                raise RuntimeError(f"old endpoint fallback preview incomplete: {instance}/{condition}")
            row[f"{condition}_fallback_saving_pct"] = mean(fallback_values)
        result[instance] = row
    old_decision = read_json(OLD_FORMAL_ROOT / "decision.json")
    geo_observed = mean([row["geographic_observed_saving_pct"] for row in result.values()])
    mixed_observed = mean([row["mixed_observed_saving_pct"] for row in result.values()])
    if not float_equal(geo_observed, float(old_decision["geographic_mean_saving_pct"]), 1e-10):
        raise RuntimeError("old geographic headline cannot be reconstructed")
    if not float_equal(mixed_observed, float(old_decision["mixed_mean_saving_pct"]), 1e-10):
        raise RuntimeError("old mixed headline cannot be reconstructed")
    return result


def mismatch_by_network() -> dict[str, dict[str, float]]:
    rows = read_csv(MEDIUM_ROOT / "ownership_structure.csv")
    result: dict[str, dict[str, float]] = {}
    for instance in FORMAL_INSTANCE_ORDER:
        selected = {
            row["condition"]: float(row["responsibility_mismatch_index"])
            for row in rows
            if row["instance"] == instance and row["condition"] in {"geographic", "medium", "mixed"}
        }
        if set(selected) != {"geographic", "medium", "mixed"}:
            raise RuntimeError(f"mismatch index incomplete: {instance}")
        if not (abs(selected["geographic"]) <= 1e-12 < selected["medium"] < selected["mixed"]):
            raise RuntimeError(f"mismatch index order invalid: {instance}")
        result[instance] = selected
    return result


def ols_slope(xs: list[float], ys: list[float]) -> float:
    xbar = mean(xs)
    ybar = mean(ys)
    denominator = sum((value - xbar) ** 2 for value in xs)
    if denominator <= 0.0:
        raise ValueError("slope x values have no variation")
    return sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys, strict=True)) / denominator


def build_trend_rows(medium_network_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    endpoints = old_endpoint_network_rows()
    mismatch = mismatch_by_network()
    medium_by_instance = {row["instance"]: row for row in medium_network_rows}
    if set(medium_by_instance) != set(FORMAL_INSTANCE_ORDER):
        raise RuntimeError("medium results do not cover all nine formal networks")
    rows: list[dict[str, Any]] = []
    for instance in FORMAL_INSTANCE_ORDER:
        medium = medium_by_instance[instance]
        if int(medium["seed_count"]) != 3:
            raise RuntimeError(f"medium network lacks three seeds: {instance}")
        x_geo = mismatch[instance]["geographic"]
        x_medium = mismatch[instance]["medium"]
        x_mixed = mismatch[instance]["mixed"]
        geo_raw = endpoints[instance]["geographic_observed_saving_pct"]
        geo_fallback = endpoints[instance]["geographic_fallback_saving_pct"]
        medium_raw = float(medium["mean_raw_search_saving_pct"])
        medium_fallback = float(medium["mean_selected_saving_pct"])
        mixed_raw = endpoints[instance]["mixed_observed_saving_pct"]
        mixed_fallback = endpoints[instance]["mixed_fallback_saving_pct"]
        raw_values = [geo_raw, medium_raw, mixed_raw]
        fallback_values = [geo_fallback, medium_fallback, mixed_fallback]
        rows.append(
            {
                "instance": instance,
                "geographic_mismatch_index": x_geo,
                "medium_mismatch_index": x_medium,
                "mixed_mismatch_index": x_mixed,
                "geographic_raw_saving_pct": geo_raw,
                "medium_raw_saving_pct": medium_raw,
                "mixed_raw_saving_pct": mixed_raw,
                "raw_slope_geographic_to_medium": (medium_raw - geo_raw) / (x_medium - x_geo),
                "raw_slope_medium_to_mixed": (mixed_raw - medium_raw) / (x_mixed - x_medium),
                "raw_slope_geographic_to_mixed": (mixed_raw - geo_raw) / (x_mixed - x_geo),
                "raw_three_point_ols_slope": ols_slope([x_geo, x_medium, x_mixed], raw_values),
                "raw_strictly_monotone": geo_raw < medium_raw - EPS and medium_raw < mixed_raw - EPS,
                "geographic_fallback_saving_pct": geo_fallback,
                "medium_fallback_saving_pct": medium_fallback,
                "mixed_fallback_saving_pct": mixed_fallback,
                "fallback_slope_geographic_to_medium": (medium_fallback - geo_fallback) / (x_medium - x_geo),
                "fallback_slope_medium_to_mixed": (mixed_fallback - medium_fallback) / (x_mixed - x_medium),
                "fallback_slope_geographic_to_mixed": (mixed_fallback - geo_fallback) / (x_mixed - x_geo),
                "fallback_three_point_ols_slope": ols_slope(
                    [x_geo, x_medium, x_mixed], fallback_values
                ),
                "fallback_strictly_monotone": (
                    geo_fallback < medium_fallback - EPS and medium_fallback < mixed_fallback - EPS
                ),
            }
        )
    return rows


def trend_decision_fields(trend_rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for prefix in ("raw", "fallback"):
        slopes = [float(row[f"{prefix}_three_point_ols_slope"]) for row in trend_rows]
        positive = sum(value > EPS for value in slopes)
        negative = sum(value < -EPS for value in slopes)
        ties = len(slopes) - positive - negative
        result.update(
            {
                f"{prefix}_strictly_monotone_networks": sum(
                    bool(row[f"{prefix}_strictly_monotone"]) for row in trend_rows
                ),
                f"{prefix}_positive_slope_networks": positive,
                f"{prefix}_negative_slope_networks": negative,
                f"{prefix}_zero_slope_networks": ties,
                f"{prefix}_slope_sign_test_p_two_sided": exact_two_sided_sign_p(positive, negative),
            }
        )
    return result


def collect_pairs(
    out: Path,
    specs: list[dict[str, Any]],
    eval_budget: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    passed: list[dict[str, Any]] = []
    halted: list[dict[str, Any]] = []
    for spec in specs:
        path = out / "pairs" / f"{spec['pair_id']}.json"
        if not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            halted.append({"pair_id": spec["pair_id"], "reason": f"unreadable pair cache: {exc}"})
            continue
        valid, reason = validate_pair_payload(payload, spec, eval_budget)
        if valid:
            passed.append(payload)
        else:
            halted.append({"pair_id": spec["pair_id"], "reason": reason})
    return passed, halted


def paired_rows_from_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for pair in pairs:
        indexed = {row["arm"]: row for row in pair["rows"]}
        fixed = indexed["ownership_fixed"]
        opened = indexed["reassignment_allowed"]
        raw_fixed_cost = float(fixed["raw_search_total_cost"])
        raw_open_cost = float(opened["raw_search_total_cost"])
        selected_fixed_cost = float(fixed["total_cost"])
        selected_open_cost = float(opened["total_cost"])
        raw_cross = int(opened["raw_search_cross_site_customer_count"])
        selected_cross = int(opened["cross_site_customer_count"])
        row: dict[str, Any] = {
            "pair_id": pair["pair_id"],
            "instance": fixed["instance"],
            "condition": CONDITION,
            "seed": int(fixed["seed"]),
            "raw_fixed_total_cost": raw_fixed_cost,
            "raw_open_total_cost": raw_open_cost,
            "raw_search_saving_pct": (raw_fixed_cost - raw_open_cost) / raw_fixed_cost * 100.0,
            "raw_strict_win": raw_open_cost < raw_fixed_cost - EPS and raw_cross > 0,
            "raw_open_cross_site_customer_count": raw_cross,
            "raw_open_cross_site_demand_kg": float(opened["raw_search_cross_site_demand_kg"]),
            "selected_fixed_total_cost": selected_fixed_cost,
            "selected_open_total_cost": selected_open_cost,
            "selected_saving_pct": (selected_fixed_cost - selected_open_cost) / selected_fixed_cost * 100.0,
            "selected_strict_win": selected_open_cost < selected_fixed_cost - EPS and selected_cross > 0,
            "selected_open_cross_site_customer_count": selected_cross,
            "selected_open_cross_site_demand_kg": float(opened["cross_site_demand_kg"]),
            "fixed_fallback_used": bool(fixed["fallback_used"]),
            "open_fallback_used": bool(opened["fallback_used"]),
            "open_selected_source": opened["selected_source"],
        }
        for name in (
            "cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_occ",
            "cost_transship", "cost_carbon", "total_cost",
        ):
            row[f"selected_delta_{name}"] = float(opened[name]) - float(fixed[name])
            row[f"raw_delta_{name}"] = float(opened[f"raw_search_{name}"]) - float(
                fixed[f"raw_search_{name}"]
            )
        result.append(row)
    return sorted(result, key=lambda row: (row["instance"], int(row["seed"])))


def medium_network_summary(paired_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for instance in FORMAL_INSTANCE_ORDER:
        rows = [row for row in paired_rows if row["instance"] == instance]
        if not rows:
            continue
        result.append(
            {
                "instance": instance,
                "condition": CONDITION,
                "seed_count": len(rows),
                "mean_raw_search_saving_pct": mean([float(row["raw_search_saving_pct"]) for row in rows]),
                "mean_selected_saving_pct": mean([float(row["selected_saving_pct"]) for row in rows]),
                "raw_strict_win_count": sum(bool(row["raw_strict_win"]) for row in rows),
                "selected_strict_win_count": sum(bool(row["selected_strict_win"]) for row in rows),
                "open_fallback_count": sum(bool(row["open_fallback_used"]) for row in rows),
                "mean_raw_open_cross_site_customer_count": mean(
                    [float(row["raw_open_cross_site_customer_count"]) for row in rows]
                ),
                "mean_selected_open_cross_site_customer_count": mean(
                    [float(row["selected_open_cross_site_customer_count"]) for row in rows]
                ),
                "mean_raw_open_cross_site_demand_kg": mean(
                    [float(row["raw_open_cross_site_demand_kg"]) for row in rows]
                ),
                "mean_selected_open_cross_site_demand_kg": mean(
                    [float(row["selected_open_cross_site_demand_kg"]) for row in rows]
                ),
            }
        )
    return result


def endpoint_headlines() -> dict[str, float]:
    rows = old_endpoint_network_rows()
    return {
        "old_geographic_observed_mean_saving_pct": mean(
            [row["geographic_observed_saving_pct"] for row in rows.values()]
        ),
        "old_geographic_fallback_preview_mean_saving_pct": mean(
            [row["geographic_fallback_saving_pct"] for row in rows.values()]
        ),
        "old_mixed_observed_mean_saving_pct": mean(
            [row["mixed_observed_saving_pct"] for row in rows.values()]
        ),
        "old_mixed_fallback_preview_mean_saving_pct": mean(
            [row["mixed_fallback_saving_pct"] for row in rows.values()]
        ),
    }


def aggregate(
    *,
    out: Path,
    specs: list[dict[str, Any]],
    eval_budget: int,
    mode: str,
    compatibility_replay: dict[str, Any] | None,
    endpoint_reproduction: dict[str, Any] | None,
) -> dict[str, Any]:
    pairs, halted = collect_pairs(out, specs, eval_budget)
    raw_rows = [row for pair in pairs for row in pair["rows"]]
    write_csv(out / "raw_runs.csv", raw_rows)
    paired_rows = paired_rows_from_pairs(pairs)
    write_csv(out / "paired_results.csv", paired_rows)
    network_rows = medium_network_summary(paired_rows)
    write_csv(out / "network_summary.csv", network_rows)
    headlines = endpoint_headlines()

    compatibility_pass = (
        mode != "formal"
        or (
            compatibility_replay is not None
            and compatibility_replay.get("status") == "PASS"
            and endpoint_reproduction is not None
            and endpoint_reproduction.get("status") == "PASS"
        )
    )
    full_complete = len(pairs) == len(specs) and not halted
    trend_rows: list[dict[str, Any]] = []
    trend_fields: dict[str, Any] = {}
    if mode == "formal" and full_complete and compatibility_pass:
        trend_rows = build_trend_rows(network_rows)
        trend_fields = trend_decision_fields(trend_rows)
    write_csv(out / "trend_summary.csv", trend_rows)

    if halted:
        status = "HALT"
    elif mode == "formal" and compatibility_replay and compatibility_replay.get("status") != "PASS":
        status = "COMPATIBILITY_HALT"
    elif mode == "formal" and (endpoint_reproduction or {}).get("status") == "HALT":
        status = "COMPATIBILITY_HALT"
    elif mode == "formal" and (endpoint_reproduction or {}).get("status") != "PASS":
        status = "ENDPOINT_REPRODUCTION_REQUIRED"
    elif full_complete:
        status = "FORMAL_COMPLETE" if mode == "formal" else "PROBE_COMPLETE"
    elif pairs:
        status = "FORMAL_PARTIAL" if mode == "formal" else "PROBE_PARTIAL"
    else:
        status = "PREPARED"

    decision: dict[str, Any] = {
        "status": status,
        "contract_sha256": specs[0]["contract_sha256"] if specs else "",
        "mode": mode,
        "expected_pairs": len(specs),
        "expected_search_runs": len(specs) * 2,
        "completed_pairs": len(pairs),
        "completed_search_runs": len(raw_rows),
        "halted_pairs": halted,
        "formal_complete": status == "FORMAL_COMPLETE",
        "compatibility_replay_status": (compatibility_replay or {}).get("status", "NOT_APPLICABLE"),
        "endpoint_reproduction_status": (endpoint_reproduction or {}).get("status", "NOT_APPLICABLE"),
        "trend_inference_allowed": bool(trend_rows),
        "raw_search_and_feasible_set_fallback_reported_separately": True,
        "result_direction_used_as_execution_gate": False,
        **headlines,
        **trend_fields,
    }
    if network_rows:
        decision.update(
            {
                "medium_raw_search_network_mean_saving_pct": mean(
                    [float(row["mean_raw_search_saving_pct"]) for row in network_rows]
                ),
                "medium_selected_network_mean_saving_pct": mean(
                    [float(row["mean_selected_saving_pct"]) for row in network_rows]
                ),
            }
        )
    write_json(out / "decision.json", decision)
    return decision


def report_text(decision: dict[str, Any]) -> str:
    """Render the human-readable boundary without strengthening the evidence."""

    status = decision["status"]
    lines = [
        "# E3 中等责任偏离正式增量实验",
        "",
        f"状态：`{status}`。完成 {decision['completed_pairs']}/{decision['expected_pairs']} 个配对，"
        f"即 {decision['completed_search_runs']}/{decision['expected_search_runs']} 次搜索。",
        "",
        "本批只增加跑前冻结的中等客户责任图。固定责任与开放合作两组使用同一起点、"
        "同一随机种子、同一 4000 次完整方案评价预算；开放合作组同时保存原始搜索结果和"
        "不劣于固定责任结果的合法保底选择，两种口径分开报告。",
        "",
        "旧地理责任与空间交错责任端点没有被覆盖。正式三点趋势只有在 108 份旧方案的"
        "当前代码回放和两个端点的确定性复现均通过、且全部中等档配对完成后才允许形成。",
        "结果方向不参与是否继续运行或是否保留记录的判断。",
    ]
    if decision.get("trend_inference_allowed"):
        lines.extend(
            [
                "",
                f"中等档九网络原始搜索平均节省 {decision['medium_raw_search_network_mean_saving_pct']:.6f}%，"
                f"采用合法保底后的平均节省 {decision['medium_selected_network_mean_saving_pct']:.6f}%。",
                "三档是否单调、斜率方向和符号检验详见 `trend_summary.csv` 与 `decision.json`；"
                "正文不得只摘取更好看的保底或原始口径。",
            ]
        )
    return "\n".join(lines) + "\n"


def artifact_hashes(out: Path) -> dict[str, str]:
    return {
        str(path.relative_to(out)): sha256(path)
        for path in sorted(out.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and ".tmp" not in path.name
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }


def parse_csv_strings(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_csv_ints(value: str) -> list[int]:
    try:
        return [int(item) for item in parse_csv_strings(value)]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("prepare", "compatibility", "run", "aggregate", "all"),
        default="prepare",
    )
    parser.add_argument("--instances", default=",".join(FORMAL_INSTANCE_ORDER))
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in FORMAL_SEEDS))
    parser.add_argument("--eval-budget", type=int, default=FORMAL_EVAL_BUDGET)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output", type=Path, default=FORMAL_OUT)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="allow a bounded non-formal subset; it must use a separate output directory",
    )
    args = parser.parse_args()

    instances = parse_csv_strings(args.instances)
    seeds = parse_csv_ints(args.seeds)
    if not instances or len(instances) != len(set(instances)):
        parser.error("--instances must be a non-empty list without duplicates")
    unknown = set(instances) - set(FORMAL_INSTANCE_ORDER)
    if unknown:
        parser.error(f"unknown formal instances: {sorted(unknown)}")
    if not seeds or any(seed <= 0 for seed in seeds) or len(seeds) != len(set(seeds)):
        parser.error("--seeds must be unique positive integers")
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")
    if args.eval_budget <= 0:
        parser.error("--eval-budget must be positive")

    mode = "probe" if args.probe else "formal"
    if mode == "formal":
        if instances != list(FORMAL_INSTANCE_ORDER) or seeds != list(FORMAL_SEEDS):
            parser.error("formal mode requires all nine frozen networks and seeds 1,2,3")
        if args.eval_budget != FORMAL_EVAL_BUDGET:
            parser.error("formal mode requires exactly 4000 evaluations per arm")
        if args.output.resolve() != FORMAL_OUT.resolve():
            parser.error("formal mode must use the frozen formal output directory")
    elif args.output.resolve() == FORMAL_OUT.resolve():
        parser.error("a probe must use a separate --output directory")

    contract = build_contract(
        mode=mode,
        eval_budget=args.eval_budget,
        instances=instances,
        seeds=seeds,
    )
    ensure_metadata(args.output, contract)
    starts = prepare_medium_starts(instances, args.output)
    specs = build_pair_specs(instances, seeds, starts, contract["contract_sha256"])
    write_task_manifest(args.output, specs, args.eval_budget)

    compatibility = None
    endpoint = None
    compatibility_path = args.output / "compatibility" / "old_solution_replay_decision.json"
    if compatibility_path.is_file():
        compatibility = read_json(compatibility_path)
    endpoint = load_endpoint_reproduction_decision(args.output)

    if args.stage in {"compatibility", "all"}:
        if mode == "formal":
            compatibility = replay_old_endpoint_solutions(args.output)
            if compatibility.get("status") != "PASS":
                raise RuntimeError("old endpoint solution replay failed; formal search is blocked")
            endpoint = run_endpoint_reproduction_probes(args.output, args.eval_budget)
            if endpoint.get("status") != "PASS":
                raise RuntimeError("old endpoint deterministic reproduction failed; formal search is blocked")

    if args.stage in {"run", "all"}:
        if mode == "formal" and (
            (compatibility or {}).get("status") != "PASS"
            or (endpoint or {}).get("status") != "PASS"
        ):
            raise RuntimeError("formal compatibility gates must pass before the middle batch")
        sources_fingerprint = contract["source_fingerprint_sha256"]
        with ProcessPoolExecutor(max_workers=min(args.workers, len(specs))) as pool:
            futures = {
                pool.submit(
                    run_pair,
                    spec,
                    out_text=str(args.output),
                    eval_budget=args.eval_budget,
                    source_fingerprint_sha256=sources_fingerprint,
                ): spec
                for spec in specs
            }
            for future in as_completed(futures):
                payload = future.result()
                print(
                    json.dumps(
                        {
                            "pair_id": payload.get("pair_id"),
                            "pair_status": payload.get("pair_status"),
                            "reason": payload.get("reason", ""),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    decision = aggregate(
        out=args.output,
        specs=specs,
        eval_budget=args.eval_budget,
        mode=mode,
        compatibility_replay=compatibility,
        endpoint_reproduction=endpoint,
    )
    (args.output / "report.md").write_text(report_text(decision), encoding="utf-8")
    write_json(args.output / "artifact_hashes.json", artifact_hashes(args.output))
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))

    if args.stage in {"prepare", "aggregate", "compatibility"}:
        return 0
    expected = "FORMAL_COMPLETE" if mode == "formal" else "PROBE_COMPLETE"
    return 0 if decision["status"] == expected else 2


if __name__ == "__main__":
    raise SystemExit(main())
