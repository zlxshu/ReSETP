#!/usr/bin/env python3
"""Run one bounded real-input trial of the formal self-developed Problem-HGS.

This is deliberately not a scientific performance experiment.  It executes
one search cycle on a real China81 input and saves enough evidence to diagnose
interface, crossover, full-evaluation, and packaging failures.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.util
import json
import math
import os
import platform
import subprocess
import sys
import traceback
from collections import Counter
from contextlib import nullcontext
from dataclasses import asdict, replace
from importlib import metadata as importlib_metadata
from itertools import permutations
from pathlib import Path
from time import perf_counter
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping, Sequence

from experiment_acceptance import (
    assess_run,
    finalize_five_file_package,
    package_exit_code,
)
from build_china81_suite_rebuild_20260812 import (
    build_edf_route_plans,
    plans_to_solution,
)
from setp_solver.algorithms.problem_hgs.charging import (
    ChargingRepairPolicy,
    charging_rejection_reason,
    repair_changed_duties,
)
from setp_solver.algorithms.problem_hgs.c0_witness_adapter import (
    adapt_witness_rows_to_duty,
)
from setp_solver.algorithms.problem_hgs.contracts import CandidateStatus
from setp_solver.algorithms.problem_hgs.dynamic import (
    DutyDynamicState,
    future_individual_from_cut,
)
from setp_solver.algorithms.problem_hgs.dynamic_insertion import (
    DynamicInsertionOperator,
)
from setp_solver.algorithms.problem_hgs.education import evaluate_move
from setp_solver.algorithms.problem_hgs.enterprise_adapter import (
    EnterpriseProblemSlice,
    slice_enterprise_problem,
)
from setp_solver.algorithms.problem_hgs.evaluation import (
    DutyEvaluationContext,
    DutyFullEvaluator,
    FrozenMappingIdentity,
    RebuiltRouteConstraintContract,
)
from setp_solver.algorithms.problem_hgs.fleet_registry import (
    register_all_vehicle_slots,
)
from setp_solver.algorithms.problem_hgs.frvcpy_adapter import (
    FRVCPY_COMMIT,
    FRVCPY_SOURCE_SHA256,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual
from setp_solver.algorithms.problem_hgs.hybrid_decoder import (
    begin_decoder_structure_stats,
    end_decoder_structure_stats,
)
from setp_solver.algorithms.problem_hgs.operators import (
    ReverseSegmentMove,
    generate_problem_moves,
)
from setp_solver.algorithms.problem_hgs.population import (
    PopulationParameters,
)
from setp_solver.algorithms.resetp_alns.support.charging import (
    charging_repair_runtime_diagnostics,
)
from setp_solver.algorithms.problem_hgs.proposals import (
    LegacyCompleteProposalEngine,
    MechanismProposalEngine,
    SequentialProposalEngine,
)
from setp_solver.algorithms.problem_hgs.initialization import build_initial_population
from setp_solver.algorithms.problem_hgs.kernel_proposals import (
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.runner import (
    SINGLE_OBJECTIVE,
    ProblemHGSSearchParameters,
    FrozenPopulationIdentity,
    population_sha256,
    run_integrated_problem_hgs,
)
from setp_solver.algorithms.problem_hgs.schedule_capture import (
    ScheduleCaptureRecord,
    schedule_capture_sink,
)
from setp_solver.charge_timing import CHARGE_TIMING_POLICIES
from setp_solver.china81 import (
    CHINA81_CARBON_PRICE_CNY_PER_KG,
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
    ENDOGENOUS_FLEET_PARAMETERS,
    FIXED_25_PERCENT_FLEET_PARAMETERS,
    China81FleetParameterClass,
    China81Bundle,
    _china_prices,
    _china_vehicle_parameters,
    _city_runtime_binding_from_profile,
    _diesel_price_map_from_profile,
    _load_time_profile,
    load_china81_bundle,
)
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.check import PROFIT_FAIRNESS
from setp_solver.enterprise_accounting import build_enterprise_ledger
from setp_solver.enterprise_assignment import load_enterprise_assignment
from setp_solver.instance_loader import Instance, Node, RoadProfileMatrices
from setp_solver.model_config import (
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    ModelConfig,
)
from setp_solver.mapping_identity import mapping_sha256
from setp_solver.pi0_manifest import load_pi0_manifest
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    prepare_multitrip_solution,
    route_timing,
)
from setp_solver.search.fleet import route_ev_energy_summary
from setp_solver.cost import time_profile_rows_for_node
from setp_solver.field_rename_compat import (
    configured_depot_gun_count,
    resolve_calendar_path,
)
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    cut_certificate_at_trigger,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict, solution_to_dict
from setp_solver.solution import Route, Solution

INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"
SEED = 11
ARM = "one-cycle-real-input-wiring-trial"
PROBE_SUCCESS_VERDICT = "PROBE_RUN_COMPLETE"
PROBE_FAILURE_VERDICT = "PROBE_RUN_FAILED"
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/algorithms/problem_hgs/charging.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py",
)
ENTERPRISE_NATIVE_PROBE_EXPECTATIONS = {
    "ENT_A": (25, 6597.0),
    "ENT_B": (25, 6667.0),
}

_FULL_EVALUATION_ACCEPTANCE_CHANNELS = frozenset(
    {"duty_crossover", "hgs_population", "route_layer_crossover"}
)


def _sentinel_acceptance_classification(
    accepted_actions: Mapping[str, int],
) -> dict[str, dict[str, int]]:
    """Separate complete-evaluation acceptances from education acceptances."""

    return {
        "incremental_education": {
            channel: int(count)
            for channel, count in sorted(accepted_actions.items())
            if channel not in _FULL_EVALUATION_ACCEPTANCE_CHANNELS and count
        },
        "full_evaluation": {
            channel: int(count)
            for channel, count in sorted(accepted_actions.items())
            if channel in _FULL_EVALUATION_ACCEPTANCE_CHANNELS and count
        },
    }


def _sentinel_validation_failures(
    *,
    accepted_actions: Mapping[str, int],
    sentinel_enabled: bool,
    sentinel_evaluations: int,
) -> tuple[str, ...]:
    """Apply the existing truth gate only to incremental education accepts."""

    classification = _sentinel_acceptance_classification(accepted_actions)
    accepted_education_moves = sum(
        classification["incremental_education"].values()
    )
    failures: list[str] = []
    if sentinel_enabled and accepted_education_moves > 0 and sentinel_evaluations <= 0:
        failures.append(
            "an accepted education move was not replayed by the full-truth sentinel"
        )
    if not sentinel_enabled and sentinel_evaluations != 0:
        failures.append("disabled full-truth sentinel was still exercised")
    return tuple(failures)
FLEET_PARAMETER_CLASSES = {
    "fixed25": FIXED_25_PERCENT_FLEET_PARAMETERS,
    "endogenous": ENDOGENOUS_FLEET_PARAMETERS,
}
MECHANISM_NAMES = frozenset(
    {"cross_depot", "multi_trip", "type_exchange", "charge_timing"}
)
DEPOT_SWAP_INSTANCE_ID = "cn-jjj-50c-01-V3-TWO-SHIFT-DEPOTSWAP"
DEPOT_SWAP_PACKAGE = Path(
    "data/ChinaInstances/china81_instance_depot_swap_jjj_v1_20260813"
)
DEPOT_SWAP_RUNTIME_PARAMETER_AUTHORITY = Path(
    "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)
DEPOT_SEARCH_INSTANCE_ID = "cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_registered_initial_solution(path: Path, bundle: China81Bundle) -> DutyIndividual:
    payload = json.loads(path.read_text(encoding="utf-8"))
    solution_payload = payload.get("evaluation", {}).get("prepared_solution", payload)
    customer_ids = (
        node.node_id for node in bundle.instance.nodes if node.node_type == "c"
    )
    individual = DutyIndividual.from_solution(
        solution_from_dict(solution_payload),
        customer_node_ids=customer_ids,
        source=f"external-initial/{_sha256(path)}",
    )
    return register_all_vehicle_slots(individual, bundle)


def _format_full_evaluation_result(
    *,
    feasible: bool,
    violation_count: int,
) -> str:
    status = "可行" if feasible else "不可行"
    return f"完整评价判定{status}，违规数为 {violation_count}"


def _probe_charging_candidate(
    record: ScheduleCaptureRecord,
    *,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> dict[str, Any]:
    """Replay one captured raw candidate without changing search decisions."""

    try:
        repaired = repair_changed_duties(
            record.reference,
            record.raw_candidate,
            changed_duty_ids=set(record.changed_duty_ids),
            context=context,
            policy=policy,
            cache=None,
        )
        full = DutyFullEvaluator(context).evaluate(repaired)
    except (TypeError, ValueError) as error:
        return {
            "feasible": False,
            "reason_code": charging_rejection_reason(error),
            "error_type": type(error).__name__,
            "error": str(error),
            "repaired_fingerprint": None,
            "full_evaluation_feasible": None,
        }
    if not full.feasible:
        return {
            "feasible": False,
            "reason_code": "FULL_EVALUATION_INFEASIBLE",
            "error_type": "FullEvaluation",
            "error": "; ".join(
                str(asdict(violation)) for violation in full.violations
            ),
            "repaired_fingerprint": repaired.fingerprint,
            "full_evaluation_feasible": False,
        }
    return {
        "feasible": True,
        "reason_code": None,
        "error_type": None,
        "error": None,
        "repaired_fingerprint": repaired.fingerprint,
        "full_evaluation_feasible": True,
    }


def _write_charging_diagnosis_probe(
    records: list[ScheduleCaptureRecord],
    *,
    output: Path,
    context: DutyEvaluationContext,
    policy: ChargingRepairPolicy,
) -> None:
    """Save raw crossover failures, then run relaxed and frvcpy replays."""

    output.mkdir(parents=True, exist_ok=True)
    snapshots = output / "duty_crossover_rejected_candidates.jsonl"
    relaxed_context = replace(context, depot_charge_window_mode="full_gap")
    relaxed_policy = replace(
        policy,
        depot_charge_window_mode="full_gap",
        first_trip_prev_night_enabled=True,
    )
    frvcpy_policy = replace(relaxed_policy, frvcpy_enabled=True)
    rows: list[dict[str, Any]] = []
    with snapshots.open("x", encoding="utf-8") as handle:
        for index, record in enumerate(records, start=1):
            case_id = f"DCX-{index:03d}"
            handle.write(
                json.dumps(
                    {
                        "case_id": case_id,
                        "capture_order": index,
                        "iteration": record.iteration,
                        "channel": record.channel,
                        "action_id": record.action_id,
                        "reference_fingerprint": record.reference.fingerprint,
                        "raw_candidate_fingerprint": (
                            record.raw_candidate.fingerprint
                        ),
                        "changed_duty_ids": sorted(record.changed_duty_ids),
                        "original_error_type": record.a0_error_type,
                        "original_error": record.a0_error,
                        "reference": asdict(record.reference),
                        "raw_candidate": asdict(record.raw_candidate),
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )
    for index, record in enumerate(records, start=1):
        case_id = f"DCX-{index:03d}"
        original = _probe_charging_candidate(
            record,
            context=context,
            policy=policy,
        )
        relaxed = _probe_charging_candidate(
            record,
            context=relaxed_context,
            policy=relaxed_policy,
        )
        frvcpy = _probe_charging_candidate(
            record,
            context=relaxed_context,
            policy=frvcpy_policy,
        )
        rows.append(
            {
                "case_id": case_id,
                "capture_order": index,
                "iteration": record.iteration,
                "raw_candidate_fingerprint": (
                    record.raw_candidate.fingerprint
                ),
                "changed_duty_ids": ";".join(
                    sorted(record.changed_duty_ids)
                ),
                "original_reason_code": charging_rejection_reason(
                    ValueError(record.a0_error or "")
                ),
                "original_error_type": record.a0_error_type,
                "original_error": record.a0_error,
                "original_replay_feasible_60kw": original["feasible"],
                "original_replay_reason_code": original["reason_code"],
                "relaxed_window_mode": "full_gap",
                "relaxed_prev_night_enabled": True,
                "relaxed_60kw_feasible": relaxed["feasible"],
                "relaxed_60kw_reason_code": relaxed["reason_code"],
                "became_feasible_60kw": (
                    not bool(original["feasible"])
                    and bool(relaxed["feasible"])
                ),
                "higher_power_scenario_available": False,
                "frvcpy_feasible_60kw": frvcpy["feasible"],
                "frvcpy_reason_code": frvcpy["reason_code"],
                "frvcpy_overruled_self_repair": (
                    not bool(original["feasible"])
                    and bool(frvcpy["feasible"])
                ),
            }
        )
    fields = tuple(rows[0]) if rows else (
        "case_id",
        "capture_order",
        "iteration",
        "raw_candidate_fingerprint",
        "changed_duty_ids",
        "original_reason_code",
        "original_error_type",
        "original_error",
        "original_replay_feasible_60kw",
        "original_replay_reason_code",
        "relaxed_window_mode",
        "relaxed_prev_night_enabled",
        "relaxed_60kw_feasible",
        "relaxed_60kw_reason_code",
        "became_feasible_60kw",
        "higher_power_scenario_available",
        "frvcpy_feasible_60kw",
        "frvcpy_reason_code",
        "frvcpy_overruled_self_repair",
    )
    with (output / "relaxation_probe.csv").open(
        "x", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)




def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _policy(
    evaluator: DutyFullEvaluator,
    *,
    first_trip_prev_night_enabled: bool = False,
    charge_timing_policy: str = "cost_plus_carbon",
    frvcpy_enabled: bool = False,
) -> ChargingRepairPolicy:
    return ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
        first_trip_prev_night_enabled=first_trip_prev_night_enabled,
        frvcpy_enabled=frvcpy_enabled,
    )


def _parameters(
    *,
    random_seed: int = SEED,
    stagnation_patience: int = 500,
    crossover_mode: str = "fast_only",
    population_mode: str = "copied_hgs_defaults",
    objective_mode: str = SINGLE_OBJECTIVE,
    education_depth_limit: int | None = None,
) -> ProblemHGSSearchParameters:
    if population_mode == "copied_hgs_defaults":
        population = PopulationParameters.copied_hgs_defaults()
    elif population_mode == "technical_two_parent":
        population = PopulationParameters(
            min_pop_size=4,
            generation_size=2,
            num_elite=1,
            num_close=1,
            tournament_size=2,
            lb_diversity=0.0,
            ub_diversity=1.0,
        )
    else:
        raise ValueError(f"unknown population mode: {population_mode}")
    return ProblemHGSSearchParameters(
        random_seed=int(random_seed),
        population=population,
        stagnation_patience=stagnation_patience,
        crossover_mode=crossover_mode,
        objective_mode=objective_mode,
        education_depth_limit=education_depth_limit,
    )


def _effective_population_metadata(
    mode: str,
    population: PopulationParameters,
) -> dict[str, Any]:
    """Record the named mode and every effective population parameter."""

    return {
        "mode": mode,
        "min_pop_size": population.min_pop_size,
        "generation_size": population.generation_size,
        "max_pop_size": population.max_pop_size,
        "num_elite": population.num_elite,
        "num_close": population.num_close,
        "tournament_size": population.tournament_size,
        "lb_diversity": population.lb_diversity,
        "ub_diversity": population.ub_diversity,
    }


def _installed_version(distribution: str) -> str | None:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return None


def _installed_distribution_identity(distribution: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": _installed_version(distribution),
        "modules": {},
        "distribution_records": {},
    }
    for module_name in (
        "setp_hgs_kernel",
        "setp_hgs_kernel.search",
        "setp_hgs_kernel._setp_hgs_kernel",
        "setp_hgs_kernel.search._search",
    ):
        module = importlib.import_module(module_name)
        module_path = Path(module.__file__).resolve()
        result["modules"][module_name] = {
            "path": str(module_path),
            "sha256": _sha256(module_path),
        }
    try:
        dist = importlib_metadata.distribution(distribution)
    except importlib_metadata.PackageNotFoundError:
        result["distribution_installed"] = False
        return result
    result["distribution_installed"] = True
    for relative in dist.files or ():
        name = str(relative)
        if not name.endswith((".dist-info/METADATA", ".dist-info/RECORD")):
            continue
        path = Path(dist.locate_file(relative)).resolve()
        result["distribution_records"][name] = {
            "path": str(path),
            "sha256": _sha256(path),
        }
    return result


def _source_provenance(
    repo: Path,
    *,
    output_path: Path,
    stderr_capture_state: str,
) -> dict[str, Any]:
    package = repo / "solver/src/setp_solver/algorithms/problem_hgs"
    vendor = repo / "third_party/setp_hgs_kernel"
    files = sorted(
        (
            *(
                path
                for path in package.rglob("*.py")
                if "__pycache__" not in path.parts
                and not path.name.startswith("._")
            ),
            Path(__file__).resolve(),
            vendor / "UPSTREAM_COMMIT",
            vendor / "LICENSE.md",
            vendor / "meson.build",
            vendor / "pyproject.toml",
        ),
        key=str,
    )
    manifest = {
        str(path.relative_to(repo)): _sha256(path)
        for path in files
    }
    manifest_payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    status = _git(repo, "status", "--porcelain")
    return {
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "worktree_clean_before_run": not bool(status),
        "worktree_status_before_run": status,
        "python_source_sha256": hashlib.sha256(manifest_payload).hexdigest(),
        "python_source_files": manifest,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "dependency_versions": {
            name: _installed_version(name)
            for name in ("numpy", "scipy", "setp-hgs-kernel")
        },
        "kernel_runtime_identity": _installed_distribution_identity(
            "setp-hgs-kernel"
        ),
        "pyvrp_importable": importlib.util.find_spec("pyvrp") is not None,
        "cwd": str(Path.cwd().resolve()),
        "command_argv": list(sys.argv),
        "output_path": str(output_path),
        "stderr_capture_state": stderr_capture_state,
    }


def _build_context(
    repo: Path,
    instance_id: str = INSTANCE_ID,
    *,
    fleet_parameters: China81FleetParameterClass = (
        FIXED_25_PERCENT_FLEET_PARAMETERS
    ),
    depot_charging_scenario_name: str = "60kw",
):
    if instance_id.endswith("-V3-TWO-SHIFT-DP"):
        if depot_charging_scenario_name != "60kw":
            raise ValueError("DP suite is frozen at the 60 kW depot scenario")
        return _build_saved_suite_context(
            repo,
            instance_id,
            package_root=repo / "data/ChinaInstances/china81_depotpair_rebuild_v1_20260812",
            report_root=repo / "solver/reports/suite_depotpair_rebuild_20260812",
            fleet_parameters=fleet_parameters,
        )
    if instance_id.endswith("-V3-TWO-SHIFT-PRDFIX"):
        if depot_charging_scenario_name != "60kw":
            raise ValueError("PRDFIX suite is frozen at the 60 kW depot scenario")
        return _build_saved_suite_context(
            repo,
            instance_id,
            package_root=repo / "data/ChinaInstances/china81_suite_prd_fix_v1_20260812",
            report_root=repo / "solver/reports/suite_prd_fix_20260812",
            fleet_parameters=fleet_parameters,
        )
    if instance_id == DEPOT_SEARCH_INSTANCE_ID:
        if depot_charging_scenario_name != "60kw":
            raise ValueError(
                "DEPOTSEARCH instance is frozen at the 60 kW depot scenario"
            )
        return _build_saved_suite_context(
            repo,
            instance_id,
            package_root=repo / "data/ChinaInstances/china81_final_suite_v2_20260815",
            report_root=repo / "solver/reports/instance_build_only_d996f755bd_20260815",
            fleet_parameters=fleet_parameters,
        )

    from setp_solver.private_instance_rebuild_20260811 import (
        DEPOT_CHARGING_SCENARIOS,
        EV_DAILY_FIXED_PREMIUM_CNY,
        INSTANCE_ID as REBUILT_INSTANCE_ID,
        load_private_instance_rebuild,
    )

    if instance_id == REBUILT_INSTANCE_ID:
        rebuilt = load_private_instance_rebuild(
            repo,
            fleet_parameters=fleet_parameters,
            depot_charging_scenario=DEPOT_CHARGING_SCENARIOS[
                depot_charging_scenario_name
            ],
        )
        bundle = rebuilt.china81
        skeleton = _private_rebuild_health_witness_initial(repo, bundle)
        individual = _with_registered_idle_duties(
            DutyIndividual.from_solution(skeleton),
            bundle,
        )
        neutral = {
            node.node_id: 1.0
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        }
        shift_windows = {
            shift_id: (
                float(row["start_minute"]) * 60.0,
                float(row["end_minute"]) * 60.0,
            )
            for shift_id, row in rebuilt.shift_contract["shifts"].items()
        }
        context = DutyEvaluationContext(
            bundle=bundle,
            independent_profit=neutral,
            independent_profit_identity=FrozenMappingIdentity(
                source_id="fairness-disabled-neutral-not-pi0",
                value_sha256=mapping_sha256(neutral),
                externally_frozen=False,
            ),
            prior_profit={depot_id: 0.0 for depot_id in neutral},
            theta=0.0,
            carbon_quota_kg=0.0,
            depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
            fairness_enabled=False,
            ev_daily_fixed_premium_cny=EV_DAILY_FIXED_PREMIUM_CNY,
            shift_aware_departure_enabled=True,
            rebuilt_route_constraints=RebuiltRouteConstraintContract(
                source_id="china81_private_rebuild_v1_20260811/shift_contract.json",
                customer_shift_by_id={
                    customer_id: str(row["shift_id"])
                    for customer_id, row in rebuilt.orders_by_customer.items()
                },
                customer_volume_m3_by_id={
                    customer_id: float(row["source_volume_m3"])
                    for customer_id, row in rebuilt.orders_by_customer.items()
                },
                shift_window_second_by_id=shift_windows,
                vehicle_volume_capacity_m3=float(
                    rebuilt.shift_contract["vehicle_volume_capacity_m3"]
                ),
            ),
        )
        return bundle, individual, neutral, context

    bundle = load_china81_bundle(
        repo,
        instance_id,
        fleet_parameters=fleet_parameters,
    )
    skeleton = _registered_finite_fleet_initial(repo, bundle)
    completed = complete_china81_route_skeleton(skeleton, bundle).solution
    individual = _with_registered_idle_duties(
        DutyIndividual.from_solution(completed),
        bundle,
    )
    profits = calculate_depot_profits(
        completed,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        customer_home_depot=dict(bundle.customer_home_depot),
    )
    pi0 = {depot_id: row.profit for depot_id, row in profits.items()}
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=pi0,
        independent_profit_identity=FrozenMappingIdentity(
            source_id="technical-initial-solution-derived-before-search",
            value_sha256=mapping_sha256(pi0),
            externally_frozen=False,
        ),
        prior_profit={depot_id: 0.0 for depot_id in pi0},
        theta=1.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    )
    return bundle, individual, pi0, context


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _apply_joint_pi0_record(
    bundle: China81Bundle,
    context: DutyEvaluationContext,
    record: Mapping[str, Any],
) -> tuple[dict[str, float], DutyEvaluationContext]:
    """Attach one validated two-depot Pi0 record to the joint context."""

    pi0 = {
        str(key): float(value)
        for key, value in dict(record["values"]).items()
    }
    depots = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    }
    if set(pi0) != depots:
        raise ValueError(
            "Pi0 depot set differs from the joint private problem: "
            f"expected={sorted(depots)}, actual={sorted(pi0)}"
        )
    if mapping_sha256(pi0) != str(record["value_sha256"]).lower():
        raise ValueError("Pi0 content hash differs from the supplied record")
    if record.get("externally_frozen") is not True:
        raise ValueError("joint participation requires externally frozen Pi0")
    return pi0, replace(
        context,
        independent_profit=pi0,
        independent_profit_identity=FrozenMappingIdentity(
            source_id=str(record["source_id"]),
            value_sha256=str(record["value_sha256"]),
            externally_frozen=True,
        ),
        theta=1.0,
        fairness_enabled=True,
    )


def _suite_matrix_from_reference(
    path: Path,
    *,
    target_node_ids: Sequence[str],
    source_node_by_target: Mapping[str, str],
) -> tuple[tuple[float, ...], ...]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows or len(rows[0]) < 2 or not rows[0][0].strip():
        raise ValueError(f"suite matrix has no row-id corner cell: {path}")
    column_ids = rows[0][1:]
    values = {
        row[0]: {column_id: float(value) for column_id, value in zip(column_ids, row[1:], strict=True)}
        for row in rows[1:]
    }
    source_ids = [source_node_by_target[node_id] for node_id in target_node_ids]
    if set(source_ids) != set(column_ids) or set(values) != set(column_ids):
        raise ValueError(f"suite matrix node identity differs from source mapping: {path}")
    return tuple(
        tuple(values[left][right] for right in source_ids)
        for left in source_ids
    )


def _load_v3_suite_bundle(
    repo: Path,
    *,
    package_root: Path,
    instance_id: str,
    fleet_parameters: China81FleetParameterClass,
) -> tuple[China81Bundle, Mapping[str, Mapping[str, str]]]:
    """Load a V3 suite only from its sealed package and shared runtime authority.

    The construction scripts retain historical source identities for
    provenance, but a runtime lane must not call the generic China81 loader on
    an old V2 instance or old finite-fleet authority.  This adapter therefore
    reads the target package's nodes, orders, fleet caps, and matrix reference
    directly, then joins the approved shared runtime parameter calendar.
    """

    from setp_solver.china81 import FLEET_CAP_SEMANTICS

    saved_root = package_root / "instances" / instance_id
    catalog_rows = [
        row
        for row in _csv_rows(package_root / "instance_catalog.csv")
        if row["instance_id"] == instance_id
    ]
    if len(catalog_rows) != 1:
        raise ValueError(f"V3 suite catalog row is not unique for {instance_id}")
    catalog = catalog_rows[0]
    node_rows = _csv_rows(saved_root / "nodes.csv")
    order_rows = _csv_rows(saved_root / "orders.csv")
    orders_by_customer = {
        row["customer_id"]: row for row in order_rows
    }
    if len(orders_by_customer) != len(order_rows):
        raise ValueError(f"V3 suite has duplicate customers for {instance_id}")
    expected_customers = int(catalog["customer_count"])
    if len(order_rows) != expected_customers:
        raise ValueError(f"V3 suite order count disagrees for {instance_id}")

    fleet_rows = [
        row
        for row in _csv_rows(package_root / "fleet_caps.csv")
        if row["instance_id"] == instance_id
    ]
    if not fleet_rows:
        raise ValueError(f"V3 suite fleet rows are missing for {instance_id}")
    fleet_caps = MappingProxyType(
        {
            row["depot_id"]: MappingProxyType(
                dict(fleet_parameters.depot_caps(row))
            )
            for row in fleet_rows
        }
    )
    if {row["fleet_parameter_class"] for row in fleet_rows} != {
        fleet_parameters.parameter_class_id
    }:
        raise ValueError(f"V3 suite fleet class disagrees for {instance_id}")

    facilities_path = package_root / "facilities.csv"
    if not facilities_path.is_file():
        facilities_path = package_root / "source_pools" / "facilities.csv"
    facilities = {
        row["city"].strip().lower(): row
        for row in _csv_rows(facilities_path)
    }
    station_assignments = {
        row["station_id"]: row
        for row in (
            _csv_rows(package_root / "station_parameter_assignments.csv")
            if (package_root / "station_parameter_assignments.csv").is_file()
            else []
        )
    }
    assignment_path = saved_root / "enterprise_assignment.csv"
    assignment = None
    if assignment_path.is_file():
        assignment = load_enterprise_assignment(
            assignment_path,
            saved_root / "nodes.csv",
            expected_instance_id=instance_id,
            expected_customer_ids=orders_by_customer,
        )
        customer_home_depot = assignment.customer_home_depot
    else:
        if "-DEPOTSEARCH-" in instance_id:
            raise ValueError(
                "ASSIGNMENT_CONTRACT_ERROR: DEPOTSEARCH requires "
                f"{assignment_path}"
            )
        customer_home_depot = MappingProxyType(
            {
                customer_id: str(row["home_depot_id"])
                for customer_id, row in orders_by_customer.items()
            }
        )
    nodes: list[Node] = []
    for row in node_rows:
        node_id = str(row["node_id"])
        node_type = str(row["node_type"]).strip().lower()
        city = str(row["city"]).strip().lower()
        common = {
            "node_id": node_id,
            "x": float(row["longitude"]),
            "y": float(row["latitude"]),
            "city": city,
        }
        facility = facilities[city]
        if node_type == "depot":
            fleet = next(item for item in fleet_rows if item["depot_id"] == node_id)
            nodes.append(
                Node(
                    node_type="d",
                    ready_time=float(CHINA81_HORIZON_START_SECOND),
                    due_time=float(CHINA81_HORIZON_END_SECOND),
                    charge_power_kw=float(fleet["depot_charge_power_kw"]),
                    station_chargers=None,
                    **common,
                )
            )
        elif node_type == "station":
            station = station_assignments.get(node_id)
            nodes.append(
                Node(
                    node_type="f",
                    ready_time=float(CHINA81_HORIZON_START_SECOND),
                    due_time=float(CHINA81_HORIZON_END_SECOND),
                    charge_power_kw=float(
                        station["power_kw"]
                        if station is not None
                        else facility["station_power_kw"]
                    ),
                    station_chargers=int(
                        station["gun_count"]
                        if station is not None
                        else facility["station_gun_count"]
                    ),
                    **common,
                )
            )
        elif node_type == "customer":
            order = orders_by_customer[node_id]
            nodes.append(
                Node(
                    node_type="c",
                    demand=float(order["demand_kg"]),
                    ready_time=float(order["time_window_early_minute"]) * 60.0,
                    due_time=float(order["time_window_late_minute"]) * 60.0,
                    service_time=float(order["service_minutes"]) * 60.0,
                    **common,
                )
            )
        else:
            raise ValueError(f"V3 suite has unsupported node type {node_type!r}")

    source_mapping = {
        row["new_node_id"]: row["source_node_id"]
        for row in _csv_rows(saved_root / "source_mapping.csv")
    }
    target_node_ids = [node.node_id for node in nodes]
    if set(source_mapping) != set(target_node_ids):
        raise ValueError(f"V3 suite source mapping is incomplete for {instance_id}")
    reference = json.loads(
        (saved_root / "matrix_reference.json").read_text(encoding="utf-8")
    )
    matrix_authority = repo / str(reference["source_authority"])
    if not matrix_authority.is_dir():
        # DP's reference was written against a temporary construction path;
        # the sealed package contains the same frozen matrix under this path.
        matrix_authority = package_root / "directed_matrices"
    matrix_instance_id = str(reference["source_instance_id"])
    matrix_root = matrix_authority / "instances" / matrix_instance_id
    profiles = {
        profile: RoadProfileMatrices(
            distance_m=_suite_matrix_from_reference(
                matrix_root / profile / "road_distance_m.csv",
                target_node_ids=target_node_ids,
                source_node_by_target=source_mapping,
            ),
            duration_s=_suite_matrix_from_reference(
                matrix_root / profile / "road_duration_s.csv",
                target_node_ids=target_node_ids,
                source_node_by_target=source_mapping,
            ),
            sum_v2d_m3_s2=_suite_matrix_from_reference(
                matrix_root / profile / "road_sum_v2d_m3_s2.csv",
                target_node_ids=target_node_ids,
                source_node_by_target=source_mapping,
            ),
        )
        for profile in ("cv", "ev")
    }
    cost_contract_path = package_root / "vehicle_cost_contract.json"
    if cost_contract_path.is_file():
        cost_contract = json.loads(
            cost_contract_path.read_text(encoding="utf-8")
        )
        fixed_costs = {
            "cv": float(cost_contract["cv"]["daily_fixed_cny"]),
            "ev": float(cost_contract["ev"]["daily_fixed_cny"]),
        }
    else:
        cost_rows = {
            row["vehicle_type"]: row
            for row in _csv_rows(
                repo
                / "data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv"
            )
        }
        fixed_costs = {
            "cv": float(cost_rows["cv"]["effective_daily_fixed_cost_cny"]),
            "ev": float(cost_rows["ev"]["effective_daily_fixed_cost_cny"]),
        }
    vehicle_parameters = _china_vehicle_parameters(fixed_costs)
    num_cv = sum(int(caps["num_cv"]) for caps in fleet_caps.values())
    num_ev = sum(int(caps["num_ev"]) for caps in fleet_caps.values())
    instance = Instance(
        nodes=nodes,
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        num_cv=num_cv,
        num_ev=num_ev,
        road_profiles=profiles,
        vehicle_parameters=vehicle_parameters,
        demand_mass_per_unit_kg=1.0,
    )
    cities = {
        str(node.city).strip().lower()
        for node in nodes
        if node.city is not None
    }
    runtime_root = repo / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
    time_profile = _load_time_profile(
        resolve_calendar_path(runtime_root),
        cities=cities,
        date="2025-02-12",
        require_explicit_mapping=True,
    )
    runtime_binding = _city_runtime_binding_from_profile(
        time_profile,
        cities=cities,
        date="2025-02-12",
    )
    diesel_prices = _diesel_price_map_from_profile(
        time_profile,
        cities=cities,
        date="2025-02-12",
    )
    prices = _china_prices(
        time_profile,
        diesel_price_by_city=diesel_prices,
        vehicle_parameters=vehicle_parameters,
    )
    charger_scenario = MappingProxyType(
        {
            node.node_id: MappingProxyType(
                {
                    "charger_count": (
                        configured_depot_gun_count(
                            next(
                                item
                                for item in fleet_rows
                                if item["depot_id"] == node.node_id
                            )
                        )
                        if node.node_type == "d"
                        else int(node.station_chargers or 0)
                    ),
                    "active_concurrency_limit": (
                        "UNBOUNDED" if node.node_type == "d" else int(node.station_chargers or 0)
                    ),
                    "capacity_mode": "unbounded" if node.node_type == "d" else "finite_instance",
                    "charge_power_kw": float(node.charge_power_kw),
                    "parameter_class": (
                        next(item for item in fleet_rows if item["depot_id"] == node.node_id)["charger_parameter_class"]
                        if node.node_type == "d"
                        else (
                            station_assignments[node.node_id]["parameter_class"]
                            if node.node_id in station_assignments
                            else facilities[str(node.city)]["station_parameter_class"]
                        )
                    ),
                }
            )
            for node in nodes
            if node.node_type in {"d", "f"}
        }
    )
    source_paths = {
        "catalog": str((package_root / "instance_catalog.csv").relative_to(repo)),
        "nodes": str((saved_root / "nodes.csv").relative_to(repo)),
        "orders": str((saved_root / "orders.csv").relative_to(repo)),
        "road_matrices": str(matrix_root.relative_to(repo)),
        "tariff_carbon_calendar": str(
            resolve_calendar_path(runtime_root).relative_to(repo)
        ),
        "vehicle_cost_authority": str(
            (
                cost_contract_path
                if cost_contract_path.is_file()
                else repo / "data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv"
            ).relative_to(repo)
        ),
        "finite_fleet_authority": str(
            (package_root / "fleet_caps.csv").relative_to(repo)
        ),
        "facilities": str(facilities_path.relative_to(repo)),
    }
    if assignment is not None:
        source_paths["enterprise_assignment"] = str(
            assignment_path.relative_to(repo)
        )
    bundle = China81Bundle(
        instance_id=instance_id,
        region=str(catalog["region"]).strip().lower(),
        date="2025-02-12",
        instance=instance,
        time_profile=time_profile,
        prices=prices,
        source_paths=MappingProxyType(source_paths),
        customer_home_depot=customer_home_depot,
        price_area_by_city=MappingProxyType(
            {city: runtime_binding[city]["price_area_id"] for city in sorted(cities)}
        ),
        carbon_source_column_by_city=MappingProxyType(
            {city: runtime_binding[city]["carbon_source_column"] for city in sorted(cities)}
        ),
        diesel_zone_by_city=MappingProxyType(
            {city: runtime_binding[city]["diesel_zone"] for city in sorted(cities)}
        ),
        diesel_price_by_city=MappingProxyType(diesel_prices),
        fleet_caps_by_depot=fleet_caps,
        fleet_parameter_class_id=fleet_parameters.parameter_class_id,
        has_additional_total_fleet_cap=fleet_parameters.has_additional_total_fleet_cap,
        charger_scenario_by_node=charger_scenario,
        fleet_cap_semantics=FLEET_CAP_SEMANTICS,
        diesel_price_source_id="CHINA-E3-FORMAL-RELEASE-001__2025-02-12_CITY_DEPOT_PRICE",
        static_input_authority=str(package_root.relative_to(repo)),
        road_matrix_authority=str(matrix_authority.relative_to(repo)),
        runtime_parameter_authority=str(runtime_root.relative_to(repo)),
        fleet_authority=str(package_root.relative_to(repo)),
        model_config=MappingProxyType(ModelConfig().as_metadata()),
        formal_search_allowed=False,
        enterprise_assignment_by_customer=(
            assignment.enterprise_by_customer
            if assignment is not None
            else MappingProxyType({})
        ),
        enterprise_assignment_source_path=(
            str(assignment_path.relative_to(repo))
            if assignment is not None
            else None
        ),
        enterprise_assignment_source_sha256=(
            assignment.source_sha256 if assignment is not None else None
        ),
        enterprise_assignment_mapping_sha256=(
            assignment.normalized_mapping_sha256 if assignment is not None else None
        ),
        enterprise_assignment_rule_ids=(
            assignment.rule_ids if assignment is not None else ()
        ),
    )
    return bundle, orders_by_customer




def _suite_context_from_built(
    repo: Path,
    instance_id: str,
    *,
    package_root: Path,
    report_root: Path,
    built: Any,
    template: Any,
    matrix_authority: str,
    fleet_parameters: China81FleetParameterClass,
):
    """Turn one saved V3 two-shift construction into a private context."""

    from setp_solver.private_instance_rebuild_20260811 import (
        EV_DAILY_FIXED_PREMIUM_CNY,
    )

    saved_root = package_root / "instances" / instance_id
    shift_contract = json.loads(
        (saved_root / "shift_contract.json").read_text(encoding="utf-8")
    )
    shift_windows = {
        shift_id: (
            float(row["start_minute"]) * 60.0,
            float(row["end_minute"]) * 60.0,
        )
        for shift_id, row in shift_contract["shifts"].items()
    }
    fleet_rows = [
        row
        for row in _csv_rows(package_root / "fleet_caps.csv")
        if row["instance_id"] == instance_id
    ]
    if not fleet_rows:
        raise ValueError(f"suite fleet rows are missing for {instance_id}")
    if {row["fleet_parameter_class"] for row in fleet_rows} != {
        fleet_parameters.parameter_class_id
    }:
        raise ValueError(f"suite fleet class disagrees for {instance_id}")
    fleet_caps = MappingProxyType(
        {
            row["depot_id"]: MappingProxyType(
                {
                    "num_cv": int(row["base_all_cv_routes_Rd"]),
                    "num_ev": int(row["base_all_ev_routes_Re"]),
                    "total_fleet_cap": (
                        int(row["base_all_cv_routes_Rd"])
                        + int(row["base_all_ev_routes_Re"])
                    ),
                }
            )
            for row in fleet_rows
        }
    )
    instance = replace(
        built.instance,
        num_cv=sum(caps["num_cv"] for caps in fleet_caps.values()),
        num_ev=sum(caps["num_ev"] for caps in fleet_caps.values()),
    )
    if instance.num_cv < 1 or instance.num_ev < 1:
        raise ValueError(f"suite fleet caps have no active mixed fleet for {instance_id}")
    depot_charger_scenario = {
            row["depot_id"]: MappingProxyType(
                {
                    "charger_count": configured_depot_gun_count(row),
                    "active_concurrency_limit": "UNBOUNDED",
                    "capacity_mode": "unbounded",
                    "charge_power_kw": float(row["depot_charge_power_kw"]),
                    "parameter_class": row["charger_parameter_class"],
                }
            )
            for row in fleet_rows
        }
    public_station_ids = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() == "f"
    }
    charger_scenario = MappingProxyType(
        {
            **{
                node_id: template.charger_scenario_by_node[node_id]
                for node_id in public_station_ids
            },
            **depot_charger_scenario,
        }
    )
    bundle = replace(
        template,
        instance_id=instance_id,
        region=built.identity.region,
        instance=instance,
        time_profile=list(built.time_profile),
        prices=built.prices,
        source_paths=MappingProxyType(
            {
                **dict(template.source_paths),
                "suite": str(package_root.relative_to(repo)),
                "instance": str(saved_root.relative_to(repo)),
                "matrix_reference": str(
                    (saved_root / "matrix_reference.json").relative_to(repo)
                ),
                "health_witness_routes": str(
                    (report_root / "health_witness_routes.csv").relative_to(repo)
                ),
                "shift_contract": str(
                    (saved_root / "shift_contract.json").relative_to(repo)
                ),
            }
        ),
        customer_home_depot=built.customer_home_depot,
        fleet_caps_by_depot=fleet_caps,
        fleet_parameter_class_id=fleet_parameters.parameter_class_id,
        has_additional_total_fleet_cap=fleet_parameters.has_additional_total_fleet_cap,
        charger_scenario_by_node=charger_scenario,
        static_input_authority=str(package_root.relative_to(repo)),
        road_matrix_authority=matrix_authority,
        fleet_authority=str(package_root.relative_to(repo)),
        formal_search_allowed=False,
    )
    individual = adapt_witness_rows_to_duty(
        (
            row
            for row in _csv_rows(report_root / "health_witness_routes.csv")
            if row["instance_id"] == instance_id
        ),
        instance_id=instance_id,
        bundle=bundle,
        register_idle_duties=_with_registered_idle_duties,
    )
    neutral = {
        node.node_id: 1.0
        for node in bundle.instance.nodes
        if node.node_type.lower() == "d"
    }
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=neutral,
        independent_profit_identity=FrozenMappingIdentity(
            source_id="fairness-disabled-neutral-not-pi0",
            value_sha256=mapping_sha256(neutral),
            externally_frozen=False,
        ),
        prior_profit={depot_id: 0.0 for depot_id in neutral},
        theta=0.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
        fairness_enabled=False,
        ev_daily_fixed_premium_cny=EV_DAILY_FIXED_PREMIUM_CNY,
        shift_aware_departure_enabled=True,
        rebuilt_route_constraints=RebuiltRouteConstraintContract(
            source_id=str((saved_root / "shift_contract.json").relative_to(repo)),
            customer_shift_by_id={
                customer_id: str(row["shift_id"])
                for customer_id, row in built.orders_by_customer.items()
            },
            customer_volume_m3_by_id={
                customer_id: float(row["source_volume_m3"])
                for customer_id, row in built.orders_by_customer.items()
            },
            shift_window_second_by_id=shift_windows,
            vehicle_volume_capacity_m3=float(
                shift_contract["vehicle_volume_capacity_m3"]
            ),
        ),
    )
    return bundle, individual, neutral, context


def _build_saved_suite_context(
    repo: Path,
    instance_id: str,
    *,
    package_root: Path,
    report_root: Path,
    fleet_parameters: China81FleetParameterClass,
):
    """Load any sealed V3 two-shift suite through its package contract."""

    bundle, orders_by_customer = _load_v3_suite_bundle(
        repo,
        package_root=package_root,
        instance_id=instance_id,
        fleet_parameters=fleet_parameters,
    )
    return _suite_context_from_built(
        repo,
        instance_id,
        package_root=package_root,
        report_root=report_root,
        built=SimpleNamespace(
            identity=SimpleNamespace(region=bundle.region),
            instance=bundle.instance,
            time_profile=bundle.time_profile,
            prices=bundle.prices,
            source_bundle=bundle,
            customer_home_depot=bundle.customer_home_depot,
            orders_by_customer=orders_by_customer,
        ),
        template=bundle,
        matrix_authority=bundle.road_matrix_authority,
        fleet_parameters=fleet_parameters,
    )












def _private_rebuild_health_witness_initial(repo: Path, bundle) -> Solution:
    """Load the frozen seed-11 health witness without invoking a solver."""

    path = (
        repo
        / "solver/reports/instance_rebuild_20260811/health_witness_routes.csv"
    )
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("rebuilt health witness is empty")
    if {str(row["seed"]) for row in rows} != {"11"}:
        raise ValueError("rebuilt health witness must be the frozen seed-11 route set")
    routes = [
        Route(
            vehicle_id=str(row["route_vehicle_id"]),
            vehicle_type=(
                "ev"
                if str(row["physical_vehicle_id"]).startswith("EV_")
                else "cv"
            ),
            home_depot_id=str(row["depot_id"]),
            node_sequence=[
                str(row["depot_id"]),
                *str(row["customers"]).split("|"),
                str(row["depot_id"]),
            ],
        )
        for row in rows
    ]
    served = [node_id for route in routes for node_id in route.node_sequence[1:-1]]
    expected = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    if len(served) != len(set(served)) or set(served) != expected:
        raise ValueError("rebuilt health witness does not cover customers exactly once")
    return Solution(routes=routes)


def _registered_finite_fleet_initial(repo: Path, bundle) -> Solution:
    """Load the certified mixed-fleet route skeleton for one China81 input."""

    witness_path = (
        repo
        / bundle.fleet_authority
        / "witnesses"
        / f"{bundle.instance_id}.json"
    )
    witness = json.loads(witness_path.read_text(encoding="utf-8"))
    if str(witness.get("instance_id")) != bundle.instance_id:
        raise RuntimeError("finite-fleet witness belongs to another instance")
    level = witness.get("levels", {}).get("25")
    if not isinstance(level, dict):
        raise TypeError("finite-fleet witness has no registered level 25")
    if level.get("status") != "CERTIFIED" or level.get("violations"):
        raise RuntimeError("finite-fleet level 25 is not certified")

    routes: list[Route] = []
    for depot_id, depot in sorted(level["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            for index, timed in enumerate(
                depot[f"{vehicle_type}_routes"],
                start=1,
            ):
                routes.append(
                    Route(
                        vehicle_id=(
                            f"REGISTERED-INITIAL-{depot_id}-"
                            f"{vehicle_type.upper()}-{index:03d}"
                        ),
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *[str(customer) for customer in timed["customers"]],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def _with_registered_idle_duties(
    individual: DutyIndividual,
    bundle,
) -> DutyIndividual:
    """Represent every registered vehicle, including currently idle assets."""
    return register_all_vehicle_slots(individual, bundle)


def _dynamic_insertion_technical_cut(
    bundle,
    initial: DutyIndividual,
    context: DutyEvaluationContext,
) -> tuple[DutyIndividual, DutyEvaluationContext, str]:
    """Build one controlled 13:00 reveal without reading a truth stream."""

    target_asset = "CV_D_guangzhou_4"
    rebuilt_duties = []
    revealed = None
    for duty in initial.duties:
        if duty.physical_vehicle_id != target_asset:
            rebuilt_duties.append(duty)
            continue
        if not duty.trips or not duty.trips[0].customer_ids:
            raise ValueError("dynamic insertion probe target duty is empty")
        trip = duty.trips[0]
        revealed = trip.customer_ids[-1]
        rebuilt_duties.append(
            replace(
                duty,
                trips=(
                    replace(
                        trip,
                        customer_ids=trip.customer_ids[:-1],
                    ),
                ),
            )
        )
    if revealed is None:
        raise ValueError("dynamic insertion probe target asset is absent")

    partial = replace(
        initial,
        duties=tuple(rebuilt_duties),
        unserved_customers=(revealed,),
        source="dynamic-insertion-technical-cut",
    )
    source_solution, source_certificate = prepare_multitrip_solution(
        partial.to_solution(),
        bundle.instance,
        bundle.prices,
        depot_charge_window_mode=context.depot_charge_window_mode,
    )
    trigger = 46_800.0
    cut = cut_certificate_at_trigger(
        source_solution,
        source_certificate,
        bundle.instance,
        bundle.prices,
        trigger_second=trigger,
    )
    battery_capacity = bundle.instance.battery_capacity_kwh(
        fallback=bundle.prices.B_battery_kwh
    )
    assets = {
        duty.physical_vehicle_id: cut.asset_states.get(
            duty.physical_vehicle_id,
            DynamicAssetState(
                duty.physical_vehicle_id,
                duty.vehicle_type,
                duty.home_depot_id,
                trigger,
                battery_capacity if duty.vehicle_type == "ev" else 0.0,
                1,
            ),
        )
        for duty in initial.duties
    }
    customer_ids = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    committed_route_ids = {
        *cut.completed_route_ids,
        *cut.in_progress_route_ids,
    }
    committed_customers = {
        node_id
        for route in source_solution.routes
        if route.vehicle_id in committed_route_ids
        for node_id in route.node_sequence[1:-1]
        if node_id in customer_ids
    }
    state = DutyDynamicState(
        source_solution=source_solution,
        cut=cut,
        asset_states=MappingProxyType(assets),
        future_customer_ids=frozenset(
            customer_ids.difference(committed_customers)
        ),
        customer_appearance_second={
            customer_id: trigger if customer_id == revealed else 0.0
            for customer_id in customer_ids
        },
        charging_strategy="aware",
        charging_intensity_field="forecast_gco2_per_kwh",
    )
    future = future_individual_from_cut(
        state,
        source_certificate,
        bundle.instance,
    )
    return (
        future,
        replace(
            context,
            dynamic_state=state,
            incremental_full_truth_sentinel_enabled=False,
        ),
        revealed,
    )


def _parse_mechanism_off(value: str) -> frozenset[str]:
    requested = frozenset(
        item.strip() for item in str(value).split(",") if item.strip()
    )
    unknown = sorted(requested.difference(MECHANISM_NAMES))
    if unknown:
        raise ValueError("unknown mechanism group(s): " + ", ".join(unknown))
    return requested


def _customer_structure(
    individual: DutyIndividual,
) -> tuple[dict[str, str], dict[str, str]]:
    depot_by_customer: dict[str, str] = {}
    type_by_customer: dict[str, str] = {}
    for duty in individual.duties:
        for trip in duty.trips:
            for customer in trip.customer_ids:
                depot_by_customer[customer] = duty.home_depot_id
                type_by_customer[customer] = duty.vehicle_type
    return depot_by_customer, type_by_customer


def _string_mapping_sha256(values: Mapping[str, str]) -> str:
    payload = json.dumps(
        sorted((str(key), str(value)) for key, value in values.items()),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _shift_aware_ev_proxy_validation(
    individual: DutyIndividual,
    route_engine: IndependentKernelDutyRouteProposalEngine,
    context: DutyEvaluationContext,
) -> dict[str, object]:
    contract = context.rebuilt_route_constraints
    if contract is None or not route_engine.shift_aware_ev_proxy:
        return {"enabled": False}
    proxy = route_engine.shift_aware_ev_proxy
    per_vehicle: dict[str, dict[str, object]] = {}
    fleet_energy = 0.0
    fleet_cost = 0.0
    fleet_old_cost = 0.0
    for duty in individual.duties:
        if not duty.trips:
            continue
        energy_by_shift: dict[str, float] = {}
        for trip in duty.trips:
            shifts = {
                contract.customer_shift_by_id[customer]
                for customer in trip.customer_ids
            }
            if len(shifts) != 1:
                raise ValueError(
                    "shift-aware proxy validation found a mixed-shift trip"
                )
            shift_id = next(iter(shifts))
            route = Route(
                vehicle_id=duty.physical_vehicle_id,
                vehicle_type="ev",
                home_depot_id=duty.home_depot_id,
                node_sequence=[
                    duty.home_depot_id,
                    *trip.customer_ids,
                    duty.home_depot_id,
                ],
            )
            energy_by_shift[shift_id] = (
                energy_by_shift.get(shift_id, 0.0)
                + float(
                    route_ev_energy_summary(
                        route,
                        context.bundle.instance,
                        context.bundle.prices,
                    ).ev_kwh
                )
            )
        energy = sum(energy_by_shift.values())
        electricity_cost = sum(
            shift_energy
            * float(
                proxy[duty.home_depot_id][shift_id][
                    "electricity_cny_per_kwh"
                ]
            )
            for shift_id, shift_energy in energy_by_shift.items()
        )
        rows = time_profile_rows_for_node(
            context.bundle.instance,
            duty.home_depot_id,
            context.bundle.time_profile,
        )
        old_rate = sum(
            float(row["depot_energy_cny_per_kwh"]) for row in rows
        ) / len(rows)
        unit_rate = electricity_cost / energy
        per_vehicle[duty.physical_vehicle_id] = {
            "energy_kwh_by_shift": energy_by_shift,
            "energy_kwh": energy,
            "electricity_cost_cny": electricity_cost,
            "unit_electricity_cny_per_kwh": unit_rate,
            # Compatibility key: this is the equal-duration daily mean of TOU
            # category prices stored on 48 half-hour integration-grid rows.
            "old_48_slot_mean_cny_per_kwh": old_rate,
        }
        fleet_energy += energy
        fleet_cost += electricity_cost
        fleet_old_cost += energy * old_rate
    old_fleet_rate = fleet_old_cost / fleet_energy
    fleet_rate = fleet_cost / fleet_energy
    return {
        "enabled": True,
        "criterion": (
            "AM energy uses the lowest-carbon pre-first-trip slot; PM energy "
            "uses the lowest-carbon inter-shift lunch slot; vehicle and fleet "
            "rates are route-EV-energy weighted"
        ),
        "per_vehicle": per_vehicle,
        "fleet_energy_kwh": fleet_energy,
        "fleet_unit_electricity_cny_per_kwh": fleet_rate,
        "old_48_slot_mean_cny_per_kwh": old_fleet_rate,
        "relative_change": fleet_rate / old_fleet_rate - 1.0,
    }


def _mechanism_closure_violations(
    reference: DutyIndividual,
    candidate: DutyIndividual,
    mechanism_enabled: Mapping[str, bool],
) -> tuple[str, ...]:
    reference_depot, reference_type = _customer_structure(reference)
    candidate_depot, candidate_type = _customer_structure(candidate)
    violations: list[str] = []
    if not mechanism_enabled["cross_depot"]:
        changed = sorted(
            customer
            for customer, depot_id in reference_depot.items()
            if candidate_depot.get(customer) != depot_id
        )
        if changed:
            violations.append("cross_depot:" + ",".join(changed))
    if not mechanism_enabled["type_exchange"]:
        changed = sorted(
            customer
            for customer, vehicle_type in reference_type.items()
            if candidate_type.get(customer) != vehicle_type
        )
        if changed:
            violations.append("type_exchange:" + ",".join(changed))
    if not mechanism_enabled["multi_trip"]:
        changed = sorted(
            duty.physical_vehicle_id
            for duty in candidate.duties
            if len(duty.trips) > 1
        )
        if changed:
            violations.append("multi_trip:" + ",".join(changed))
    return tuple(violations)


def _move_mechanism_enabled(
    channel: str,
    mechanism_enabled: Mapping[str, bool],
) -> bool:
    mechanism_by_channel = {
        "depot_collaboration": "cross_depot",
        "fairness_cross_depot": "cross_depot",
        "multi_trip": "multi_trip",
        "whole_duty_type_exchange": "type_exchange",
        "time_varying_carbon_charge": "charge_timing",
    }
    mechanism = mechanism_by_channel.get(str(channel))
    return mechanism is None or bool(mechanism_enabled[mechanism])


def _single_trip_initial(individual: DutyIndividual) -> DutyIndividual:
    """Place every existing trip on one same-type, same-depot idle asset."""

    if any(
        trip.locked_customer_prefix
        or trip.trip_index in duty.locked_charging_trip_indices
        or any(session.locked for session in duty.charging_sessions)
        for duty in individual.duties
        for trip in duty.trips
    ):
        raise ValueError("single-trip initialization cannot rewrite locked Duty")
    duties = list(individual.duties)
    idle_by_group: dict[tuple[str, str], list[int]] = {}
    for index, duty in enumerate(duties):
        if not duty.trips:
            idle_by_group.setdefault(
                (duty.home_depot_id, duty.vehicle_type), []
            ).append(index)
    for index, duty in enumerate(tuple(duties)):
        if len(duty.trips) <= 1:
            continue
        group = (duty.home_depot_id, duty.vehicle_type)
        extras = duty.trips[1:]
        available = idle_by_group.get(group, [])
        if len(available) < len(extras):
            raise ValueError(
                "single-trip initialization lacks same-type, same-depot idle assets"
            )
        duties[index] = replace(
            duty,
            trips=(replace(duty.trips[0], trip_index=1),),
            charging_sessions=(),
        )
        for trip in extras:
            receiver_index = available.pop(0)
            receiver = duties[receiver_index]
            duties[receiver_index] = replace(
                receiver,
                trips=(
                    replace(
                        trip,
                        trip_index=1,
                        locked_customer_prefix=(),
                    ),
                ),
                charging_sessions=(),
            )
    result = DutyIndividual(
        duties=tuple(duties),
        unserved_customers=individual.unserved_customers,
        source=individual.source + ":single-trip-mechanism-off",
    )
    if any(len(duty.trips) > 1 for duty in result.duties):
        raise RuntimeError("single-trip initialization remained multi-trip")
    if _customer_structure(result) != _customer_structure(individual):
        raise RuntimeError("single-trip initialization changed customer structure")
    return result


def _prepare_population(
    initial: DutyIndividual,
    evaluator: DutyFullEvaluator,
    policy: ChargingRepairPolicy,
    *,
    mechanism_enabled: Mapping[str, bool] | None = None,
):
    initial_evaluation = evaluator.evaluate(initial)
    reversible = next(
        (
            (duty, trip)
            for duty in initial.duties
            for trip in duty.trips
            if len(trip.customer_ids) >= 2
        ),
        None,
    )
    if reversible is None:
        reverse_record = {
            "action_id": "preflight-reverse-first-two",
            "status": "SKIPPED_NO_REVERSIBLE_TRIP",
            "error_type": None,
            "error": None,
        }
    else:
        first_duty, first_trip = reversible
        reverse = ReverseSegmentMove(
            action_id="preflight-reverse-first-two",
            channel="technical_preflight",
            duty_id=first_duty.physical_vehicle_id,
            trip_index=first_trip.trip_index,
            start=0,
            stop=2,
        )
        reverse_outcome = evaluate_move(
            initial,
            reverse,
            evaluator=evaluator,
            charging_policy=policy,
        )
        reverse_record = {
            "action_id": reverse_outcome.action_id,
            "status": str(reverse_outcome.status),
            "error_type": reverse_outcome.error_type,
            "error": reverse_outcome.error,
        }

    attempts = []
    second = None
    second_evaluation = None
    for index, move in enumerate(
        generate_problem_moves(initial, initial_evaluation, evaluator.context.bundle.instance),
        start=1,
    ):
        if mechanism_enabled is not None and not _move_mechanism_enabled(
            move.channel,
            mechanism_enabled,
        ):
            continue
        outcome = evaluate_move(
            initial,
            move,
            evaluator=evaluator,
            charging_policy=policy,
        )
        attempts.append(
            {
                "index": index,
                "action_id": outcome.action_id,
                "channel": outcome.channel,
                "status": str(outcome.status),
                "error_type": outcome.error_type,
                "error": outcome.error,
            }
        )
        if (
            outcome.status == CandidateStatus.EVALUATED
            and outcome.candidate is not None
            and outcome.evaluation is not None
            and outcome.candidate.fingerprint != initial.fingerprint
            and (
                mechanism_enabled is None
                or not _mechanism_closure_violations(
                    initial,
                    outcome.candidate,
                    mechanism_enabled,
                )
            )
        ):
            second = outcome.candidate
            second_evaluation = outcome.evaluation
            break
    if second is None or second_evaluation is None:
        raise RuntimeError("no deterministic, fully evaluated distinct second parent")

    candidates = (initial, second, initial, second)
    return (
        candidates,
        initial_evaluation,
        reverse_record,
        attempts,
        (initial_evaluation, second_evaluation) * 2,
    )



def _write_failure_package(output: Path, error: Exception) -> bool:
    """Complete an output directory created by this invocation as failed."""

    metadata_path = output / "metadata.json"
    if not metadata_path.is_file():
        return False
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "RUNNING":
        return False
    repo = Path(__file__).resolve().parents[2]
    metadata["protected_hashes_after"] = {
        path: _sha256(repo / path) for path in PROTECTED
    }
    with (output / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("verdict", "error_type", "error"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "verdict": PROBE_FAILURE_VERDICT,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    failure_reason = f"{type(error).__name__}: {error}"
    acceptance = assess_run(
        termination_ok=None,
        feasible_ok=None,
        customers_complete=None,
        demand_complete=None,
        audit_ok=None,
        extra_failure_reasons=(failure_reason,),
        success_verdict=PROBE_SUCCESS_VERDICT,
        failure_verdict=PROBE_FAILURE_VERDICT,
    )
    decision = {
        "traceback": traceback.format_exc(),
        "user_decision_changed": False,
    }
    enterprise_failure_ending = ""
    if metadata.get("requested_enterprise_id") is not None:
        constructor = metadata.get(
            "requested_enterprise_init_constructor",
            "random",
        )
        enterprise_failure_ending = f"""
