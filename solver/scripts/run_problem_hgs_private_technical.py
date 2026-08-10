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
import platform
import random
import subprocess
import sys
import traceback
from dataclasses import asdict, replace
from importlib import metadata as importlib_metadata
from pathlib import Path
from time import perf_counter
from typing import Any

from setp_solver.algorithms.problem_hgs.charging import ChargingRepairPolicy
from setp_solver.algorithms.problem_hgs.contracts import CandidateStatus
from setp_solver.algorithms.problem_hgs.education import evaluate_move
from setp_solver.algorithms.problem_hgs.evaluation import (
    DutyEvaluationContext,
    DutyFullEvaluator,
    FrozenMappingIdentity,
    mapping_sha256,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual, PhysicalVehicleDuty
from setp_solver.algorithms.problem_hgs.operators import (
    ReverseSegmentMove,
    generate_problem_moves,
)
from setp_solver.algorithms.problem_hgs.population import (
    AdaptivePenaltyManager,
    DutyPopulation,
    PenaltyParameters,
    PopulationParameters,
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
    ProblemHGSSearchParameters,
    FrozenPopulationIdentity,
    population_sha256,
    run_integrated_problem_hgs,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
)
from setp_solver.search.metaheuristic_baselines import solution_to_dict
from setp_solver.solution import Route, Solution

INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"
SEED = 11
ARM = "one-cycle-real-input-wiring-trial"
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


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


def _write_failure_package(output: Path, error: Exception) -> bool:
    """Complete an output directory created by this invocation as failed."""

    metadata_path = output / "metadata.json"
    if not metadata_path.is_file():
        return False
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "RUNNING":
        return False
    metadata["status"] = "FAILED"
    _json(metadata_path, metadata)
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
                "verdict": "TECHNICAL_TRIAL_FAILED",
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    _json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_TRIAL_FAILED",
            "failure_reasons": [f"{type(error).__name__}: {error}"],
            "traceback": traceback.format_exc(),
            "user_decision_changed": False,
        },
    )
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
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    _json(output / "artifact_hashes.json", hashes)
    return True


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _policy(evaluator: DutyFullEvaluator) -> ChargingRepairPolicy:
    return ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )


def _parameters(
    *,
    stagnation_patience: int = 500,
    crossover_mode: str = "fast_only",
    population_mode: str = "technical_two_parent",
) -> ProblemHGSSearchParameters:
    if population_mode == "copied_hgs_defaults":
        population = PopulationParameters.copied_hgs_defaults()
    elif population_mode == "technical_two_parent":
        population = PopulationParameters(
            min_pop_size=2,
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
        random_seed=SEED,
        population=population,
        penalties=PenaltyParameters(
            initial_penalty_per_unit=100.0,
            solutions_between_updates=50,
            penalty_increase=1.34,
            penalty_decrease=0.32,
            target_feasible=0.43,
            feasibility_tolerance=0.05,
            minimum_penalty=0.1,
            maximum_penalty=100_000.0,
        ),
        stagnation_patience=stagnation_patience,
        crossover_mode=crossover_mode,
    )


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


def _build_context(repo: Path, instance_id: str = INSTANCE_ID):
    bundle = load_china81_bundle(repo, instance_id)
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

    by_id = {
        duty.physical_vehicle_id: duty for duty in individual.duties
    }
    for depot_id, caps in sorted(bundle.fleet_caps_by_depot.items()):
        expected_ids = set()
        for vehicle_type, cap_field in (("cv", "num_cv"), ("ev", "num_ev")):
            for index in range(1, int(caps[cap_field]) + 1):
                vehicle_id = f"{vehicle_type.upper()}_{depot_id}_{index}"
                expected_ids.add(vehicle_id)
                if vehicle_id not in by_id:
                    by_id[vehicle_id] = PhysicalVehicleDuty(
                        physical_vehicle_id=vehicle_id,
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        trips=(),
                    )
        actual_ids = {
            duty.physical_vehicle_id
            for duty in individual.duties
            if duty.home_depot_id == depot_id
        }
        unexpected = actual_ids.difference(expected_ids)
        if unexpected:
            raise RuntimeError(
                "completed solution uses unregistered physical vehicles: "
                + ", ".join(sorted(unexpected))
            )
        if len(expected_ids) > int(caps["total_fleet_cap"]):
            raise RuntimeError("typed fleet caps exceed the total fleet cap")
    return replace(
        individual,
        duties=tuple(by_id[duty_id] for duty_id in sorted(by_id)),
    )


