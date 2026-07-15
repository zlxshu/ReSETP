#!/usr/bin/env python3
"""Formal E2b four-arm component-ablation runner.

The route-search matrix has three arms under the same start and evaluation
budget.  A is one continuous ALNS phase, B is the frozen staged search, and C
adds the dedicated reciprocal cross-depot adjustment to B.  Strict multitrip
and the cross-depot feasible domain remain enabled in all three arms.  D does
not search: it reuses C and changes charging time only.

The default invocation is the formal nine-network x five-seed x 4000-eval
contract.  Smaller ``--instances``/``--seeds``/``--eval-budget`` invocations
are supported for future wiring probes, but are labelled subset-only and do
not authorize formal inference.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e2_alns import e2b_component_ablation_probe_20260715 as probe  # noqa: E402


COMPONENT_COMMIT = "0652cc2b"
DEFAULT_OUT = ROOT / "baselines/e2_alns/e2b_component_ablation_formal_20260715"
FORMAL_INSTANCES = probe.INSTANCE_LADDER
FORMAL_SEEDS = tuple(range(1, 6))
FORMAL_EVAL_BUDGET = 4000
CONDITION = "mixed"
WORKER_CHOICES = (6, 7, 8)
DEFAULT_WORKERS = 6
GOLD_PYTHON = Path("/opt/anaconda3/bin/python3.13")
TOLERANCE = 1e-6
GROUP_ORDER = ("A_continuous", "B_staged", "C_staged_cross", "D_full")
SEARCH_GROUP_ORDER = GROUP_ORDER[:3]
SOURCE_PATHS = (
    Path(__file__).resolve(),
    Path(probe.__file__).resolve(),
    Path(probe.legacy.__file__).resolve(),
    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    ROOT / "solver/src/setp_solver/algorithms/resetp_alns/operators/feasible_repair.py",
    ROOT / "solver/src/setp_solver/search/bundle.py",
    ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/prices.py",
    ROOT / "solver/src/setp_solver/solution.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
)
REQUIRED_EVIDENCE = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def material_path(label: str) -> Path:
    path = Path(label)
    return path if path.is_absolute() else ROOT / path


def clean_files(paths: Iterable[Path]) -> list[Path]:
    """Return existing regular files while excluding AppleDouble/cache noise."""

    output: list[Path] = []
    for path in paths:
        if not path.is_file():
            continue
        if path.name.startswith("._") or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        output.append(path.resolve())
    return sorted(set(output), key=lambda item: str(item))


def fingerprint_files(paths: Iterable[Path]) -> tuple[dict[str, str], str]:
    file_hashes = {display_path(path): sha256(path) for path in clean_files(paths)}
    return file_hashes, sha256_bytes(canonical_bytes(file_hashes))


def instance_input_fingerprint(instance: str) -> tuple[dict[str, str], str]:
    bundle_dir = probe.ASSET_ROOT / instance / "bundle"
    paths = [
        *bundle_dir.rglob("*"),
        probe.ASSET_ROOT / instance / f"{CONDITION}__common_start.json",
        probe.ASSET_ROOT / instance / f"{CONDITION}__common_start_meta.json",
        probe.OWNERSHIP_ROOT / f"{instance}__{CONDITION}.csv",
        *(probe.ASSET_ROOT.parent / name for name in ("metadata.json", "decision.json", "artifact_hashes.json")),
        *(probe.OWNERSHIP_ROOT.parent / name for name in ("metadata.json", "decision.json", "artifact_hashes.json")),
    ]
    file_hashes, fingerprint = fingerprint_files(paths)
    required_names = {
        "instance.json",
        "distance_matrix.npy",
        "carbon_profile.csv",
        "scenario_manifest.json",
        f"{CONDITION}__common_start.json",
        f"{instance}__{CONDITION}.csv",
    }
    observed_names = {Path(label).name for label in file_hashes}
    missing = required_names - observed_names
    if missing:
        raise FileNotFoundError(f"{instance}: missing frozen inputs {sorted(missing)}")
    return file_hashes, fingerprint


def parse_csv_items(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", default=",".join(FORMAL_INSTANCES))
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in FORMAL_SEEDS))
    parser.add_argument("--eval-budget", type=int, default=FORMAL_EVAL_BUDGET)
    parser.add_argument("--workers", type=int, choices=WORKER_CHOICES, default=DEFAULT_WORKERS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    args.instances = parse_csv_items(args.instances)
    try:
        args.seeds = tuple(int(item) for item in parse_csv_items(args.seeds))
    except ValueError as exc:
        parser.error(f"--seeds must be comma-separated integers: {exc}")
    if not args.instances:
        parser.error("--instances must not be empty")
    if len(set(args.instances)) != len(args.instances):
        parser.error("--instances contains duplicates")
    unsupported = set(args.instances) - set(FORMAL_INSTANCES)
    if unsupported:
        parser.error(f"unsupported instances: {sorted(unsupported)}")
    if not args.seeds or any(seed <= 0 for seed in args.seeds):
        parser.error("--seeds must contain positive integers")
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds contains duplicates")
    if int(args.eval_budget) <= 0:
        parser.error("--eval-budget must be positive")
    return args


def validate_execution_environment() -> None:
    if Path(sys.executable).resolve() != GOLD_PYTHON.resolve():
        raise RuntimeError(
            f"HALT_E2B_PYTHON_DRIFT: {Path(sys.executable).resolve()} != {GOLD_PYTHON.resolve()}"
        )
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("HALT_E2B_HASH_SEED_DRIFT: set PYTHONHASHSEED=0")


def build_formal_tasks(
    instances: Iterable[str],
    seeds: Iterable[int],
    *,
    eval_budget: int,
) -> list[dict[str, Any]]:
    instance_tuple = tuple(instances)
    seed_tuple = tuple(int(seed) for seed in seeds)
    tasks = probe.build_search_tasks(
        instance_tuple,
        seed_tuple,
        eval_budget=int(eval_budget),
        condition=CONDITION,
    )
    fingerprints = {
        instance: instance_input_fingerprint(instance) for instance in instance_tuple
    }
    for task in tasks:
        file_hashes, fingerprint = fingerprints[str(task["instance"])]
        task["input_file_hashes_json"] = json.dumps(
            file_hashes, ensure_ascii=False, sort_keys=True
        )
        task["input_data_sha256"] = fingerprint
        task["strict_multitrip"] = True
        task["allow_cross_depot"] = True
    validate_formal_task_manifest(
        tasks,
        instances=instance_tuple,
        seeds=seed_tuple,
        eval_budget=int(eval_budget),
    )
    return tasks


def validate_formal_task_manifest(
    tasks: list[dict[str, Any]],
    *,
    instances: Sequence[str],
    seeds: Sequence[int],
    eval_budget: int,
) -> None:
    expected = {
        (instance, int(seed), group)
        for instance in instances
        for seed in seeds
        for group in SEARCH_GROUP_ORDER
    }
    observed = {
        (str(task["instance"]), int(task["seed"]), str(task["group_id"]))
        for task in tasks
    }
    if observed != expected or len(tasks) != len(expected):
        raise ValueError(
            f"E2b task matrix mismatch: expected={len(expected)}, observed={len(tasks)}, "
            f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
        )
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for task in tasks:
        grouped.setdefault((str(task["instance"]), int(task["seed"])), []).append(task)
    for key, unit in grouped.items():
        if len({task["start_solution_sha256"] for task in unit}) != 1:
            raise ValueError(f"{key}: shared start drift")
        if len({task["input_data_sha256"] for task in unit}) != 1:
            raise ValueError(f"{key}: frozen input drift")
        if {int(task["eval_budget"]) for task in unit} != {int(eval_budget)}:
            raise ValueError(f"{key}: equal-budget drift")
        if any(not task["strict_multitrip"] or not task["allow_cross_depot"] for task in unit):
            raise ValueError(f"{key}: feasible-domain switch drift")
        by_group = {str(task["group_id"]): task for task in unit}
        expected_switches = {
            "A_continuous": (False, False, False),
            "B_staged": (True, False, False),
            "C_staged_cross": (True, True, True),
        }
        for group, expected_values in expected_switches.items():
            observed_values = (
                bool(by_group[group]["enable_staged_search"]),
                bool(by_group[group]["enable_cross_depot_operator"]),
                bool(by_group[group]["reciprocal_cross_depot"]),
            )
            if observed_values != expected_values:
                raise ValueError(
                    f"{key}/{group}: component switch drift "
                    f"{observed_values} != {expected_values}"
                )


def verify_task_inputs(task: dict[str, Any]) -> None:
    expected = json.loads(str(task["input_file_hashes_json"]))
    observed: dict[str, str] = {}
    for label, expected_hash in expected.items():
        path = material_path(label)
        if not path.is_file():
            raise FileNotFoundError(path)
        observed[label] = sha256(path)
        if observed[label] != expected_hash:
            raise RuntimeError(f"input hash drift: {label}")
    if sha256_bytes(canonical_bytes(observed)) != task["input_data_sha256"]:
        raise RuntimeError("input data fingerprint drift")


def input_drift_failures(tasks: Iterable[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    checked: set[str] = set()
    for task in tasks:
        fingerprint = str(task["input_data_sha256"])
        if fingerprint in checked:
            continue
        checked.add(fingerprint)
        try:
            verify_task_inputs(task)
        except Exception as exc:
            failures.append(
                f"{task['instance']}: frozen input drift after run: "
                f"{type(exc).__name__}: {exc}"
            )
    return failures


def run_formal_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    verify_task_inputs(task)
    rows = probe.run_search_task(task)
    verify_task_inputs(task)
    return rows


def _rounded(value: Any) -> float:
    return round(float(value), 9)


def _charging_action_identity(action: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(action.get("vehicle_id", "")),
        str(action.get("station_id", "")),
        _rounded(action.get("energy_kwh", 0.0)),
        _rounded(action.get("occupancy_minutes", 0.0)),
        int(action.get("charge_day_offset", 0)),
    )


def charging_timing_change_count(
    before_payload: dict[str, Any], after_payload: dict[str, Any]
) -> int:
    def grouped_times(payload: dict[str, Any]) -> dict[tuple[Any, ...], list[float]]:
        grouped: dict[tuple[Any, ...], list[float]] = {}
        for action in payload.get("charging_actions", []):
            grouped.setdefault(_charging_action_identity(action), []).append(
                _rounded(action.get("charge_start_second", 0.0))
            )
        for values in grouped.values():
            values.sort()
        return grouped

    before = grouped_times(before_payload)
    after = grouped_times(after_payload)
    changed = 0
    for identity in set(before) | set(after):
        left = before.get(identity, [])
        right = after.get(identity, [])
        changed += abs(len(left) - len(right))
        changed += sum(
            abs(left_value - right_value) > 1e-9
            for left_value, right_value in zip(left, right)
        )
    return changed


def solution_fingerprints(payload: dict[str, Any]) -> dict[str, Any]:
    routes = payload.get("routes", [])
    actions = payload.get("charging_actions", [])
    route_payload = sorted(
        (
            str(route.get("home_depot_id", "")),
            tuple(str(node) for node in route.get("node_sequence", [])),
        )
        for route in routes
    )
    vehicle_payload = sorted(
        (
            str(route.get("vehicle_id", "")),
            str(route.get("vehicle_type", "")).lower(),
            str(route.get("home_depot_id", "")),
            tuple(str(node) for node in route.get("node_sequence", [])),
        )
        for route in routes
    )
    action_identity_payload = sorted(_charging_action_identity(action) for action in actions)
    action_timing_payload = sorted(
        (
            str(action.get("vehicle_id", "")),
            str(action.get("station_id", "")),
            _rounded(action.get("energy_kwh", 0.0)),
            _rounded(action.get("occupancy_minutes", 0.0)),
            int(action.get("charge_day_offset", 0)),
            _rounded(action.get("charge_start_second", 0.0)),
        )
        for action in actions
    )
    total_energy = _rounded(sum(float(action.get("energy_kwh", 0.0)) for action in actions))
    return {
        "route_sha256": sha256_bytes(canonical_bytes(route_payload)),
        "vehicle_sha256": sha256_bytes(canonical_bytes(vehicle_payload)),
        "charging_identity_sha256": sha256_bytes(canonical_bytes(action_identity_payload)),
        "charging_timing_sha256": sha256_bytes(canonical_bytes(action_timing_payload)),
        "total_energy_kwh": total_energy,
        "total_energy_sha256": sha256_bytes(canonical_bytes(total_energy)),
    }


def load_start_payloads(tasks: Iterable[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    output: dict[tuple[str, int], dict[str, Any]] = {}
    for task in tasks:
        key = (str(task["instance"]), int(task["seed"]))
        if key not in output:
            path = Path(task["start_path"])
            if sha256(path) != str(task["start_solution_sha256"]):
                raise RuntimeError(f"{key}: shared start changed after manifest creation")
            output[key] = json.loads(path.read_text(encoding="utf-8"))
    return output


def attach_before_after_fingerprints(
    rows: list[dict[str, Any]],
    start_payloads: dict[tuple[str, int], dict[str, Any]],
) -> None:
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["instance"]), int(row["seed"])), {})[
            str(row["group_id"])
        ] = row
    for key, arms in grouped.items():
        start_payload = start_payloads[key]
        c_payload = arms.get("C_staged_cross", {}).get("_solution_payload")
        for group, row in arms.items():
            after_payload = row["_solution_payload"]
            if group == "D_full" and c_payload is not None:
                before_payload = c_payload
                basis = "C_staged_cross_to_D_full"
            else:
                before_payload = start_payload
                basis = "shared_start_to_search_output"
            before = solution_fingerprints(before_payload)
            after = solution_fingerprints(after_payload)
            row["fingerprint_basis"] = basis
            for name, value in before.items():
                row[f"before_{name}"] = value
            for name, value in after.items():
                row[f"after_{name}"] = value
            for name in (
                "route_sha256",
                "vehicle_sha256",
                "charging_identity_sha256",
                "total_energy_sha256",
            ):
                row[f"{name.removesuffix('_sha256')}_unchanged_from_before"] = (
                    before[name] == after[name]
                )
            row["charging_timing_changed_from_before"] = (
                before["charging_timing_sha256"] != after["charging_timing_sha256"]
            )
            row["charging_actions_moved_from_raw_search_output"] = row.get(
                "charging_actions_moved", 0
            )
            row["charging_actions_moved_from_before"] = charging_timing_change_count(
                before_payload, after_payload
            )


def attach_provenance(
    rows: list[dict[str, Any]],
    tasks: Iterable[dict[str, Any]],
    *,
    component_commit: str,
    execution_commit: str,
    source_fingerprint: str,
) -> None:
    data_by_unit: dict[tuple[str, int], str] = {}
    for task in tasks:
        key = (str(task["instance"]), int(task["seed"]))
        fingerprint = str(task["input_data_sha256"])
        previous = data_by_unit.setdefault(key, fingerprint)
        if previous != fingerprint:
            raise ValueError(f"{key}: input data fingerprint differs across arms")
    for row in rows:
        key = (str(row["instance"]), int(row["seed"]))
        row["input_data_sha256"] = data_by_unit[key]
        row["source_fingerprint_sha256"] = source_fingerprint
        row["component_commit"] = component_commit
        row["execution_commit"] = execution_commit


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _as_int(value: Any) -> int:
    return int(float(value))


def _as_float(value: Any) -> float:
    return float(value)


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return list(json.loads(str(value)))


def full_formal_contract(
    instances: Sequence[str], seeds: Sequence[int], eval_budget: int
) -> bool:
    return (
        tuple(instances) == FORMAL_INSTANCES
        and tuple(int(seed) for seed in seeds) == FORMAL_SEEDS
        and int(eval_budget) == FORMAL_EVAL_BUDGET
    )


def _arm_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for group in GROUP_ORDER:
        arm = [row for row in rows if row.get("group_id") == group]
        record: dict[str, Any] = {
            "row_count": len(arm),
            "valid_count": sum(_as_bool(row.get("valid")) for row in arm),
            "search_eval_total": sum(_as_int(row.get("actual_search_evals", 0)) for row in arm),
        }
        for metric in (
            "total_cost",
            "cost_fix",
            "cost_km",
            "cost_fuel",
            "cost_elec",
            "cost_occ",
            "cost_transship",
            "cost_carbon",
            "E_total",
            "E_cv_direct",
            "E_ev_indirect",
            "electricity_kwh",
        ):
            values = [_as_float(row[metric]) for row in arm if metric in row]
            if values:
                record[f"mean_{metric}"] = statistics.fmean(values)
        summary[group] = record
    return summary


def _paired_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["instance"]), _as_int(row["seed"])), {})[
            str(row["group_id"])
        ] = row
    comparisons = {
        "B_minus_A_total_cost": ("A_continuous", "B_staged", "total_cost"),
        "C_minus_B_total_cost": ("B_staged", "C_staged_cross", "total_cost"),
        "D_minus_C_ev_indirect": ("C_staged_cross", "D_full", "E_ev_indirect"),
    }
    output: dict[str, dict[str, Any]] = {}
    for name, (left_group, right_group, metric) in comparisons.items():
        deltas: list[float] = []
        for arms in grouped.values():
            if left_group in arms and right_group in arms:
                deltas.append(
                    _as_float(arms[right_group][metric]) - _as_float(arms[left_group][metric])
                )
        output[name] = {
            "pair_count": len(deltas),
            "right_better": sum(delta < -TOLERANCE for delta in deltas),
            "ties": sum(abs(delta) <= TOLERANCE for delta in deltas),
            "right_worse": sum(delta > TOLERANCE for delta in deltas),
            "mean_delta": statistics.fmean(deltas) if deltas else None,
        }
    return output


def assess_formal(
    rows: list[dict[str, Any]],
    *,
    instances: Sequence[str],
    seeds: Sequence[int],
    eval_budget: int,
    worker_failures: Sequence[dict[str, Any]] = (),
    contract_failures: Sequence[str] = (),
) -> dict[str, Any]:
    failures = list(contract_failures) + [
        f"worker failure {item.get('instance')}/seed{item.get('seed')}/{item.get('group_id')}: "
        f"{item.get('error_type')}: {item.get('error')}"
        for item in worker_failures
    ]
    expected_units = {(instance, int(seed)) for instance in instances for seed in seeds}
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    duplicates: list[tuple[str, int, str]] = []
    for row in rows:
        key = (str(row["instance"]), _as_int(row["seed"]))
        group = str(row["group_id"])
        if group in grouped.setdefault(key, {}):
            duplicates.append((*key, group))
        grouped[key][group] = row
    if duplicates:
        failures.append(f"duplicate evidence rows: {duplicates}")
    extra_units = set(grouped) - expected_units
    if extra_units:
        failures.append(f"unexpected comparison units: {sorted(extra_units)}")

    moved_units = 0
    carbon_improved_units = 0
    carbon_nonincreasing_units = 0
    for key in sorted(expected_units):
        arms = grouped.get(key, {})
        if set(arms) != set(GROUP_ORDER):
            failures.append(
                f"{key}: comparison groups mismatch; found={sorted(arms)}, expected={list(GROUP_ORDER)}"
            )
            continue
        if len({str(arms[group]["start_solution_sha256"]) for group in GROUP_ORDER}) != 1:
            failures.append(f"{key}: shared start differs across arms")
        for group in SEARCH_GROUP_ORDER:
            row = arms[group]
            if not _as_bool(row.get("search_performed")):
                failures.append(f"{key}/{group}: search was not performed")
            if _as_int(row.get("configured_search_budget", -1)) != int(eval_budget):
                failures.append(f"{key}/{group}: configured budget drift")
            if _as_int(row.get("actual_search_evals", -1)) != int(eval_budget):
                failures.append(f"{key}/{group}: evaluation budget not exhausted")
            if not _as_bool(row.get("strict_multitrip")) or not _as_bool(
                row.get("allow_cross_depot")
            ):
                failures.append(f"{key}/{group}: feasible-domain contract failed")
            if not _as_bool(row.get("valid")) or _as_int(row.get("violation_count", -1)) != 0:
                failures.append(f"{key}/{group}: infeasible result")
            if _as_float(row.get("cost_component_error", float("inf"))) > TOLERANCE:
                failures.append(f"{key}/{group}: cost breakdown does not close")

        a, b, c, d = (arms[group] for group in GROUP_ORDER)
        expected_staged = probe.expected_staged_budgets(int(eval_budget))
        if _as_bool(a.get("enable_staged_search")):
            failures.append(f"{key}/A: staged search leaked into continuous arm")
        if _as_bool(a.get("enable_cross_depot_operator")) or _as_bool(
            a.get("reciprocal_cross_depot")
        ):
            failures.append(f"{key}/A: dedicated cross-depot adjustment leaked")
        if _json_list(a.get("stage_budgets_json", "[]")) != [int(eval_budget)]:
            failures.append(f"{key}/A: continuous phase budget drift")
        if _json_list(a.get("strong_phase_indexes_json", "[]")) != []:
            failures.append(f"{key}/A: strong phase leaked")
        if not _as_bool(b.get("enable_staged_search")) or _as_bool(
            b.get("enable_cross_depot_operator")
        ):
            failures.append(f"{key}/B: staged-only switch drift")
        if _as_bool(b.get("reciprocal_cross_depot")):
            failures.append(f"{key}/B: reciprocal cross-depot adjustment leaked")
        if not _as_bool(c.get("enable_staged_search")) or not _as_bool(
            c.get("enable_cross_depot_operator")
        ) or not _as_bool(c.get("reciprocal_cross_depot")):
            failures.append(f"{key}/C: dedicated cross-depot switch drift")
        for group, row in (("B", b), ("C", c)):
            if _json_list(row.get("stage_budgets_json", "[]")) != expected_staged:
                failures.append(f"{key}/{group}: staged phase budget drift")
            if _json_list(row.get("strong_phase_indexes_json", "[]")) != [1]:
                failures.append(f"{key}/{group}: strong middle phase drift")
        if _as_int(a.get("dedicated_cross_destroy_attempts", 0)) != 0 or _as_int(
            b.get("dedicated_cross_destroy_attempts", 0)
        ) != 0:
            failures.append(f"{key}: dedicated cross-depot operator leaked into A/B")
        if _as_int(c.get("dedicated_cross_destroy_attempts", 0)) <= 0 or _as_int(
            c.get("dedicated_cross_repair_attempts", 0)
        ) <= 0:
            failures.append(f"{key}/C: dedicated cross-depot pair was never exercised")

        if _as_bool(d.get("search_performed")) or _as_int(d.get("actual_search_evals", -1)) != 0:
            failures.append(f"{key}/D: unexpected route search")
        if str(d.get("source_group")) != "C_staged_cross":
            failures.append(f"{key}/D: source arm is not C")
        if _as_int(d.get("source_search_evals", -1)) != int(eval_budget):
            failures.append(f"{key}/D: C source budget drift")
        if not _as_bool(d.get("strict_multitrip")) or not _as_bool(
            d.get("allow_cross_depot")
        ) or not _as_bool(d.get("valid")):
            failures.append(f"{key}/D: replay feasibility failed")
        for invariant in (
            "route_unchanged_from_before",
            "vehicle_unchanged_from_before",
            "charging_identity_unchanged_from_before",
            "total_energy_unchanged_from_before",
        ):
            if not _as_bool(d.get(invariant)):
                failures.append(f"{key}/D: invariant failed: {invariant}")
        moved = _as_int(d.get("charging_actions_moved_from_before", 0))
        if moved > 0:
            moved_units += 1
            if not _as_bool(d.get("charging_timing_changed_from_before")):
                failures.append(f"{key}/D: moved charging lacks a timing fingerprint change")
        c_carbon = _as_float(c.get("E_ev_indirect", 0.0))
        d_carbon = _as_float(d.get("E_ev_indirect", 0.0))
        if d_carbon <= c_carbon + TOLERANCE:
            carbon_nonincreasing_units += 1
        else:
            failures.append(f"{key}/D: carbon-aware replay increased EV indirect emissions")
        if d_carbon < c_carbon - TOLERANCE:
            carbon_improved_units += 1

    if expected_units and moved_units == 0:
        failures.append("D did not move any charging action in the requested matrix")
    is_formal = full_formal_contract(instances, seeds, eval_budget)
    if failures:
        verdict = "HALT_E2B_FORMAL_EVIDENCE"
    elif is_formal:
        verdict = "E2B_FORMAL_EVIDENCE_READY"
    else:
        verdict = "PASS_E2B_SUBSET_ONLY"
    return {
        "verdict": verdict,
        "formal_request_shape_complete": is_formal,
        "formal_contract_complete": bool(is_formal and not failures),
        "formal_inference_allowed": bool(is_formal and not failures),
        "failure_count": len(failures),
        "failures": failures,
        "expected_comparison_units": len(expected_units),
        "observed_comparison_units": len(set(grouped) & expected_units),
        "expected_search_rows": len(expected_units) * 3,
        "expected_evidence_rows": len(expected_units) * 4,
        "observed_evidence_rows": len(rows),
        "worker_failure_count": len(worker_failures),
        "contract_failure_count": len(contract_failures),
        "d_moved_charging_unit_count": moved_units,
        "d_carbon_nonincreasing_unit_count": carbon_nonincreasing_units,
        "d_strict_carbon_improvement_unit_count": carbon_improved_units,
        "arm_summary": _arm_summary(rows),
        "paired_summary": _paired_summary(rows),
        "claim_boundary": (
            "The complete default matrix may support component-effect analysis; subset runs check "
            "wiring only. No arm is selected or discarded by performance in this runner."
        ),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    clean = [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]
    fieldnames = sorted({key for row in clean for key in row})
    if not fieldnames:
        fieldnames = ["instance", "seed", "group_id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(clean)


def artifact_hashes(out: Path) -> dict[str, str]:
    paths = clean_files(path for path in out.rglob("*") if path.name != "artifact_hashes.json")
    return {str(path.relative_to(out)): sha256(path) for path in paths}


def render_report(decision: dict[str, Any]) -> str:
    return (
        "# E2b four-arm component ablation\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "A/B/C use one shared start and the same route-search budget. Strict multitrip and the "
        "cross-depot feasible domain stay enabled in all three; only staged search and the dedicated "
        "reciprocal cross-depot operator are ablated. D performs zero route-search evaluations and "
        "may change charging time only.\n\n"
        f"Comparison units: {decision['observed_comparison_units']}/"
        f"{decision['expected_comparison_units']}; evidence rows: "
        f"{decision['observed_evidence_rows']}/{decision['expected_evidence_rows']}; "
        f"worker failures: {decision['worker_failure_count']}.\n\n"
        f"D charging moved in {decision['d_moved_charging_unit_count']} units and strictly reduced "
        f"EV indirect emissions in {decision['d_strict_carbon_improvement_unit_count']} units.\n\n"
        "No performance direction is used to filter or rerun an arm. Subset runs are wiring-only.\n\n"
        f"Failures: `{json.dumps(decision['failures'], ensure_ascii=False)}`\n"
    )


def write_evidence_bundle(
    out: Path,
    *,
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    write_csv(out / "raw_runs.csv", rows)
    write_json(out / "metadata.json", metadata)
    write_json(out / "decision.json", decision)
    (out / "report.md").write_text(render_report(decision), encoding="utf-8")
    write_json(out / "artifact_hashes.json", artifact_hashes(out))
    missing = [name for name in REQUIRED_EVIDENCE if not (out / name).is_file()]
    if missing:
        raise RuntimeError(f"evidence bundle incomplete: {missing}")


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def component_commit_full() -> str:
    commit = git_output("rev-parse", COMPONENT_COMMIT)
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode != 0:
        raise RuntimeError(f"HALT_E2B_COMPONENT_COMMIT_NOT_ANCESTOR: {commit}")
    return commit


def validate_fresh_output_dir(out: Path) -> None:
    if not out.exists():
        return
    leftovers = sorted(str(path.relative_to(out)) for path in out.iterdir())
    if leftovers:
        raise FileExistsError(
            f"refusing non-empty E2b output directory {out}: {leftovers}"
        )


def _persist_payloads(rows: list[dict[str, Any]], out: Path) -> None:
    solutions = out / "solutions"
    certificates = out / "certificates"
    solutions.mkdir(parents=True, exist_ok=True)
    certificates.mkdir(parents=True, exist_ok=True)
    for row in rows:
        run_id = (
            f"{row['instance']}__{row['condition']}__seed{row['seed']}__{row['group_id']}"
        )
        solution_path = solutions / f"{run_id}.json"
        certificate_path = certificates / f"{run_id}.json"
        write_json(solution_path, row.pop("_solution_payload"))
        write_json(certificate_path, row.pop("_certificate_payload"))
        row["solution_path"] = display_path(solution_path)
        row["solution_file_sha256"] = sha256(solution_path)
        row["certificate_path"] = display_path(certificate_path)
        row["certificate_sha256"] = sha256(certificate_path)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_execution_environment()
    if (
        not full_formal_contract(args.instances, args.seeds, int(args.eval_budget))
        and args.output_dir.resolve() == DEFAULT_OUT.resolve()
    ):
        raise ValueError("subset/probe runs require a separate --output-dir")
    component_source_commit = component_commit_full()
    execution_source_commit = git_output("rev-parse", "HEAD")
    tasks = build_formal_tasks(args.instances, args.seeds, eval_budget=int(args.eval_budget))
    start_payloads = load_start_payloads(tasks)
    source_hashes, source_fingerprint = fingerprint_files(SOURCE_PATHS)
    out = args.output_dir.resolve()
    validate_fresh_output_dir(out)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "task_manifest.csv", tasks)

    started = time.perf_counter()
    effective_workers = min(int(args.workers), len(tasks))
    rows: list[dict[str, Any]] = []
    worker_failures: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=effective_workers) as pool:
        futures = {pool.submit(run_formal_task, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                rows.extend(future.result())
            except Exception as exc:  # evidence records the failed task; no silent loss
                worker_failures.append(
                    {
                        "instance": task["instance"],
                        "seed": task["seed"],
                        "group_id": task["group_id"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    rows.sort(
        key=lambda row: (
            FORMAL_INSTANCES.index(str(row["instance"])),
            int(row["seed"]),
            GROUP_ORDER.index(str(row["group_id"])),
        )
    )
    source_hashes_after, source_fingerprint_after = fingerprint_files(SOURCE_PATHS)
    contract_failures = input_drift_failures(tasks)
    if source_fingerprint_after != source_fingerprint or source_hashes_after != source_hashes:
        contract_failures.append("source files changed while the E2b matrix was running")
    attach_before_after_fingerprints(rows, start_payloads)
    attach_provenance(
        rows,
        tasks,
        component_commit=component_source_commit,
        execution_commit=execution_source_commit,
        source_fingerprint=source_fingerprint,
    )
    _persist_payloads(rows, out)
    if worker_failures:
        write_json(out / "worker_failures.json", worker_failures)

    decision = assess_formal(
        rows,
        instances=args.instances,
        seeds=args.seeds,
        eval_budget=int(args.eval_budget),
        worker_failures=worker_failures,
        contract_failures=contract_failures,
    )
    input_fingerprints: dict[str, Any] = {}
    for task in tasks:
        instance = str(task["instance"])
        input_fingerprints.setdefault(
            instance,
            {
                "sha256": task["input_data_sha256"],
                "files": json.loads(task["input_file_hashes_json"]),
            },
        )
    metadata = {
        "schema": "resetp.e2b.component-ablation-formal.v1",
        "purpose": "additive four-arm component evidence; no performance-based filtering",
        "formal_request_shape_complete": full_formal_contract(
            args.instances, args.seeds, int(args.eval_budget)
        ),
        "formal_contract_complete": bool(decision["formal_contract_complete"]),
        "instances": list(args.instances),
        "seeds": list(args.seeds),
        "condition": CONDITION,
        "search_groups": [vars(group) for group in probe.SEARCH_GROUPS],
        "fourth_group": (
            "D_full reuses C routes, vehicles, charging-action identity, and total energy; "
            "zero route search; charging time only"
        ),
        "eval_budget_per_search": int(args.eval_budget),
        "planned_search_task_count": len(tasks),
        "planned_evidence_row_count": len(args.instances) * len(args.seeds) * 4,
        "requested_workers": int(args.workers),
        "effective_workers": effective_workers,
        "elapsed_seconds": time.perf_counter() - started,
        "strict_multitrip_in_all_search_arms": True,
        "cross_depot_feasible_domain_in_all_search_arms": True,
        "component_commit": component_source_commit,
        "execution_commit": execution_source_commit,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": sys.version,
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "source_file_hashes": source_hashes,
        "source_fingerprint_sha256": source_fingerprint,
        "source_fingerprint_after_run_sha256": source_fingerprint_after,
        "source_files_unchanged_during_run": not contract_failures,
        "input_data_fingerprints": input_fingerprints,
    }
    write_evidence_bundle(out, rows=rows, metadata=metadata, decision=decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not str(decision["verdict"]).startswith("HALT") else 2


if __name__ == "__main__":
    raise SystemExit(main())