## 直接给用户

{metadata['requested_enterprise_id']} 的 `{constructor}` 初始化探针真实结局是：**失败**。原始初始化拒绝记录如已产生，保存在同包的 `native_initialization_diagnostics.json`。本次调用只保存失败现场；本轮执行者按用户预批退路继续收尾。
"""
    report = f"""# Problem-HGS 真实输入技术试跑失败报告

## 结论

本次技术试跑在生成正式结果包前失败。错误类型为 `{type(error).__name__}`，错误信息为：{error}。失败没有被改写成完成；完整调用栈保存在 `decision.json`。

## 交付前九条自检

1. 每个事实是否有出处？——错误类型、错误信息和调用栈来自本次异常，保存在 `decision.json`。
2. 有没有把建议或担忧写成已决？——没有；这里只记录失败。
3. 是否超出任务范围？——没有；只补齐本次失败现场。
4. 是否碰受保护文件？——本失败包不修改受保护文件；实际运行前后哈希以 `metadata.json` 已保存内容为准。
5. 是否留下新的待决选项？——没有。
6. 是否使用自造术语？——没有。
7. 失败、跳过、超时、异常是否如实保留？——本次异常已如实保留。
8. 四件套是否齐全？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json` 和 `report.md` 将由本失败收口一次写齐。
9. 交接记录是否同步？——失败包只保存现场；项目交接记录在任务收尾时统一同步。
{enterprise_failure_ending}
"""
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    finalize_five_file_package(
        output,
        acceptance=acceptance,
        metadata=metadata,
        decision=decision,
        report_text=report,
    )
    return True

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    problem_scope = parser.add_mutually_exclusive_group()
    problem_scope.add_argument(
        "--enterprise-id",
        help="run the sealed shared-station problem for one assigned enterprise",
    )
    problem_scope.add_argument(
        "--pi0-manifest",
        type=Path,
        help="enable joint participation checks from one supplied Pi0 manifest",
    )
    parser.add_argument(
        "--initial-solution",
        type=Path,
        help="inject one saved complete solution into the initial population",
    )
    parser.add_argument(
        "--enterprise-init-constructor",
        choices=("random", "greedy_repair", "legacy_three"),
        default="random",
        help="native constructor for an enterprise initial population",
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--carbon-price",
        type=float,
        default=CHINA81_CARBON_PRICE_CNY_PER_KG,
        help="carbon price in CNY/kg; default preserves the China81 constant",
    )
    parser.add_argument("--convergence-csv", type=Path)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    parser.add_argument("--stagnation-patience", type=int, default=500)
    parser.add_argument(
        "--education-depth-limit",
        type=int,
        default=None,
        help=(
            "maximum education rounds per child; omitted keeps the current "
            "unlimited behavior"
        ),
    )
    parser.add_argument(
        "--population-mode",
        choices=("technical_two_parent", "copied_hgs_defaults"),
        default="copied_hgs_defaults",
    )
    parser.add_argument(
        "--crossover-mode",
        choices=("fast_only", "hybrid"),
        default="fast_only",
    )
    parser.add_argument(
        "--route-layer-crossover",
        action="store_true",
        help=(
            "enable the independent OX-style customer-order crossover; "
            "default keeps the existing duty crossover path byte-for-byte"
        ),
    )
    parser.add_argument(
        "--decoder-structure-stats",
        action="store_true",
        help=(
            "record in-memory route-decoder block, label, and D2 cache "
            "statistics; default is disabled"
        ),
    )
    parser.add_argument(
        "--objective-mode",
        choices=(SINGLE_OBJECTIVE,),
        default=SINGLE_OBJECTIVE,
    )
    parser.add_argument("--arm", default=ARM)
    parser.add_argument(
        "--fleet-parameter-class",
        choices=tuple(FLEET_PARAMETER_CLASSES),
        default="fixed25",
    )
    parser.add_argument(
        "--depot-charging-scenario",
        choices=("60kw", "22kw"),
        default="60kw",
        help="rebuilt private-instance depot power/registered-curve pairing",
    )
    parser.add_argument("--disable-truth-sentinel", action="store_true")
    parser.add_argument(
        "--trajectory",
        choices=("full", "off"),
        default="off",
        help="full writes the per-candidate diagnostic trace; experiment default is off",
    )
    parser.add_argument("--stream-trajectory", action="store_true")
    parser.add_argument("--no-retain-trajectory", action="store_true")
    parser.add_argument("--stderr-capture-state", default="caller_not_declared")
    parser.add_argument(
        "--first-trip-prev-night",
        action="store_true",
        help=(
            "merge previous-day and same-day predeparture charging candidates "
            "for the first trip of each physical-vehicle duty"
        ),
    )
    parser.add_argument(
        "--charge-timing-policy",
        choices=tuple(sorted(CHARGE_TIMING_POLICIES)),
        default="cost_plus_carbon",
        help="charging-start policy used by both paired arms",
    )
    parser.add_argument(
        "--frvcpy-charging",
        action="store_true",
        help=(
            "use pinned frvcpy for fixed-route charging sites and amounts; "
            "default keeps the existing charging repair"
        ),
    )
    parser.add_argument(
        "--depot-assignment-operator",
        action="store_true",
        help=(
            "enable incremental cross-depot prefix/suffix migration into an "
            "empty same-vehicle-class duty"
        ),
    )
    parser.add_argument(
        "--dynamic-insertion-operator",
        action="store_true",
        help=(
            "technical V3 cut: insert one newly revealed PM order through "
            "the cached incremental dynamic operator; default is disabled"
        ),
    )
    parser.add_argument(
        "--proposal-mode",
        choices=(
            "legacy",
            "system",
            "route_only",
            "mechanism_only",
        ),
        default="system",
    )
    parser.add_argument(
        "--proposal-config",
        choices=("default", "combat"),
        default="default",
        help=(
            "named technical wiring configuration; combat enables the five "
            "Duty mechanism channels, DepotSplit, and first-trip prev_night"
        ),
    )
    parser.add_argument(
        "--mechanism-off",
        default="",
        help=(
            "comma-separated closed mechanism groups: cross_depot,"
            "multi_trip,type_exchange,charge_timing"
        ),
    )
    parser.add_argument(
        "--charging-prescreen",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "exact route-clock prescreen; defaults on for combat and off for "
            "other proposal configurations"
        ),
    )
    parser.add_argument(
        "--prescreen-audit-sample",
        type=int,
        default=0,
        help="number of prescreen rejections to replay through full charging repair",
    )
    parser.add_argument(
        "--fairness-generation-prescreen",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "filter exact dead fairness moves before constructing move objects; "
            "disable only for paired equivalence probes"
        ),
    )
    parser.add_argument(
        "--charging-diagnosis-capture-limit",
        type=int,
        default=0,
        help=(
            "save and replay the first N rejected duty-crossover raw candidates; "
            "default zero leaves search and outputs unchanged"
        ),
    )
    parser.add_argument(
        "--charging-diagnosis-output-dir",
        type=Path,
        help="directory for raw crossover snapshots and relaxation_probe.csv",
    )
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("technical iteration count must be positive")
    if args.stagnation_patience < 1:
        raise ValueError("technical stagnation patience must be positive")
    if args.education_depth_limit is not None and args.education_depth_limit < 1:
        raise ValueError("education depth limit must be positive")
    if args.max_runtime_seconds <= 0.0:
        raise ValueError("maximum runtime must be positive")
    if not math.isfinite(args.carbon_price) or args.carbon_price < 0.0:
        raise ValueError("carbon price must be finite and non-negative")
    if args.prescreen_audit_sample < 0:
        raise ValueError("prescreen audit sample cannot be negative")
    if args.charging_diagnosis_capture_limit < 0:
        raise ValueError("charging diagnosis capture limit cannot be negative")
    if (
        args.enterprise_id is not None
        and args.population_mode != "copied_hgs_defaults"
    ):
        raise ValueError(
            "enterprise native initialization requires copied_hgs_defaults"
        )
    if (
        args.enterprise_id is None
        and args.enterprise_init_constructor != "random"
    ):
        raise ValueError(
            "enterprise init constructor requires an enterprise id"
        )
    if bool(args.charging_diagnosis_capture_limit) != bool(
        args.charging_diagnosis_output_dir
    ):
        raise ValueError(
            "charging diagnosis capture limit and output directory must be "
            "provided together"
        )
    if any(
        name == "pyvrp" or name.startswith("pyvrp.")
        for name in sys.modules
    ):
        raise RuntimeError(
            "independent Problem-HGS runtime imported frozen PyVRP"
        )

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    combat_enabled = args.proposal_config == "combat"
    mechanism_off = _parse_mechanism_off(args.mechanism_off)
    mechanism_enabled = {
        name: name not in mechanism_off for name in sorted(MECHANISM_NAMES)
    }
    trajectory_mode = "full" if args.stream_trajectory else args.trajectory
    charging_prescreen_enabled = (
        combat_enabled
        if args.charging_prescreen is None
        else bool(args.charging_prescreen)
    )
    if args.prescreen_audit_sample and not charging_prescreen_enabled:
        raise ValueError("prescreen audit requires charging prescreen to be enabled")
    effective_first_trip_prev_night = bool(
        args.first_trip_prev_night or combat_enabled
    )
    effective_depot_assignment_operator = bool(
        args.depot_assignment_operator or combat_enabled
    )
    effective_charge_timing_policy = (
        args.charge_timing_policy
        if mechanism_enabled["charge_timing"]
        else "asap"
    )
    parameters = _parameters(
        random_seed=args.seed,
        stagnation_patience=args.stagnation_patience,
        crossover_mode=args.crossover_mode,
        population_mode=args.population_mode,
        objective_mode=args.objective_mode,
        education_depth_limit=args.education_depth_limit,
    )
    effective_population = _effective_population_metadata(
        args.population_mode,
        parameters.population,
    )
    code_provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state=args.stderr_capture_state,
    )
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "run_kind": "probe",
            "purpose": "exploratory real-input wiring probe; not a performance experiment",
            "code_provenance": code_provenance,
            "requested_instance_id": args.instance_id,
            "requested_enterprise_id": args.enterprise_id,
            "requested_pi0_manifest": (
                None
                if args.pi0_manifest is None
                else str(args.pi0_manifest.resolve())
            ),
            "requested_enterprise_init_constructor": (
                args.enterprise_init_constructor
            ),
            "requested_proposal_mode": args.proposal_mode,
            "requested_proposal_config": args.proposal_config,
            "requested_mechanism_off": sorted(mechanism_off),
            "effective_mechanism_enabled": mechanism_enabled,
            "requested_iterations": args.iterations,
            "requested_max_runtime_seconds": args.max_runtime_seconds,
            "requested_stagnation_patience": args.stagnation_patience,
            "requested_population_mode": args.population_mode,
            "effective_population": effective_population,
            "requested_crossover_mode": args.crossover_mode,
            "requested_objective_mode": args.objective_mode,
            "requested_fleet_parameter_class": args.fleet_parameter_class,
            "requested_depot_charging_scenario": (
                args.depot_charging_scenario
            ),
            "requested_truth_sentinel_enabled": not args.disable_truth_sentinel,
            "requested_trajectory_mode": args.trajectory,
            "effective_trajectory_mode": trajectory_mode,
            "legacy_stream_trajectory": args.stream_trajectory,
            "legacy_no_retain_trajectory": args.no_retain_trajectory,
            "requested_charging_prescreen": args.charging_prescreen,
            "effective_charging_prescreen": charging_prescreen_enabled,
            "prescreen_audit_sample": args.prescreen_audit_sample,
            "requested_first_trip_prev_night": args.first_trip_prev_night,
            "effective_first_trip_prev_night": (
                effective_first_trip_prev_night
            ),
            "requested_charge_timing_policy": args.charge_timing_policy,
            "effective_charge_timing_policy": effective_charge_timing_policy,
            "requested_frvcpy_charging": args.frvcpy_charging,
            "requested_depot_assignment_operator": (
                args.depot_assignment_operator
            ),
            "effective_depot_assignment_operator": (
                effective_depot_assignment_operator
            ),
            "requested_dynamic_insertion_operator": (
                args.dynamic_insertion_operator
            ),
            "protected_hashes_before": protected_before,
        },
    )

    bundle, initial, pi0, context = _build_context(
        repo,
        args.instance_id,
        fleet_parameters=FLEET_PARAMETER_CLASSES[
            args.fleet_parameter_class
        ],
        depot_charging_scenario_name=args.depot_charging_scenario,
    )
    if args.carbon_price != CHINA81_CARBON_PRICE_CNY_PER_KG:
        bundle = replace(
            bundle,
            prices=replace(bundle.prices, carbon_price=args.carbon_price),
            carbon_price_cny_per_kg=args.carbon_price,
        )
        context = replace(context, bundle=bundle)
    enterprise_slice: EnterpriseProblemSlice | None = None
    pi0_record: dict[str, object] | None = None
    pi0_manifest_sha256: str | None = None
    if args.enterprise_id is not None:
        if context.rebuilt_route_constraints is None:
            raise ValueError(
                "enterprise slicing requires the sealed rebuilt route contract"
            )
        enterprise_slice = slice_enterprise_problem(
            bundle,
            context.rebuilt_route_constraints,
            args.enterprise_id,
        )
        bundle = enterprise_slice.bundle
        if args.enterprise_init_constructor == "legacy_three":
            plans, reason = build_edf_route_plans(enterprise_slice.seed_input)
            if reason:
                raise RuntimeError(f"HALT_NO_ENTERPRISE_SEED: {reason}")
            skeleton, _departures, _scheduled = plans_to_solution(
                enterprise_slice.seed_input,
                plans,
            )
            completed = complete_china81_route_skeleton(
                skeleton,
                bundle,
                charge_amount_strategies=("just_enough",),
                depot_charge_window_mode="same_day_predeparture",
                charge_timing_policy="carbon_min",
                public_station_candidate_mode="fallback",
            )
            initial = register_all_vehicle_slots(
                DutyIndividual.from_solution(
                    completed.solution,
                    customer_node_ids=enterprise_slice.customer_ids,
                    source=f"enterprise-seed/{enterprise_slice.source_id}",
                ),
                bundle,
            )
        else:
            initial = register_all_vehicle_slots(
                DutyIndividual(
                    duties=(),
                    unserved_customers=enterprise_slice.customer_ids,
                    source=f"native-init-reference/{enterprise_slice.source_id}",
                ),
                bundle,
            )
        neutral = {enterprise_slice.depot_id: 1.0}
        pi0 = neutral
        context = replace(
            context,
            bundle=bundle,
            independent_profit=neutral,
            independent_profit_identity=FrozenMappingIdentity(
                source_id=f"enterprise-neutral/{enterprise_slice.source_id}",
                value_sha256=mapping_sha256(neutral),
                externally_frozen=False,
            ),
            prior_profit={enterprise_slice.depot_id: 0.0},
            rebuilt_route_constraints=enterprise_slice.route_constraints,
            fairness_enabled=False,
            theta=0.0,
        )
    elif args.pi0_manifest is not None:
        pi0_manifest_path = args.pi0_manifest.resolve()
        pi0_records = load_pi0_manifest(pi0_manifest_path)
        if args.instance_id not in pi0_records:
            raise ValueError(
                f"Pi0 manifest misses requested instance: {args.instance_id}"
            )
        pi0_record = pi0_records[args.instance_id]
        pi0, context = _apply_joint_pi0_record(
            bundle,
            context,
            pi0_record,
        )
        pi0_manifest_sha256 = _sha256(pi0_manifest_path)
    if args.initial_solution is not None:
        initial = _load_registered_initial_solution(args.initial_solution.resolve(), bundle)
    if effective_first_trip_prev_night:
        context = replace(
            context,
            depot_charge_window_mode="full_gap",
        )
    if args.disable_truth_sentinel:
        context = replace(
            context,
            incremental_full_truth_sentinel_enabled=False,
        )
    dynamic_revealed_customer = None
    if args.dynamic_insertion_operator:
        initial, context, dynamic_revealed_customer = (
            _dynamic_insertion_technical_cut(
                bundle,
                initial,
                context,
            )
        )
    if not mechanism_enabled["multi_trip"]:
        initial = _single_trip_initial(initial)
    metro_initial_clock_closure = None
    mechanism_reference = initial
    evaluator = DutyFullEvaluator(context)
    policy = _policy(
        evaluator,
        first_trip_prev_night_enabled=effective_first_trip_prev_night,
        charge_timing_policy=effective_charge_timing_policy,
        frvcpy_enabled=args.frvcpy_charging,
    )
    dynamic_insertion_diagnostic = None
    if args.dynamic_insertion_operator:
        inserted = DynamicInsertionOperator(
            enabled=True,
            random_seed=args.seed,
        ).apply(
            initial,
            evaluator=evaluator,
            charging_policy=policy,
            newly_revealed_customer_ids=(dynamic_revealed_customer,),
        )
        initial = inserted.individual
        dynamic_insertion_diagnostic = asdict(inserted.accounting)
    depotsearch_c1_requested = bool(
        args.instance_id == DEPOT_SEARCH_INSTANCE_ID and combat_enabled
    )
    route_engine_options: dict[str, object] = {}
    if depotsearch_c1_requested:
        route_engine_options.update(
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
        )
    if not mechanism_enabled["cross_depot"]:
        route_engine_options["cross_depot_enabled"] = False
    if not mechanism_enabled["multi_trip"]:
        route_engine_options["multi_trip_enabled"] = False
    if not mechanism_enabled["type_exchange"]:
        route_engine_options["type_exchange_enabled"] = False
    route_engine = IndependentKernelDutyRouteProposalEngine(
        evaluator.context,
        initial,
        random_seed=args.seed,
        stream_role="main_route",
        depot_assignment_operator_enabled=(
            effective_depot_assignment_operator
        ),
        **route_engine_options,
    )
    route_contract = evaluator.context.rebuilt_route_constraints
    if depotsearch_c1_requested and route_contract is None:
        raise RuntimeError(
            "DEPOTSEARCH C1 wiring requires a registered route contract"
        )
    route_engine_wiring = {
        "scope": "DEPOTSEARCH instance with explicit combat proposal config",
        "requested": {
            "rebuilt_volume_capacity_enabled": depotsearch_c1_requested,
            "rebuilt_shift_neighbours_only": depotsearch_c1_requested,
        },
        "effective": {
            "rebuilt_volume_capacity_enabled": bool(
                route_engine.rebuilt_volume_capacity_enabled
            ),
            "rebuilt_shift_neighbours_only": bool(
                route_engine.rebuilt_shift_neighbours_only
            ),
        },
        "route_engine_source_id": route_engine.source_id,
        "route_engine_identity_sha256": route_engine.identity_sha256,
        "route_contract": (
            None
            if route_contract is None
            else {
                "source_id": route_contract.source_id,
                "customer_shift_count": len(
                    route_contract.customer_shift_by_id
                ),
                "customer_volume_count": len(
                    route_contract.customer_volume_m3_by_id
                ),
                "shift_ids": sorted(
                    {
                        str(shift_id)
                        for shift_id in route_contract.customer_shift_by_id.values()
                    }
                ),
                "vehicle_volume_capacity_m3": float(
                    route_contract.vehicle_volume_capacity_m3
                ),
            }
        ),
    }
    if depotsearch_c1_requested:
        if route_engine_wiring["effective"] != route_engine_wiring["requested"]:
            raise RuntimeError(
                "DEPOTSEARCH C1 requested/effective switch mismatch"
            )
        assert route_contract is not None
        if set(route_contract.customer_shift_by_id) != set(
            route_contract.customer_volume_m3_by_id
        ):
            raise RuntimeError(
                "DEPOTSEARCH C1 route contract shift/volume customer coverage mismatch"
            )
    shift_proxy_validation = _shift_aware_ev_proxy_validation(
        initial,
        route_engine,
        evaluator.context,
    )
    initialization_started = perf_counter()
    initialization_full_calls_before = evaluator.full_calls
    native_initialization_diagnostics = None
    if args.population_mode == "technical_two_parent":
        (
            candidates,
            initial_evaluation,
            reverse_record,
            attempts,
            initial_evaluations,
        ) = _prepare_population(
            initial,
            evaluator,
            policy,
            mechanism_enabled=(
                mechanism_enabled if mechanism_off else None
            ),
        )
        initialization_summary = {
            "requested_size": 4,
            "actual_size": len(candidates),
            "attempts_exhausted": False,
        }
    else:
        legacy_enterprise_init = bool(
            enterprise_slice is not None
            and args.enterprise_init_constructor == "legacy_three"
        )
        built = build_initial_population(
            initial,
            evaluator=evaluator,
            charging_policy=policy,
            route_engine=route_engine,
            requested_size=(
                1 if legacy_enterprise_init else parameters.population.min_pop_size
            ),
            random_seed=args.seed,
            max_random_attempts=(
                0
                if legacy_enterprise_init
                else (
                    parameters.population.min_pop_size
                    if enterprise_slice is not None
                    else None
                )
            ),
            initialization_method=(
                args.enterprise_init_constructor
                if enterprise_slice is not None and not legacy_enterprise_init
                else "random"
            ),
            include_reference_candidate=(
                enterprise_slice is None or legacy_enterprise_init
            ),
            require_complete_feasible=False,
            stop_requested=lambda: (
                perf_counter() - initialization_started
                >= args.max_runtime_seconds
            ),
            witness_seed=(
                initial
                if (
                    args.instance_id == DEPOT_SEARCH_INSTANCE_ID
                    and enterprise_slice is None
                )
                else None
            ),
            mechanism_enabled=(
                None if enterprise_slice is not None else mechanism_enabled
            ),
        )
        if enterprise_slice is not None:
            native_statistics = route_engine.native_initialization_statistics
            native_initialization_diagnostics = {
                "schema": "resetp.enterprise_native_initialization.v2",
                "enterprise_id": enterprise_slice.enterprise_id,
                "source_id": enterprise_slice.source_id,
                "constructor": args.enterprise_init_constructor,
                "rng_stream_count": native_statistics["rng_stream_count"],
                "native_make_random_call_count": native_statistics[
                    "make_random_call_count"
                ],
                "greedy_repair_call_count": native_statistics[
                    "greedy_repair_call_count"
                ],
                "prepopulation_local_search_call_count": native_statistics[
                    "prepopulation_local_search_call_count"
                ],
                "legacy_self_built_initialization_call_counts": {
                    "build_edf_route_plans": int(legacy_enterprise_init),
                    "minimum_edf_order_chains": int(legacy_enterprise_init),
                    "complete_china81_route_skeleton": int(
                        legacy_enterprise_init
                    ),
                },
                "attempts": [asdict(item) for item in built.attempts],
            }
            _json(
                output / "native_initialization_diagnostics.json",
                native_initialization_diagnostics,
            )
        if legacy_enterprise_init and built.actual_size == 1:
            candidates = built.candidates * 4
            initial_evaluations = built.evaluations * 4
        elif built.actual_size < 4:
            raise RuntimeError(
                "HALT_B_NATIVE_MATERIALIZATION: fewer than four native "
                f"{args.enterprise_init_constructor} solutions were retained "
                "before population entry"
            )
        else:
            candidates = built.candidates
            initial_evaluations = built.evaluations
        initial_evaluation = built.evaluations[0]
        reverse_record = {
            "status": "NOT_RUN_COPIED_HGS_POPULATION",
            "error": None,
        }
        attempts = [asdict(item) for item in built.attempts]
        initialization_summary = {
            "requested_size": built.requested_size,
            "actual_size": len(candidates),
            "attempts_exhausted": built.attempts_exhausted,
            "reference_candidate_included": (
                enterprise_slice is None or legacy_enterprise_init
            ),
        }
    initialization_wall_seconds = perf_counter() - initialization_started
    initialization_full_evaluations = (
        evaluator.full_calls - initialization_full_calls_before
    )
    mechanism_engine = MechanismProposalEngine(
        evaluator.context,
        policy,
        include_charging_candidates=mechanism_enabled["charge_timing"],
        include_structural_channels=combat_enabled,
        cross_depot_enabled=mechanism_enabled["cross_depot"],
        multi_trip_enabled=mechanism_enabled["multi_trip"],
        type_exchange_enabled=mechanism_enabled["type_exchange"],
        fairness_generation_prescreen_enabled=(
            args.fairness_generation_prescreen
        ),
    )
    if combat_enabled:
        proposal_engine = SequentialProposalEngine(
            (route_engine, mechanism_engine),
            source_id="problem-hgs-combat-all-duty-channels-v1",
        )
    elif args.proposal_mode == "legacy":
        proposal_engine = LegacyCompleteProposalEngine()
    elif args.proposal_mode == "route_only":
        proposal_engine = SequentialProposalEngine((route_engine,))
    elif args.proposal_mode == "mechanism_only":
        proposal_engine = SequentialProposalEngine((mechanism_engine,))
    else:
        proposal_engine = None
    identity = FrozenPopulationIdentity(
        source_id=f"technical-real-input-{args.population_mode}",
        value_sha256=population_sha256(candidates),
    )
    trajectory_path = output / "trajectory.jsonl"
    stream_summary = {
        "rows": 0,
        "crossover_changed": False,
    }
    trajectory_handle = None
    trajectory_sink = None
    if trajectory_mode == "full":
        trajectory_handle = trajectory_path.open("w", encoding="utf-8")

        def trajectory_sink(rows) -> None:
            for row in rows:
                trajectory_handle.write(
                    json.dumps(asdict(row), ensure_ascii=False, allow_nan=False)
                    + "\n"
                )
                stream_summary["rows"] += 1
                stream_summary["crossover_changed"] = bool(
                    stream_summary["crossover_changed"]
                    or (
                        row.phase == "crossover"
                        and row.after_fingerprint is not None
                        and row.before_fingerprint != row.after_fingerprint
                    )
                )
            trajectory_handle.flush()

    convergence_path = (
        args.convergence_csv.resolve()
        if args.convergence_csv is not None
        else output / "convergence.csv"
    )
    convergence_path.parent.mkdir(parents=True, exist_ok=True)
    convergence_diagnostics_path = convergence_path.with_name(
        f"{convergence_path.stem}_diagnostics.csv"
    )
    convergence_handle = convergence_path.open(
        "x", encoding="utf-8", newline=""
    )
    convergence_diagnostics_handle = convergence_diagnostics_path.open(
        "x", encoding="utf-8", newline=""
    )
    convergence_fields = (
        "cycle",
        "wall_seconds",
        "actual_full_model_evaluations",
        "has_feasible",
        "best_feasible_raw_cost",
    )
    diagnostics_fields = (
        "cycle",
        "wall_seconds",
        "actual_full_model_evaluations",
        "current_solution_raw_cost",
        "current_solution_penalized_cost",
        "physical_feasible",
        "fairness_feasible",
        "violation_counts_json",
        "violation_magnitudes_json",
        "outer_repair_calls",
        "outer_refinement_calls",
    )
    convergence_writer = csv.DictWriter(
        convergence_handle,
        fieldnames=convergence_fields,
        lineterminator="\n",
    )
    convergence_diagnostics_writer = csv.DictWriter(
        convergence_diagnostics_handle,
        fieldnames=diagnostics_fields,
        lineterminator="\n",
    )
    convergence_writer.writeheader()
    convergence_diagnostics_writer.writeheader()
    convergence_handle.flush()
    convergence_diagnostics_handle.flush()
    os.fsync(convergence_handle.fileno())
    os.fsync(convergence_diagnostics_handle.fileno())
    last_logged_best: float | None = None
    last_diagnostic_cycle: int | None = None

    def stop_and_record(state) -> bool:
        nonlocal last_diagnostic_cycle, last_logged_best
        if state.best_feasible_raw_cost is not None and (
            last_logged_best is None
            or float(state.best_feasible_raw_cost) < last_logged_best
        ):
            last_logged_best = float(state.best_feasible_raw_cost)
            convergence_writer.writerow(
                {
                    "cycle": int(state.iterations),
                    "wall_seconds": f"{float(state.elapsed_seconds):.9f}",
                    "actual_full_model_evaluations": evaluator.full_calls,
                    "has_feasible": True,
                    "best_feasible_raw_cost": f"{last_logged_best:.12f}",
                }
            )
            convergence_handle.flush()
            os.fsync(convergence_handle.fileno())
        if last_diagnostic_cycle != int(state.iterations):
            last_diagnostic_cycle = int(state.iterations)
            convergence_diagnostics_writer.writerow(
                {
                    "cycle": int(state.iterations),
                    "wall_seconds": f"{float(state.elapsed_seconds):.9f}",
                    "actual_full_model_evaluations": evaluator.full_calls,
                    "current_solution_raw_cost": (
                        state.current_solution_raw_cost
                    ),
                    "current_solution_penalized_cost": (
                        state.current_solution_penalized_cost
                    ),
                    "physical_feasible": state.physical_feasible,
                    "fairness_feasible": state.fairness_feasible,
                    "violation_counts_json": json.dumps(
                        dict(state.violation_counts), sort_keys=True
                    ),
                    "violation_magnitudes_json": json.dumps(
                        dict(state.violation_magnitudes), sort_keys=True
                    ),
                    "outer_repair_calls": state.outer_repair_calls,
                    "outer_refinement_calls": state.outer_refinement_calls,
                }
            )
            convergence_diagnostics_handle.flush()
            os.fsync(convergence_diagnostics_handle.fileno())
        return (
            state.iterations >= args.iterations
            or state.elapsed_seconds >= args.max_runtime_seconds
        )

    captured_charging_rejections: list[ScheduleCaptureRecord] = []

    def capture_charging_rejection(record: ScheduleCaptureRecord) -> None:
        if (
            len(captured_charging_rejections)
            >= args.charging_diagnosis_capture_limit
            or record.channel != "duty_crossover"
            or record.a0_status != "INFEASIBLE"
        ):
            return
        captured_charging_rejections.append(record)

    capture_context = (
        schedule_capture_sink(capture_charging_rejection)
        if args.charging_diagnosis_capture_limit
        else nullcontext()
    )
    decoder_structure_snapshot = None
    if args.decoder_structure_stats:
        begin_decoder_structure_stats()
    station_pruning_before_search = charging_repair_runtime_diagnostics()
    try:
        with capture_context:
            result = run_integrated_problem_hgs(
                candidates,
                evaluator=evaluator,
                charging_policy=policy,
                parameters=parameters,
                initial_population_identity=identity,
                stop=stop_and_record,
                arm=args.arm,
                route_engine=route_engine,
                trajectory_sink=trajectory_sink,
                retain_trajectory=False,
                proposal_engine=proposal_engine,
                initial_evaluations=initial_evaluations,
                initialization_full_evaluation_count=(
                    initialization_full_evaluations
                ),
                initialization_wall_seconds=initialization_wall_seconds,
                charging_prescreen_enabled=charging_prescreen_enabled,
                charging_prescreen_audit_limit=args.prescreen_audit_sample,
                cross_depot_enabled=mechanism_enabled["cross_depot"],
                multi_trip_enabled=mechanism_enabled["multi_trip"],
                type_exchange_enabled=mechanism_enabled["type_exchange"],
                route_layer_crossover_enabled=args.route_layer_crossover,
                include_mechanism_refinement=True,
                include_charging_candidates=mechanism_enabled["charge_timing"],
            )
    finally:
        if args.decoder_structure_stats:
            decoder_structure_snapshot = end_decoder_structure_stats()
            _json(
                output / "decoder_structure_stats.json",
                decoder_structure_snapshot.to_dict(),
            )
        if trajectory_handle is not None:
            trajectory_handle.close()
        convergence_handle.close()
        convergence_diagnostics_handle.close()

    station_pruning_after_search = charging_repair_runtime_diagnostics()
    station_pruning_search = {
        name: (
            station_pruning_after_search["station_pruning"][name]
            - station_pruning_before_search["station_pruning"][name]
        )
        for name in station_pruning_after_search["station_pruning"]
    }

    if decoder_structure_snapshot is not None:
        decoder_structure_payload = decoder_structure_snapshot.to_dict()
        decoder_structure_payload["search_outcome"] = {
            "iterations": int(result.iterations),
            "termination_status": result.termination_status,
            "best_individual_fingerprint": result.best.fingerprint,
            "best_cost": float(result.best_evaluation.total_cost),
            "best_feasible": bool(result.best_evaluation.feasible),
            "best_violation_count": len(result.best_evaluation.violations),
            "accounting": result.accounting.to_dict(),
        }
        _json(
            output / "decoder_structure_stats.json",
            decoder_structure_payload,
        )

    if args.charging_diagnosis_capture_limit:
        assert args.charging_diagnosis_output_dir is not None
        _write_charging_diagnosis_probe(
            captured_charging_rejections,
            output=args.charging_diagnosis_output_dir.resolve(),
            context=evaluator.context,
            policy=policy,
        )

    terminal_wall_seconds = (
        result.accounting.initialization_wall_seconds
        + result.accounting.run_wall_seconds
    )
    with convergence_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=convergence_fields,
            lineterminator="\n",
        )
        writer.writerow(
            {
                "cycle": int(result.iterations),
                "wall_seconds": f"{terminal_wall_seconds:.9f}",
                "actual_full_model_evaluations": evaluator.full_calls,
                "has_feasible": bool(result.best_evaluation.feasible),
                "best_feasible_raw_cost": (
                    f"{float(result.best_evaluation.total_cost):.12f}"
                    if result.best_evaluation.feasible
                    else ""
                ),
            }
        )
        handle.flush()
        os.fsync(handle.fileno())
    terminal_violation_counts = Counter(
        item.type for item in result.best_evaluation.violations
    )
    terminal_violation_magnitudes: Counter[str] = Counter()
    for magnitude, axis in zip(
        result.best_evaluation.violation_magnitudes,
        result.best_evaluation.violation_axes,
        strict=True,
    ):
        terminal_violation_magnitudes[axis] += float(magnitude)
    with convergence_diagnostics_path.open(
        "a", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=diagnostics_fields,
            lineterminator="\n",
        )
        writer.writerow(
            {
                "cycle": int(result.iterations),
                "wall_seconds": f"{terminal_wall_seconds:.9f}",
                "actual_full_model_evaluations": evaluator.full_calls,
                "current_solution_raw_cost": float(
                    result.best_evaluation.total_cost
                ),
                "current_solution_penalized_cost": float(
                    result.accounting.penalty_manager.cost(
                        result.best_evaluation
                    )
                ),
                "physical_feasible": not any(
                    item.type != PROFIT_FAIRNESS
                    for item in result.best_evaluation.violations
                ),
                "fairness_feasible": not any(
                    item.type == PROFIT_FAIRNESS
                    for item in result.best_evaluation.violations
                ),
                "violation_counts_json": json.dumps(
                    dict(sorted(terminal_violation_counts.items())),
                    sort_keys=True,
                ),
                "violation_magnitudes_json": json.dumps(
                    dict(sorted(terminal_violation_magnitudes.items())),
                    sort_keys=True,
                ),
                "outer_repair_calls": int(
                    result.accounting.repair_calls
                ),
                "outer_refinement_calls": int(
                    result.accounting.outer_refinement_calls
                ),
            }
        )
        handle.flush()
        os.fsync(handle.fileno())
    if any(
        name == "pyvrp" or name.startswith("pyvrp.")
        for name in sys.modules
    ):
        raise RuntimeError(
            "independent Problem-HGS runtime imported frozen PyVRP"
        )
    crossover_changed = bool(stream_summary["crossover_changed"]) or bool(
        result.accounting.crossover_actions
    )
    customer_nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    if args.dynamic_insertion_operator:
        served = {
            node_id
            for route in result.best_evaluation.prepared_solution.routes
            for node_id in route.node_sequence[1:-1]
            if node_id in customer_nodes
        }
    else:
        served = {
            customer
            for duty in result.best.duties
            for trip in duty.trips
            for customer in trip.customer_ids
        }
    served_demand = sum(float(customer_nodes[item].demand) for item in served)
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    charging_actions = tuple(
        result.best_evaluation.prepared_solution.charging_actions
    )
    ev_observation = {
        "ev_customers": sum(
            len(trip.customer_ids)
            for duty in result.best.duties
            if duty.vehicle_type == "ev"
            for trip in duty.trips
        ),
        "used_ev_duties": sum(
            1
            for duty in result.best.duties
            if duty.vehicle_type == "ev" and duty.trips
        ),
        "charging_actions": len(charging_actions),
        "charging_energy_kwh": sum(
            float(action.energy_kwh) for action in charging_actions
        ),
        "electricity_kwh": float(
            result.best_evaluation.breakdown.get("electricity_kwh", 0.0)
        ),
        "depot_charging_kwh": float(
            result.best_evaluation.breakdown.get("depot_charging_kwh", 0.0)
        ),
        "station_charging_kwh": float(
            result.best_evaluation.breakdown.get("station_charging_kwh", 0.0)
        ),
        "ev_drive_kwh": float(
            result.best_evaluation.breakdown.get("ev_drive_kwh", 0.0)
        ),
    }
    enterprise_ledger = build_enterprise_ledger(
        instance_id=args.instance_id,
        seed=args.seed,
        solution_fingerprint=result.best.fingerprint,
        solution=result.best_evaluation.prepared_solution,
        bundle=bundle,
        prior_profit=evaluator.context.prior_profit,
        carbon_quota_kg=evaluator.context.carbon_quota_kg,
        expected_total_cost=result.best_evaluation.total_cost,
    )
    enterprise_ledger_path = output / "enterprise_ledger.json"
    _json(enterprise_ledger_path, enterprise_ledger)
    participation_margin = {
        str(key): float(value)
        for key, value in result.best_evaluation.participation_margin.items()
    }
    participation_violations = tuple(
        violation
        for violation in result.best_evaluation.violations
        if violation.type == PROFIT_FAIRNESS
    )
    physical_violations = tuple(
        violation
        for violation in result.best_evaluation.violations
        if violation.type != PROFIT_FAIRNESS
    )
    fairness_active = bool(context.fairness_enabled)
    participation_margin_complete = bool(
        not fairness_active
        or (
            set(participation_margin) == set(context.independent_profit)
            and all(math.isfinite(value) for value in participation_margin.values())
        )
    )
    participation_satisfied = bool(
        participation_margin_complete and not participation_violations
    )
    physical_feasible = not physical_violations
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    closure_violations = _mechanism_closure_violations(
        mechanism_reference,
        result.best,
        mechanism_enabled,
    )
    forbidden_channels_by_mechanism = {
        "cross_depot": ("depot_collaboration", "fairness_cross_depot"),
        "multi_trip": ("multi_trip",),
        "type_exchange": ("whole_duty_type_exchange",),
        "charge_timing": ("time_varying_carbon_charge",),
    }
    forbidden_proposed_actions = {
        mechanism: {
            channel: int(result.accounting.proposed_actions.get(channel, 0))
            for channel in forbidden_channels_by_mechanism[mechanism]
        }
        for mechanism in sorted(mechanism_off)
    }
    forbidden_proposed_nonzero = {
        mechanism: counts
        for mechanism, counts in forbidden_proposed_actions.items()
        if any(counts.values())
    }
    reference_depot, reference_type = _customer_structure(mechanism_reference)
    final_depot, final_type = _customer_structure(result.best)

    failure_reasons = []
    enterprise_expectation = (
        None
        if enterprise_slice is None
        else ENTERPRISE_NATIVE_PROBE_EXPECTATIONS.get(
            enterprise_slice.enterprise_id
        )
    )
    enterprise_customer_scope_ok = True
    enterprise_demand_scope_ok = True
    if enterprise_expectation is not None:
        expected_customers, expected_demand = enterprise_expectation
        enterprise_customer_scope_ok = len(customer_nodes) == expected_customers
        enterprise_demand_scope_ok = total_demand == expected_demand
        if not enterprise_customer_scope_ok:
            failure_reasons.append(
                "enterprise slice customer total differs from the frozen probe contract"
            )
        if not enterprise_demand_scope_ok:
            failure_reasons.append(
                "enterprise slice demand total differs from the frozen probe contract"
            )
    if (
        enterprise_slice is None
        and args.pi0_manifest is None
        and not initial_evaluation.feasible
    ):
        failure_reasons.append("initial solution is infeasible")
    expected_termination_statuses = {"STOPPED_BY_CALLER"}
    if parameters.stagnation_patience is not None:
        expected_termination_statuses.add("CONVERGED_NO_IMPROVEMENT")
    if result.termination_status not in expected_termination_statuses:
        failure_reasons.append(f"unexpected termination: {result.termination_status}")
    if args.pi0_manifest is None and not result.best_evaluation.feasible:
        failure_reasons.append("best solution is infeasible")
    if args.pi0_manifest is not None and not physical_feasible:
        failure_reasons.append(
            "best solution has a physical violation outside the participation constraint"
        )
    if args.pi0_manifest is not None and not participation_margin_complete:
        failure_reasons.append("participation margin output is missing or non-finite")
    if served != set(customer_nodes):
        failure_reasons.append("not all customers are served")
    sentinel_acceptance_classification = _sentinel_acceptance_classification(
        result.accounting.accepted_actions
    )
    failure_reasons.extend(
        _sentinel_validation_failures(
            accepted_actions=result.accounting.accepted_actions,
            sentinel_enabled=(
                context.incremental_full_truth_sentinel_enabled
            ),
            sentinel_evaluations=result.accounting.sentinel_evaluations,
        )
    )
    if protected_before != protected_after:
        failure_reasons.append("a protected evaluator file changed during the run")
    if closure_violations:
        failure_reasons.append(
            "disabled mechanism structural closure failed: "
            + "; ".join(closure_violations)
        )
    if forbidden_proposed_nonzero:
        failure_reasons.append(
            "disabled mechanism emitted named actions: "
            + repr(forbidden_proposed_nonzero)
        )
    if (
        not mechanism_enabled["charge_timing"]
        and policy.charge_timing_policy != "asap"
    ):
        failure_reasons.append("disabled charge timing did not force asap")
    acceptance = assess_run(
        termination_ok=result.termination_status in expected_termination_statuses,
        feasible_ok=bool(
            physical_feasible
            if args.pi0_manifest is not None
            else (
                result.best_evaluation.feasible
                and (
                    enterprise_slice is not None
                    or initial_evaluation.feasible
                )
            )
        ),
        customers_complete=(
            served == set(customer_nodes) and enterprise_customer_scope_ok
        ),
        demand_complete=(
            served_demand == total_demand and enterprise_demand_scope_ok
        ),
        audit_ok=protected_before == protected_after,
        extra_failure_reasons=failure_reasons,
        success_verdict=PROBE_SUCCESS_VERDICT,
        failure_verdict=PROBE_FAILURE_VERDICT,
    )
    failure_reasons = list(acceptance.failure_reasons)
    verdict = acceptance.verdict
    enterprise_counts: dict[str, int] = {}
    for enterprise_id in bundle.enterprise_assignment_by_customer.values():
        enterprise_counts[str(enterprise_id)] = (
            enterprise_counts.get(str(enterprise_id), 0) + 1
        )

    metadata = {
        "status": "COMPLETE" if acceptance.accepted else "FAILED",
        "run_kind": "probe",
        "purpose": "exploratory real-input wiring probe; not a performance experiment",
        "instance_id": args.instance_id,
        "requested_initial_solution": (
            None
            if args.initial_solution is None
            else {
                "path": str(args.initial_solution.resolve()),
                "sha256": _sha256(args.initial_solution.resolve()),
            }
        ),
        "enterprise_slice": (
            None
            if enterprise_slice is None
            else {
                "enterprise_id": enterprise_slice.enterprise_id,
                "depot_id": enterprise_slice.depot_id,
                "customer_count": len(enterprise_slice.customer_ids),
                "customer_ids": list(enterprise_slice.customer_ids),
                "source_id": enterprise_slice.source_id,
                "mapping_sha256": enterprise_slice.mapping_sha256,
                "shared_public_station_ids": [
                    node.node_id
                    for node in enterprise_slice.bundle.instance.nodes
                    if node.node_type.lower() == "f"
                ],
            }
        ),
        "instance_formally_selected": False,
        "formal_search_allowed": bool(bundle.formal_search_allowed),
        "bundle_source_paths": dict(bundle.source_paths),
        "enterprise_assignment": {
            "loaded": bundle.enterprise_assignment_source_path is not None,
            "source_path": bundle.enterprise_assignment_source_path,
            "source_sha256": bundle.enterprise_assignment_source_sha256,
            "normalized_mapping_sha256": (
                bundle.enterprise_assignment_mapping_sha256
            ),
            "rule_ids": list(bundle.enterprise_assignment_rule_ids),
            "customer_home_depot_sha256": _string_mapping_sha256(
                bundle.customer_home_depot
            ),
            "customer_count": len(bundle.enterprise_assignment_by_customer),
            "enterprise_customer_counts": dict(sorted(enterprise_counts.items())),
        },
        "machine": "M1 formal-number machine, but this output is diagnostic only",
        "code_provenance": code_provenance,
        "random_seed": args.seed,
        "carbon_price_cny_per_kg": float(bundle.prices.carbon_price),
        "enterprise_init_constructor": args.enterprise_init_constructor,
        "iterations": result.iterations,
        "requested_iteration_ceiling": args.iterations,
        "max_runtime_seconds": args.max_runtime_seconds,
        "stop_semantics": (
            "technical fixed-iteration stop with a "
            f"{args.max_runtime_seconds:g}-second hard ceiling"
        ),
        "stagnation_patience": parameters.stagnation_patience,
        "education_depth_limit": parameters.education_depth_limit,
        "crossover_mode": parameters.crossover_mode,
        "objective_mode": result.objective_mode,
        "trajectory_mode": trajectory_mode,
        "trajectory_streamed_incrementally": trajectory_mode == "full",
        "trajectory_retained_in_memory": False,
        "trajectory_rows_streamed": stream_summary["rows"],
        "convergence_csv": str(convergence_path),
        "convergence_diagnostics_csv": str(
            convergence_diagnostics_path
        ),
        "fairness_generation_prescreen": (
            mechanism_engine.generation_statistics
        ),
        "charging_prescreen": (
            result.charging_prescreen_accounting
            if result.charging_prescreen_accounting is not None
            else {"enabled": False}
        ),
        "charging_station_pruning": {
            "scope": "search_only",
            "completed_cycles": int(result.iterations),
            "totals": station_pruning_search,
            "per_cycle": {
                name: (
                    float(value) / float(result.iterations)
                    if result.iterations
                    else None
                )
                for name, value in station_pruning_search.items()
            },
        },
        "frvcpy_route_clock_prescreen": {
            "frvcpy_enabled": bool(
                result.effective_execution.frvcpy_enabled
            ),
            "bypass_removed_after_equivalence_spot_check": bool(
                result.effective_execution.frvcpy_enabled
                and charging_prescreen_enabled
            ),
        },
        "charging_diagnosis_capture": {
            "requested_limit": int(args.charging_diagnosis_capture_limit),
            "captured": len(captured_charging_rejections),
            "output_dir": (
                None
                if args.charging_diagnosis_output_dir is None
                else str(args.charging_diagnosis_output_dir.resolve())
            ),
        },
        "incremental_full_truth_sentinel_enabled": (
            result.effective_execution.incremental_full_truth_sentinel_enabled
        ),
        "sentinel_acceptance_classification": (
            sentinel_acceptance_classification
        ),
        "best_evaluation_source": result.best_evaluation.source,
        "parameters": asdict(parameters),
        "population_mode": args.population_mode,
        "effective_population": effective_population,
        "initial_population": initialization_summary,
        "native_initialization": (
            None
            if native_initialization_diagnostics is None
            else {
                key: value
                for key, value in native_initialization_diagnostics.items()
                if key != "attempts"
            }
        ),
        "initialization_wall_seconds": initialization_wall_seconds,
        "initialization_full_evaluations": initialization_full_evaluations,
        "accounting": result.accounting.to_dict(),
        "metro_initial_clock_closure": metro_initial_clock_closure,
        "effective_execution_schema": (
            result.provenance.effective_execution_schema
        ),
        "effective_algorithm_configuration": (
            result.provenance.effective_algorithm_configuration
        ),
        "effective_runtime_identity": (
            result.provenance.effective_runtime_identity
        ),
        "search_configuration_sha256": (
            result.provenance.search_configuration_sha256
        ),
        "charging_policy": (
            None
            if result.provenance.effective_algorithm_configuration is None
            else result.provenance.effective_algorithm_configuration[
                "charging_policy"
            ]
        ),
        "frvcpy_provenance": {
            "enabled": bool(result.effective_execution.frvcpy_enabled),
            "source": "INFORMSJoC/2020.1035 harvested local snapshot",
            "commit": FRVCPY_COMMIT,
            "license": "Apache-2.0",
            "source_sha256": FRVCPY_SOURCE_SHA256,
        },
        "proposal_mode": args.proposal_mode,
        "proposal_config": args.proposal_config,
        "route_layer_crossover": {
            "enabled": bool(
                result.effective_execution.route_layer_crossover_enabled
            ),
            "operator": "OX_customer_permutation_then_feasibility_split",
            "trip_count_rule": "no_per_vehicle_trip_count_limit",
            "accounting": {
                "proposed": int(result.accounting.route_layer_proposed),
                "decoded": int(result.accounting.route_layer_decoded),
                "entered_evaluation": int(
                    result.accounting.route_layer_entered_evaluation
                ),
                "accepted": int(result.accounting.route_layer_accepted),
                "decode_wall_seconds": float(
                    result.accounting.route_layer_decode_wall_seconds
                ),
                "gap_counts": dict(
                    sorted(result.accounting.route_layer_gap_counts.items())
                ),
            },
            "final_trip_counts_by_vehicle": {
                duty.physical_vehicle_id: len(duty.trips)
                for duty in result.best.duties
                if duty.trips
            },
        },
        "route_engine_wiring": route_engine_wiring,
        "ev_observation": ev_observation,
        "mechanism_off": sorted(mechanism_off),
        "mechanism_enabled": {
            **mechanism_enabled,
            "charge_timing": bool(
                result.effective_execution.include_charging_candidates
            ),
        },
        "mechanism_closure": {
            "violations": list(closure_violations),
            "forbidden_named_proposed_actions": forbidden_proposed_actions,
            "reference_customer_depot_sha256": _string_mapping_sha256(
                reference_depot
            ),
            "final_customer_depot_sha256": _string_mapping_sha256(final_depot),
            "reference_customer_type_sha256": _string_mapping_sha256(reference_type),
            "final_customer_type_sha256": _string_mapping_sha256(final_type),
            "reference_max_trips_per_duty": max(
                (len(duty.trips) for duty in mechanism_reference.duties),
                default=0,
            ),
            "final_max_trips_per_duty": max(
                (len(duty.trips) for duty in result.best.duties),
                default=0,
            ),
            "effective_charge_timing_policy": (
                result.effective_execution.charge_timing_policy
            ),
        },
        "combat_configuration": {
            "enabled": combat_enabled,
            "duty_channels": [
                "depot_collaboration",
                "fairness_cross_depot",
                "multi_trip",
                "time_varying_carbon_charge",
                "whole_duty_type_exchange",
            ] if combat_enabled else [],
            "depot_split_enabled": route_engine.depot_assignment_statistics[
                "enabled"
            ],
            "rebuilt_volume_capacity_enabled": bool(
                route_engine.rebuilt_volume_capacity_enabled
            ),
            "rebuilt_shift_neighbours_only": bool(
                route_engine.rebuilt_shift_neighbours_only
            ),
            "shift_aware_ev_unit_cost_enabled": bool(
                route_engine.shift_aware_ev_unit_cost_enabled
            ),
            "shift_aware_ev_proxy": route_engine.shift_aware_ev_proxy,
            "shift_aware_ev_proxy_validation": shift_proxy_validation,
            "node_operators": list(route_engine.node_operator_names),
            "native_reload_contract": {
                "max_reloads": sorted(
                    {
                        int(
                            route_engine.data.vehicle_type(index).max_reloads
                        )
                        for index in range(
                            route_engine.data.num_vehicle_types
                        )
                    }
                ),
                "reload_depot_counts": sorted(
                    {
                        len(
                            route_engine.data.vehicle_type(index).reload_depots
                        )
                        for index in range(
                            route_engine.data.num_vehicle_types
                        )
                    }
                ),
            },
            "first_trip_prev_night_enabled": (
                effective_first_trip_prev_night
            ),
        },
        "depot_assignment_operator": (
            route_engine.depot_assignment_statistics
        ),
        "dynamic_insertion_operator": {
            "enabled": bool(args.dynamic_insertion_operator),
            "revealed_customer_id": dynamic_revealed_customer,
            "trigger_second": (
                46_800.0 if args.dynamic_insertion_operator else None
            ),
            "accounting": dynamic_insertion_diagnostic,
            "truth_artifacts_read": [],
        },
        "fleet_parameter_class": args.fleet_parameter_class,
        "fleet_parameter_class_id": bundle.fleet_parameter_class_id,
        "has_additional_total_fleet_cap": (
            bundle.has_additional_total_fleet_cap
        ),
        "fleet_caps_by_depot": {
            depot_id: dict(caps)
            for depot_id, caps in bundle.fleet_caps_by_depot.items()
        },
        "fairness_enabled": bool(context.fairness_enabled),
        "fairness_theta": float(context.theta),
        "pi0": {
            "values": dict(context.independent_profit),
            "source_id": context.independent_profit_identity.source_id,
            "sha256": context.independent_profit_identity.value_sha256,
            "externally_frozen": bool(
                context.independent_profit_identity.externally_frozen
            ),
            "formal_reuse_allowed": bool(
                pi0_record is not None
                and pi0_record.get("formal_reuse_allowed", False)
            ),
            "run_kind": (
                "probe" if pi0_record is None else pi0_record["run_kind"]
            ),
            "manifest_path": (
                None
                if args.pi0_manifest is None
                else str(args.pi0_manifest.resolve())
            ),
            "manifest_sha256": pi0_manifest_sha256,
            "selected_package_sha256_by_enterprise": (
                None
                if pi0_record is None
                else pi0_record.get(
                    "selected_package_sha256_by_enterprise"
                )
            ),
        },
        "enterprise_ledger": {
            "schema": enterprise_ledger["schema"],
            "path": enterprise_ledger_path.name,
            "file_sha256": _sha256(enterprise_ledger_path),
            "individual_fingerprint": result.best.fingerprint,
        },
        "participation": {
            "margin": participation_margin,
            "margin_complete": participation_margin_complete,
            "canonical_violation_count": len(participation_violations),
            "satisfied": (
                participation_satisfied if fairness_active else None
            ),
            "physical_feasible": physical_feasible,
            "physical_violation_count": len(physical_violations),
        },
        "initial_population_sha256": identity.value_sha256,
        "preflight_reverse_attempt": reverse_record,
        "second_parent_attempts": attempts,
        "second_parent_rule": (
            "first generated move with EVALUATED status and a distinct fingerprint; "
            "cost and direction were ignored"
            if args.population_mode == "technical_two_parent"
            else (
                (
                    "one disclosed EDF/chain/completion seed; no native random "
                    "draw and no prepopulation local search"
                    if args.enterprise_init_constructor == "legacy_three"
                    else (
                        "one copied-HGS 0.12.2 RNG stream; one make_random "
                        "customer-order draw plus "
                        f"{args.enterprise_init_constructor} construction per "
                        "requested member; no reference candidate and no "
                        "prepopulation local search"
                    )
                )
                if enterprise_slice is not None
                else (
                    "copied HGS 0.12.2 population defaults with witness-seed "
                    "perturbations followed by random-skeleton fallback per "
                    "requested initial member"
                    if args.instance_id == DEPOT_SEARCH_INSTANCE_ID
                    else "copied HGS 0.12.2 population defaults with deterministic "
                    "random-skeleton attempts per requested initial member"
                )
            )
        ),
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "failure_conditions": [
            "input or initial construction failure",
            (
                "final solution incomplete, physically infeasible, or missing participation margins"
                if args.pi0_manifest is not None
                else (
                    "final solution incomplete or infeasible"
                    if enterprise_slice is not None
                    else "initial or final solution incomplete or infeasible"
                )
            ),
            "truth-sentinel mismatch or internal error",
            "abnormal termination",
            "missing customers or demand",
            "incomplete experiment package",
        ],
    }
    if decoder_structure_snapshot is not None:
        metadata["decoder_structure_stats"] = {
            "enabled": True,
            "schema_version": 1,
            "decode_count": len(decoder_structure_snapshot.decoder_calls),
            "path": "decoder_structure_stats.json",
        }
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "run_kind", "instance_id", "enterprise_id", "seed", "iterations",
            "termination_status",
            "initial_feasible", "initial_violations", "initial_cost",
            "best_feasible", "best_violations", "best_cost", "cost_delta",
            "customers_served", "customers_total", "demand_served",
            "demand_total", "crossover_calls", "crossover_changed_parent",
            "sentinel_evaluations", "actual_full_model_evaluations",
            "best_evaluation_source", "run_wall_seconds",
            "initialization_rng_streams", "native_make_random_calls",
            "greedy_repair_calls",
            "prepopulation_local_search_calls", "legacy_initialization_calls",
            "fairness_enabled", "fairness_theta", "pi0_source_id",
            "pi0_sha256", "pi0_externally_frozen",
            "participation_margin_json", "participation_satisfied", "verdict",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "run_kind": "probe",
                "instance_id": args.instance_id,
                "enterprise_id": (
                    None
                    if enterprise_slice is None
                    else enterprise_slice.enterprise_id
                ),
                "seed": args.seed,
                "iterations": result.iterations,
                "termination_status": result.termination_status,
                "initial_feasible": initial_evaluation.feasible,
                "initial_violations": len(initial_evaluation.violations),
                "initial_cost": initial_evaluation.total_cost,
                "best_feasible": result.best_evaluation.feasible,
                "best_violations": len(result.best_evaluation.violations),
                "best_cost": result.best_evaluation.total_cost,
                "cost_delta": result.best_evaluation.total_cost - initial_evaluation.total_cost,
                "customers_served": len(served),
                "customers_total": len(customer_nodes),
                "demand_served": served_demand,
                "demand_total": total_demand,
                "crossover_calls": result.accounting.crossover_calls,
                "crossover_changed_parent": crossover_changed,
                "sentinel_evaluations": result.accounting.sentinel_evaluations,
                "actual_full_model_evaluations": result.accounting.to_dict()["actual_full_model_evaluations"],
                "best_evaluation_source": result.best_evaluation.source,
                "run_wall_seconds": result.accounting.run_wall_seconds,
                "initialization_rng_streams": (
                    None
                    if native_initialization_diagnostics is None
                    else native_initialization_diagnostics["rng_stream_count"]
                ),
                "native_make_random_calls": (
                    None
                    if native_initialization_diagnostics is None
                    else native_initialization_diagnostics[
                        "native_make_random_call_count"
                    ]
                ),
                "greedy_repair_calls": (
                    None
                    if native_initialization_diagnostics is None
                    else native_initialization_diagnostics[
                        "greedy_repair_call_count"
                    ]
                ),
                "prepopulation_local_search_calls": (
                    None
                    if native_initialization_diagnostics is None
                    else native_initialization_diagnostics[
                        "prepopulation_local_search_call_count"
                    ]
                ),
                "legacy_initialization_calls": (
                    None
                    if native_initialization_diagnostics is None
                    else sum(
                        native_initialization_diagnostics[
                            "legacy_self_built_initialization_call_counts"
                        ].values()
                    )
                ),
                "fairness_enabled": bool(context.fairness_enabled),
                "fairness_theta": float(context.theta),
                "pi0_source_id": (
                    context.independent_profit_identity.source_id
                ),
                "pi0_sha256": (
                    context.independent_profit_identity.value_sha256
                ),
                "pi0_externally_frozen": bool(
                    context.independent_profit_identity.externally_frozen
                ),
                "participation_margin_json": json.dumps(
                    participation_margin,
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                ),
                "participation_satisfied": (
                    participation_satisfied if fairness_active else None
                ),
                "verdict": verdict,
            }
        )
    decision = {
        "verdict": verdict,
        "failure_reasons": failure_reasons,
        "what_this_answers": [
            "the real input can or cannot complete one Problem-HGS cycle",
            "complete-Duty crossover and education are wired into one HGS cycle",
            "an accepted incremental improvement is or is not cold-replayed",
            "the supplied standalone Pi0 is evaluated into participation margins",
            "the required evidence package is or is not complete",
        ],
        "what_this_does_not_decide": [
            "algorithm superiority",
            "calibrated convergence iteration limit",
            "formal comparison instance",
            "formal Pi0 values from the approved ten-seed procedure",
            "dynamic-demand effectiveness",
        ],
        "user_decision_changed": False,
    }
    _json(
        output / "best_solution.json",
        {
            "individual_fingerprint": result.best.fingerprint,
            "individual": asdict(result.best),
            "evaluation": {
                "total_cost": result.best_evaluation.total_cost,
                "breakdown": dict(result.best_evaluation.breakdown),
                "feasible": result.best_evaluation.feasible,
                "violations": [asdict(item) for item in result.best_evaluation.violations],
                "participation_margin": dict(result.best_evaluation.participation_margin),
                "source": result.best_evaluation.source,
                "prepared_solution": solution_to_dict(
                    result.best_evaluation.prepared_solution
                ),
            },
            "accounting": result.accounting.to_dict(),
            "charging_prescreen": result.charging_prescreen_accounting,
            "provenance": asdict(result.provenance),
        },
    )
    full_evaluation_result = _format_full_evaluation_result(
        feasible=result.best_evaluation.feasible,
        violation_count=len(result.best_evaluation.violations),
    )
    enterprise_report_ending = ""
    if enterprise_slice is not None:
        probe_outcome = "通过" if acceptance.accepted else "失败"
        next_route = (
            "这个企业支持保留本次构造路径；整条公平线仍要与另一个企业的探针一起判断。"
            if acceptance.accepted
            else (
                "不改班次、不加抽样、不恢复预局部搜索；本轮按用户预批退路继续收尾。"
            )
        )
        enterprise_report_ending = f"""
## 直接给用户

{enterprise_slice.enterprise_id} 的 `{args.enterprise_init_constructor}` 初始化探针真实结局是：**{probe_outcome}**。最终服务 {len(served)}/{len(customer_nodes)} 个客户、{served_demand:.6f}/{total_demand:.6f} kg，完整评价违规 {len(result.best_evaluation.violations)} 项。{next_route}
"""
    if args.pi0_manifest is not None:
        pi0_report = (
            "本轮从固定清单读取一份单种子探索版单干利润基准，参与约束已按 "
            f"`theta={context.theta:.1f}` 打开；来源为 "
            f"`{context.independent_profit_identity.source_id}`。利润余量为 "
            f"`{json.dumps(participation_margin, ensure_ascii=False, sort_keys=True)}`；"
            f"参与约束满足状态为 `{participation_satisfied}`，物理约束违规 "
            f"{len(physical_violations)} 项，参与约束违规 "
            f"{len(participation_violations)} 项。该清单不替代后续十种子正式基准。"
        )
    else:
        pi0_report = (
            "本轮没有读取联合臂 Pi0 清单；单干探针关闭参与约束，"
            "它的中性占位不用于联合搜索或报告结论。"
        )
    report = f"""# Problem-HGS 真实输入单轮探索验证报告

## 结论

本轮判定：`{verdict}`。这是一轮探索版接线和内部一致性检查，不是算法对比实验，也没有替用户确定正式算例、收敛迭代数或论文结论。

真实输入 `{args.instance_id}` 完成了 {result.iterations} 个搜索循环，结束状态为 `{result.termination_status}`。最终服务 {len(served)}/{len(customer_nodes)} 个客户，完成需求量 {served_demand:.6f}/{total_demand:.6f}；{full_evaluation_result}。本轮候选方式为 `{args.proposal_mode}`，具名配置为 `{args.proposal_config}`。完整真值哨兵开关为 `{result.effective_execution.incremental_full_truth_sentinel_enabled}`，实际调用 {result.accounting.sentinel_evaluations} 次。轨迹模式为 `{trajectory_mode}`，内存保留为 `False`。交叉后代相对于交叉前父代是否发生 Duty 内容变化：{crossover_changed}。

初始成本为 {initial_evaluation.total_cost:.12f}，本轮保存解成本为 {result.best_evaluation.total_cost:.12f}。这个差值只用于排查运行过程，不能据此宣称 Problem-HGS 更优，因为本轮只有一个种子、一个循环，也没有同预算强基线。

## 如实保留的异常

预先尝试“反转第一条路线的前两个客户”时，结果为 `{reverse_record['status']}`，错误为：{reverse_record['error']}。该尝试没有被改写成成功，也没有被用于挑选有利结果。第二个父代改按固定生成顺序选取第一个能被完整评价且结构不同的动作，选择时没有看成本好坏。

## 本轮没有解决的事

{pi0_report}本轮固定迭代只用于接线，不是正式收敛实验；该算例没有因此被选定为正式代表算例。算法优越性、公开算例竞争力、私有算例三大实验与五大因素效应仍需后续正式实验回答。
{enterprise_report_ending}
"""
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    finalize_five_file_package(
        output,
        acceptance=acceptance,
        metadata=metadata,
        decision=decision,
        report_text=report,
    )
    print(json.dumps({"output": str(output), "verdict": verdict}, ensure_ascii=False))
    return package_exit_code(acceptance)


if __name__ == "__main__":
    requested_output = (
        None
        if len(sys.argv) < 2 or sys.argv[1].startswith("-")
        else Path(sys.argv[1]).resolve()
    )
    try:
        raise SystemExit(main())
    except Exception as exc:
        if requested_output is not None:
            _write_failure_package(requested_output, exc)
        raise