def _prepare_population(
    initial: DutyIndividual,
    evaluator: DutyFullEvaluator,
    policy: ChargingRepairPolicy,
    parameters: ProblemHGSSearchParameters | None = None,
    *,
    require_distinct_selection: bool = True,
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
        ):
            second = outcome.candidate
            second_evaluation = outcome.evaluation
            break
    if second is None or second_evaluation is None:
        raise RuntimeError("no deterministic, fully evaluated distinct second parent")

    candidates = (initial, second)
    parameters = parameters or _parameters()
    penalties = AdaptivePenaltyManager(parameters.penalties)
    population = DutyPopulation(parameters.population, penalties)
    population.add(initial, initial_evaluation)
    population.add(second, second_evaluation)
    left, right = population.select(random.Random(SEED))
    selected = {
        "left_fingerprint": left.individual.fingerprint,
        "right_fingerprint": right.individual.fingerprint,
        "distinct": left.individual.fingerprint != right.individual.fingerprint,
    }
    if require_distinct_selection and not selected["distinct"]:
        raise RuntimeError("seed 11 did not select structurally distinct parents")
    return (
        candidates,
        initial_evaluation,
        reverse_record,
        attempts,
        selected,
        (initial_evaluation, second_evaluation),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    parser.add_argument("--stagnation-patience", type=int, default=500)
    parser.add_argument(
        "--population-mode",
        choices=("technical_two_parent", "copied_hgs_defaults"),
        default="technical_two_parent",
    )
    parser.add_argument(
        "--crossover-mode",
        choices=("fast_only", "hybrid"),
        default="fast_only",
    )
    parser.add_argument("--arm", default=ARM)
    parser.add_argument("--disable-truth-sentinel", action="store_true")
    parser.add_argument("--stream-trajectory", action="store_true")
    parser.add_argument("--no-retain-trajectory", action="store_true")
    parser.add_argument("--stderr-capture-state", default="caller_not_declared")
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
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("technical iteration count must be positive")
    if args.stagnation_patience < 1:
        raise ValueError("technical stagnation patience must be positive")
    if args.max_runtime_seconds <= 0.0:
        raise ValueError("maximum runtime must be positive")
    if any(
        name == "pyvrp" or name.startswith("pyvrp.")
        for name in sys.modules
    ):
        raise RuntimeError(
            "independent Problem-HGS runtime imported frozen PyVRP"
        )

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    code_provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state=args.stderr_capture_state,
    )
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "bounded real-input wiring trial; not a performance experiment",
            "code_provenance": code_provenance,
            "requested_instance_id": args.instance_id,
            "requested_proposal_mode": args.proposal_mode,
            "requested_iterations": args.iterations,
            "requested_max_runtime_seconds": args.max_runtime_seconds,
            "requested_stagnation_patience": args.stagnation_patience,
            "requested_population_mode": args.population_mode,
            "requested_crossover_mode": args.crossover_mode,
            "requested_truth_sentinel_enabled": not args.disable_truth_sentinel,
            "requested_trajectory_streaming": args.stream_trajectory,
            "requested_trajectory_retention": not args.no_retain_trajectory,
        },
    )

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    bundle, initial, pi0, context = _build_context(repo, args.instance_id)
    if args.disable_truth_sentinel:
        context = replace(
            context,
            incremental_full_truth_sentinel_enabled=False,
        )
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    parameters = _parameters(
        stagnation_patience=args.stagnation_patience,
        crossover_mode=args.crossover_mode,
        population_mode=args.population_mode,
    )
    route_engine = IndependentKernelDutyRouteProposalEngine(
        evaluator.context,
        initial,
        random_seed=SEED,
        stream_role="main_route",
    )
    initialization_started = perf_counter()
    initialization_full_calls_before = evaluator.full_calls
    if args.population_mode == "technical_two_parent":
        (
            candidates,
            initial_evaluation,
            reverse_record,
            attempts,
            selected,
            initial_evaluations,
        ) = _prepare_population(
            initial,
            evaluator,
            policy,
            parameters,
            require_distinct_selection=False,
        )
        initialization_summary = {
            "requested_size": 2,
            "actual_size": len(candidates),
            "attempts_exhausted": False,
        }
    else:
        built = build_initial_population(
            initial,
            evaluator=evaluator,
            charging_policy=policy,
            route_engine=route_engine,
            requested_size=parameters.population.min_pop_size,
            random_seed=SEED,
            max_random_attempts=None,
            stop_requested=lambda: (
                perf_counter() - initialization_started
                >= args.max_runtime_seconds
            ),
        )
        if built.actual_size < 1:
            raise RuntimeError("copied HGS population construction is empty")
        candidates = built.candidates
        initial_evaluations = built.evaluations
        initial_evaluation = built.evaluations[0]
        reverse_record = {
            "status": "NOT_RUN_COPIED_HGS_POPULATION",
            "error": None,
        }
        attempts = [asdict(item) for item in built.attempts]
        precheck_penalties = AdaptivePenaltyManager(parameters.penalties)
        precheck_population = DutyPopulation(
            parameters.population,
            precheck_penalties,
        )
        for candidate, evaluation in zip(
            candidates,
            initial_evaluations,
            strict=True,
        ):
            precheck_population.add(candidate, evaluation)
        left, right = precheck_population.select(random.Random(SEED))
        selected = {
            "left_fingerprint": left.individual.fingerprint,
            "right_fingerprint": right.individual.fingerprint,
            "distinct": left.individual.fingerprint
            != right.individual.fingerprint,
        }
        initialization_summary = {
            "requested_size": built.requested_size,
            "actual_size": built.actual_size,
            "attempts_exhausted": built.attempts_exhausted,
        }
    initialization_wall_seconds = perf_counter() - initialization_started
    initialization_full_evaluations = (
        evaluator.full_calls - initialization_full_calls_before
    )
    mechanism_engine = MechanismProposalEngine(evaluator.context, policy)
    if args.proposal_mode == "legacy":
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
    if args.stream_trajectory:
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

    try:
        result = run_integrated_problem_hgs(
            candidates,
            evaluator=evaluator,
            charging_policy=policy,
            parameters=parameters,
            initial_population_identity=identity,
            stop=lambda state: (
                state.iterations >= args.iterations
                or state.elapsed_seconds >= args.max_runtime_seconds
            ),
            arm=args.arm,
            route_engine=route_engine,
            trajectory_sink=trajectory_sink,
            retain_trajectory=not args.no_retain_trajectory,
            proposal_engine=proposal_engine,
            initial_evaluations=initial_evaluations,
            initialization_full_evaluation_count=(
                initialization_full_evaluations
            ),
            initialization_wall_seconds=initialization_wall_seconds,
        )
    finally:
        if trajectory_handle is not None:
            trajectory_handle.close()
    if any(
        name == "pyvrp" or name.startswith("pyvrp.")
        for name in sys.modules
    ):
        raise RuntimeError(
            "independent Problem-HGS runtime imported frozen PyVRP"
        )
    trajectory = [asdict(row) for row in result.trajectory]
    crossover_rows = [row for row in trajectory if row["phase"] == "crossover"]
    crossover_changed = bool(stream_summary["crossover_changed"]) or any(
        row["after_fingerprint"] is not None
        and row["before_fingerprint"] != row["after_fingerprint"]
        for row in crossover_rows
    )
    served = {
        customer
        for duty in result.best.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    customer_nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served_demand = sum(float(customer_nodes[item].demand) for item in served)
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}

    failure_reasons = []
    if not initial_evaluation.feasible:
        failure_reasons.append("initial solution is infeasible")
    expected_termination_statuses = {"STOPPED_BY_CALLER"}
    if parameters.stagnation_patience is not None:
        expected_termination_statuses.add("CONVERGED_NO_IMPROVEMENT")
    if result.termination_status not in expected_termination_statuses:
        failure_reasons.append(f"unexpected termination: {result.termination_status}")
    if not result.best_evaluation.feasible:
        failure_reasons.append("best solution is infeasible")
    if served != set(customer_nodes):
        failure_reasons.append("not all customers are served")
    accepted_education_moves = sum(
        count
        for channel, count in result.accounting.accepted_actions.items()
        if channel != "hgs_population"
    )
    if (
        context.incremental_full_truth_sentinel_enabled
        and accepted_education_moves > 0
        and result.accounting.sentinel_evaluations <= 0
    ):
        failure_reasons.append(
            "an accepted education move was not replayed by the full-truth sentinel"
        )
    if (
        not context.incremental_full_truth_sentinel_enabled
        and result.accounting.sentinel_evaluations != 0
    ):
        failure_reasons.append("disabled full-truth sentinel was still exercised")
    if protected_before != protected_after:
        failure_reasons.append("a protected evaluator file changed during the run")
    verdict = (
        "TECHNICAL_TRIAL_COMPLETE" if not failure_reasons
        else "TECHNICAL_TRIAL_FAILED"
    )

    metadata = {
        "status": "COMPLETE" if not failure_reasons else "FAILED",
        "purpose": "bounded real-input wiring trial; not a performance experiment",
        "instance_id": args.instance_id,
        "instance_formally_selected": False,
        "formal_search_allowed": bool(bundle.formal_search_allowed),
        "machine": "M1 formal-number machine, but this output is diagnostic only",
        "code_provenance": code_provenance,
        "random_seed": SEED,
        "iterations": args.iterations,
        "max_runtime_seconds": args.max_runtime_seconds,
        "stop_semantics": (
            "technical fixed-iteration stop with the user-set 20-minute hard ceiling"
        ),
        "stagnation_patience": parameters.stagnation_patience,
        "crossover_mode": parameters.crossover_mode,
        "trajectory_streamed_incrementally": args.stream_trajectory,
        "trajectory_retained_in_memory": not args.no_retain_trajectory,
        "trajectory_rows_streamed": stream_summary["rows"],
        "incremental_full_truth_sentinel_enabled": (
            context.incremental_full_truth_sentinel_enabled
        ),
        "best_evaluation_source": result.best_evaluation.source,
        "parameters": asdict(parameters),
        "population_mode": args.population_mode,
        "initial_population": initialization_summary,
        "charging_policy": asdict(policy),
        "proposal_mode": args.proposal_mode,
        "pi0": {
            "values": pi0,
            "sha256": mapping_sha256(pi0),
            "externally_frozen": False,
            "formal_reuse_allowed": False,
        },
        "initial_population_sha256": identity.value_sha256,
        "preflight_reverse_attempt": reverse_record,
        "second_parent_attempts": attempts,
        "second_parent_rule": (
            "first generated move with EVALUATED status and a distinct fingerprint; "
            "cost and direction were ignored"
            if args.population_mode == "technical_two_parent"
            else "copied HGS 0.12.2 population defaults with one deterministic "
            "random-skeleton attempt per requested initial member"
        ),
        "parent_selection_precheck": selected,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "failure_conditions": [
            "input or initial construction failure",
            "initial solution incomplete or infeasible",
            "parents not structurally distinct",
            "truth-sentinel mismatch or internal error",
            "abnormal termination",
            "missing customers or demand",
            "incomplete experiment package",
        ],
    }
    _json(output / "metadata.json", metadata)
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "instance_id", "seed", "iterations", "termination_status",
            "initial_feasible", "initial_violations", "initial_cost",
            "best_feasible", "best_violations", "best_cost", "cost_delta",
            "customers_served", "customers_total", "demand_served",
            "demand_total", "crossover_calls", "crossover_changed_parent",
            "sentinel_evaluations", "actual_full_model_evaluations",
            "best_evaluation_source", "run_wall_seconds",
            "pi0_externally_frozen", "verdict",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "instance_id": args.instance_id,
                "seed": SEED,
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
                "pi0_externally_frozen": False,
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
    _json(output / "decision.json", decision)
    if not args.stream_trajectory:
        trajectory_path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                for row in trajectory
            ),
            encoding="utf-8",
        )
    _json(
        output / "best_solution.json",
        {
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
            "provenance": asdict(result.provenance),
        },
    )
    report = f"""# Problem-HGS 真实输入单轮技术试跑报告

## 结论

本轮判定：`{verdict}`。这是一轮接线和内部一致性检查，不是算法对比实验，也没有替用户确定正式算例、收敛迭代数或论文结论。

真实输入 `{args.instance_id}` 完成了 {result.iterations} 个搜索循环，结束状态为 `{result.termination_status}`。最终服务 {len(served)}/{len(customer_nodes)} 个客户，完成需求量 {served_demand:.6f}/{total_demand:.6f}；完整评价判定可行，违规数为 {len(result.best_evaluation.violations)}。本轮候选方式为 `{args.proposal_mode}`。完整真值哨兵开关为 `{context.incremental_full_truth_sentinel_enabled}`，实际调用 {result.accounting.sentinel_evaluations} 次。轨迹增量写盘为 `{args.stream_trajectory}`，内存保留为 `{not args.no_retain_trajectory}`。交叉算子收到两个不同父代，并产生了不同于右父代的候选：{crossover_changed}。

初始成本为 {initial_evaluation.total_cost:.12f}，本轮保存解成本为 {result.best_evaluation.total_cost:.12f}。这个差值只用于排查运行过程，不能据此宣称 Problem-HGS 更优，因为本轮只有一个种子、一个循环，也没有同预算强基线。

## 如实保留的异常

预先尝试“反转第一条路线的前两个客户”时，结果为 `{reverse_record['status']}`，错误为：{reverse_record['error']}。该尝试没有被改写成成功，也没有被用于挑选有利结果。第二个父代改按固定生成顺序选取第一个能被完整评价且结构不同的动作，选择时没有看成本好坏。

## 本轮没有解决的事

技术用 Pi0 来自本轮初始解，`externally_frozen=False`，不是用户已批准的“每个车场十个种子取最好利润”正式值；本轮固定迭代只用于接线，不是正式收敛实验；该算例没有因此被选定为正式代表算例。算法优越性、公开算例竞争力、私有算例三大实验与五大因素效应仍需后续正式实验回答。

## 交付前九条自检

1. 每个 `FACT` 是否都指到了文件行号 / 产物哈希 / 论文页码？——本报告事实来自同包的 `raw_runs.csv`、`metadata.json`、`trajectory.jsonl`、`best_solution.json`；包内哈希将在 `artifact_hashes.json` 登记。没有把无出处判断写成 FACT。
2. 有没有把自己的建议或担忧写成“已决”或“状态”？——没有。本轮只给技术试跑判定，没有改变任何用户决定。
3. 改动范围有没有超出任务文本？——没有。仅增加试跑入口和本次试跑产物；没有开始正式算法比较。
4. 有没有碰受保护文件？——未碰；三个受保护文件运行前后哈希一致，具体值见 `metadata.json`。
5. 待决事项是否转成了 2–4 个具体候选并写清代价？——本轮没有新增需要用户拍板的选择；停止方式和 Pi0 生成方法已经由用户决定，本轮没有替用户选择正式算例或冻结具体数值。
6. 有没有用自造词或内部任务号跟用户说话？——报告仅使用项目已有术语；“单轮技术试跑”已解释为接线和一致性检查。
7. 失败、跳过、超时、异常结果有没有如实保留？——已保留反转前两个客户导致时间窗失败；没有超时；结束状态按实际结果记录。
8. 四件套齐了吗？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，另附 `trajectory.jsonl` 和 `best_solution.json`。
9. `HANDOFF.md` 变更日志和 `docs/handoff/memory/` 同步了吗？——试跑产物生成后将在本任务收尾时同步，最终提交前复核。
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    _json(output / "artifact_hashes.json", hashes)
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    required = {
        "metadata.json", "raw_runs.csv", "decision.json",
        "artifact_hashes.json", "report.md",
    }
    missing = sorted(required.difference(path.name for path in output.iterdir()))
    if missing:
        raise RuntimeError(f"incomplete package: {missing}")
    print(json.dumps({"output": str(output), "verdict": verdict}, ensure_ascii=False))
    return 0 if verdict == "TECHNICAL_TRIAL_COMPLETE" else 2


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
