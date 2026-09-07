#!/usr/bin/env python3
"""Enumerate depot coalitions through the existing private Problem-HGS runner.

declared_identity=PROJECT_ADAPTER
code_role=ORCHESTRATION_SCRIPT

Existing components reused: the sealed V3 loader conventions and private run
pipeline in ``run_problem_hgs_private_technical.py``, exact matrix slicing in
``setp_solver.instance_subset``, and native random initialization in
``setp_solver.algorithms.problem_hgs.initialization``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from types import FunctionType, MappingProxyType
from typing import Mapping

import run_problem_hgs_private_technical as private_runner
import setp_solver.china81 as china81_data
from setp_solver.algorithms.problem_hgs.evaluation import (
    DutyEvaluationContext,
    RebuiltRouteConstraintContract,
)
from setp_solver.algorithms.problem_hgs.fleet_registry import (
    register_all_vehicle_slots,
)
from setp_solver.algorithms.problem_hgs.initialization import (
    InitialPopulationResult,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual
from setp_solver.china81 import China81Bundle
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.solution import Solution
from setp_solver.instance_loader import RoadProfileMatrices
from setp_solver.instance_subset import rebuild_instance_matrix
from setp_solver.private_instance_rebuild_20260811 import (
    EV_DAILY_FIXED_PREMIUM_CNY,
)
from setp_solver.search.multitrip_schedule import (
    DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
)


PACKAGE = Path("data/ChinaInstances/china81_suite_prd_fix_v1_20260812")
RUNTIME = Path(
    "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
)


@dataclass(frozen=True)
class LoadedProblem:
    bundle: China81Bundle
    orders_by_customer: Mapping[str, Mapping[str, str]]
    route_contract: RebuiltRouteConstraintContract
    depot_ids: tuple[str, ...]


@dataclass(frozen=True)
class CoalitionProblem:
    label: str
    members: tuple[str, ...]
    bundle: China81Bundle
    context: DutyEvaluationContext
    initial: DutyIndividual
    customer_ids: tuple[str, ...]
    demand_kg: float
    volume_m3: float
    preparation_wall_seconds: float


def _only(rows: list[dict[str, str]], description: str) -> dict[str, str]:
    if len(rows) != 1:
        raise ValueError(f"{description} is not unique")
    return rows[0]


def _matrix_subset(
    path: Path,
    target_ids: list[str],
    source_by_target: Mapping[str, str],
) -> tuple[tuple[float, ...], ...]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    columns = rows[0][1:]
    values = {row[0]: row[1:] for row in rows[1:]}
    source_ids = [source_by_target[node_id] for node_id in target_ids]
    if set(values) != set(columns) or not set(source_ids).issubset(columns):
        raise ValueError(f"matrix does not cover the mapped coalition source: {path}")
    index = {node_id: offset for offset, node_id in enumerate(columns)}
    return tuple(
        tuple(float(values[left][index[right]]) for right in source_ids)
        for left in source_ids
    )


def _load_problem(repo: Path, instance_id: str) -> LoadedProblem:
    package = repo / PACKAGE
    saved = package / "instances" / instance_id
    node_rows = china81_data._read_csv(saved / "nodes.csv")
    order_rows = china81_data._read_csv(saved / "orders.csv")
    orders = {row["customer_id"]: row for row in order_rows}
    source_mapping = {
        row["new_node_id"]: row["source_node_id"]
        for row in china81_data._read_csv(saved / "source_mapping.csv")
    }
    if set(source_mapping) != {row["node_id"] for row in node_rows}:
        raise ValueError("source mapping does not cover the instance nodes")
    reference = json.loads(
        (saved / "matrix_reference.json").read_text(encoding="utf-8")
    )
    default_orders = (repo / china81_data._ORDER_RELATIVE).resolve()

    def read_rows(path: Path) -> list[dict[str, str]]:
        resolved = path.resolve()
        if resolved == (package / "instance_catalog.csv").resolve():
            return [
                (
                    {**row, "node_count": str(len(node_rows))}
                    if row["instance_id"] == instance_id
                    else row
                )
                for row in china81_data._read_csv(resolved)
            ]
        if resolved == default_orders:
            return order_rows
        return china81_data._read_csv(resolved)

    def load_matrices(
        matrix_root: Path,
        nodes: list[object],
    ) -> Mapping[str, RoadProfileMatrices]:
        node_ids = [str(getattr(node, "node_id")) for node in nodes]
        return {
            profile: RoadProfileMatrices(
                **{
                    field: _matrix_subset(
                        matrix_root / profile / filename,
                        node_ids,
                        source_mapping,
                    )
                    for field, filename in (
                        ("distance_m", "road_distance_m.csv"),
                        ("duration_s", "road_duration_s.csv"),
                        ("sum_v2d_m3_s2", "road_sum_v2d_m3_s2.csv"),
                    )
                }
            )
            for profile in ("cv", "ev")
        }

    loader_globals = dict(china81_data.load_china81_bundle.__globals__)
    loader_globals.update(
        _STATIC_INPUT_RELATIVE=PACKAGE,
        _FLEET_AUTHORITY_RELATIVE=PACKAGE,
        _read_csv=read_rows,
        load_profiled_road_matrices=load_matrices,
    )
    loader = FunctionType(
        china81_data.load_china81_bundle.__code__,
        loader_globals,
        china81_data.load_china81_bundle.__name__,
        china81_data.load_china81_bundle.__defaults__,
        china81_data.load_china81_bundle.__closure__,
    )
    loader.__kwdefaults__ = china81_data.load_china81_bundle.__kwdefaults__
    bundle = loader(
        repo,
        instance_id,
        road_matrix_authority=reference["source_authority"],
        runtime_parameter_authority=RUNTIME,
        fleet_parameters=private_runner.ENDOGENOUS_FLEET_PARAMETERS,
        matrix_source_from_catalog=True,
        customer_home_depot_from_orders=True,
    )
    bundle = replace(
        bundle,
        source_paths=MappingProxyType(
            {
                **bundle.source_paths,
                "orders": str((saved / "orders.csv").relative_to(repo)),
                "matrix_reference": str(
                    (saved / "matrix_reference.json").relative_to(repo)
                ),
            }
        ),
    )
    depot_ids = tuple(
        node.node_id for node in bundle.instance.nodes if node.node_type == "d"
    )
    shift = json.loads((saved / "shift_contract.json").read_text(encoding="utf-8"))
    contract = RebuiltRouteConstraintContract(
        source_id=str((saved / "shift_contract.json").relative_to(repo)),
        customer_shift_by_id=MappingProxyType({customer_id: row["shift_id"] for customer_id, row in orders.items()}),
        customer_volume_m3_by_id=MappingProxyType({customer_id: float(row["source_volume_m3"]) for customer_id, row in orders.items()}),
        shift_window_second_by_id=MappingProxyType({key: (float(row["start_minute"]) * 60.0, float(row["end_minute"]) * 60.0) for key, row in shift["shifts"].items()}),
        vehicle_volume_capacity_m3=float(shift["vehicle_volume_capacity_m3"]),
    )
    return LoadedProblem(bundle, MappingProxyType(orders), contract, depot_ids)


def _label(members: tuple[str, ...], depots: tuple[str, ...]) -> str:
    indices = [depots.index(member) + 1 for member in members]
    return "GRAND" if len(members) == len(depots) else "+".join(f"D{index}" for index in indices)


def _slice_problem(source: LoadedProblem, requested: tuple[str, ...]) -> CoalitionProblem:
    started = perf_counter()
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("coalition must contain distinct depot ids")
    unknown = set(requested) - set(source.depot_ids)
    if unknown:
        raise ValueError(f"unknown coalition depots: {sorted(unknown)}")
    members = tuple(depot for depot in source.depot_ids if depot in requested)
    homes = source.bundle.customer_home_depot
    customer_ids = tuple(
        node.node_id
        for node in source.bundle.instance.nodes
        if node.node_type == "c" and homes[node.node_id] in members
    )
    customer_set = set(customer_ids)
    selected_nodes = tuple(
        node
        for node in source.bundle.instance.nodes
        if node.node_type == "f"
        or (node.node_type == "d" and node.node_id in members)
        or (node.node_type == "c" and node.node_id in customer_set)
    )
    selected_caps = MappingProxyType({member: source.bundle.fleet_caps_by_depot[member] for member in members})
    instance = replace(
        rebuild_instance_matrix(source.bundle.instance, selected_nodes),
        num_cv=sum(int(row["num_cv"]) for row in selected_caps.values()),
        num_ev=sum(int(row["num_ev"]) for row in selected_caps.values()),
    )
    station_ids = {node.node_id for node in selected_nodes if node.node_type == "f"}
    bundle = replace(
        source.bundle,
        instance=instance,
        customer_home_depot=MappingProxyType({customer_id: homes[customer_id] for customer_id in customer_ids}),
        fleet_caps_by_depot=selected_caps,
        charger_scenario_by_node=MappingProxyType({node_id: source.bundle.charger_scenario_by_node[node_id] for node_id in (*members, *sorted(station_ids))}),
        enterprise_depot_by_id=MappingProxyType({}),
    )
    shifts = {customer_id: source.route_contract.customer_shift_by_id[customer_id] for customer_id in customer_ids}
    contract = replace(
        source.route_contract,
        source_id=f"{source.route_contract.source_id}/coalition/{'+'.join(members)}",
        customer_shift_by_id=MappingProxyType(shifts),
        customer_volume_m3_by_id=MappingProxyType({customer_id: source.route_contract.customer_volume_m3_by_id[customer_id] for customer_id in customer_ids}),
        shift_window_second_by_id=MappingProxyType({shift_id: source.route_contract.shift_window_second_by_id[shift_id] for shift_id in set(shifts.values())}),
    )
    neutral = {member: 1.0 for member in members}
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=neutral,
        prior_profit={member: 0.0 for member in members},
        theta=0.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
        fairness_enabled=False,
        ev_daily_fixed_premium_cny=EV_DAILY_FIXED_PREMIUM_CNY,
        shift_aware_departure_enabled=True,
        rebuilt_route_constraints=contract,
    )
    empty = register_all_vehicle_slots(
        DutyIndividual(duties=(), unserved_customers=customer_ids, source="coalition-native-random"),
        bundle,
    )
    demand = sum(float(instance.node_lookup[item].demand) for item in customer_ids)
    volume = sum(float(contract.customer_volume_m3_by_id[item]) for item in customer_ids)
    expected = {customer_id for customer_id, home in homes.items() if home in members}
    charger_ids = set(members) | station_ids
    if (
        customer_set != expected
        or set(bundle.customer_home_depot) != customer_set
        or set(bundle.fleet_caps_by_depot) != set(members)
        or set(bundle.charger_scenario_by_node) != charger_ids
        or set(contract.customer_shift_by_id) != customer_set
        or set(contract.customer_volume_m3_by_id) != customer_set
        or len(instance.distance_matrix) != len(selected_nodes)
    ):
        raise RuntimeError("coalition slice does not preserve its source facts")
    return CoalitionProblem(
        _label(members, source.depot_ids),
        members,
        bundle,
        context,
        empty,
        customer_ids,
        demand,
        volume,
        perf_counter() - started,
    )


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _enrich_output(output: Path, coalition: CoalitionProblem, elapsed: float) -> bool:
    metadata = _load_json(output / "metadata.json")
    decision = _load_json(output / "decision.json")
    best = _load_json(output / "best_solution.json")
    with (output / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    row = _only(rows, "raw run row")
    evaluation = best["evaluation"]
    assert isinstance(evaluation, dict)
    violations = evaluation["violations"]
    assert isinstance(violations, list)
    served_customers = int(row["customers_served"])
    served_demand = float(row["demand_served"])
    total_cost = float(evaluation["total_cost"])
    feasible = bool(evaluation["feasible"])
    termination = row["termination_status"]
    failure_reasons = list(decision.get("failure_reasons", []))
    if len(violations) != 0:
        failure_reasons.append("coalition best solution has violations")
    acceptance = private_runner.assess_run(
        termination_ok=termination == "STOPPED_BY_CALLER",
        feasible_ok=feasible and len(violations) == 0,
        customers_complete=served_customers == len(coalition.customer_ids),
        demand_complete=math.isclose(served_demand, coalition.demand_kg, rel_tol=0.0, abs_tol=1e-9),
        extra_failure_reasons=failure_reasons,
        success_verdict=private_runner.SUCCESS_VERDICT,
        failure_verdict=private_runner.FAILURE_VERDICT,
    )
    result = {
        "label": coalition.label,
        "members": list(coalition.members),
        "customer_count": len(coalition.customer_ids),
        "demand_kg": coalition.demand_kg,
        "volume_m3": coalition.volume_m3,
        "customers_served": served_customers,
        "demand_served_kg": served_demand,
        "total_cost_cny": total_cost,
        "feasible": feasible,
        "violation_count": len(violations),
        "termination_status": termination,
        "preparation_wall_seconds": coalition.preparation_wall_seconds,
        "driver_wall_seconds": elapsed,
    }
    metadata["coalition"] = result
    initial_population = metadata.get("initial_population")
    if isinstance(initial_population, dict):
        initial_population["reference_candidate_included"] = False
    decision["coalition"] = result
    report = (output / "report.md").read_text(encoding="utf-8")
    report = report.replace(
        f"本轮判定：`{decision.get('verdict')}`。",
        f"本轮判定：`{acceptance.verdict}`。",
        1,
    )
    report += (
        "\n## 联盟格\n\n"
        f"联盟 `{coalition.label}`：{', '.join(coalition.members)}。"
        f"客户 {served_customers}/{len(coalition.customer_ids)}，"
        f"需求 {served_demand:.6f}/{coalition.demand_kg:.6f} kg，"
        f"总成本 {total_cost:.12f} CNY，可行性 {feasible}，"
        f"违规数 {len(violations)}。\n"
    )
    private_runner.finalize_run_output(
        output,
        acceptance=acceptance,
        metadata=metadata,
        decision=decision,
        report_text=report,
    )
    fields = [*rows[0], "coalition_label", "coalition_members"]
    row["verdict"] = acceptance.verdict
    row["coalition_label"] = coalition.label
    row["coalition_members"] = "|".join(coalition.members)
    with (output / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    return acceptance.accepted


def _union_seed(
    seed_root: Path,
    source: LoadedProblem,
    coalition: CoalitionProblem,
) -> DutyIndividual:
    """Merge the members' singleton best solutions into one feasible seed.

    The union of singleton solutions is itself a feasible coalition solution,
    so seeding it makes c(S) <= sum of member costs hold by construction and
    the search can only improve on the partition.
    """

    routes: list = []
    actions: list = []
    services: list = []
    for member in coalition.members:
        label = _label((member,), source.depot_ids)
        path = seed_root / label / "run_1" / "best_solution.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        solution = solution_from_dict(payload["evaluation"]["prepared_solution"])
        routes.extend(solution.routes)
        actions.extend(solution.charging_actions)
        services.extend(solution.cross_site_services)
    merged = Solution(
        routes=routes,
        charging_actions=actions,
        cross_site_services=services,
    )
    individual = DutyIndividual.from_solution(
        merged,
        customer_node_ids=coalition.customer_ids,
        source="union-of-singletons",
    )
    return register_all_vehicle_slots(individual, coalition.bundle)


def _run_one(root: Path, coalition: CoalitionProblem) -> bool:
    output = root / coalition.label / "run_1"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    original_build_context = private_runner._build_context
    original_build_population = private_runner.build_initial_population
    original_route_engine = private_runner.IndependentKernelDutyRouteProposalEngine
    original_argv = sys.argv
    started = perf_counter()
    error: Exception | None = None

    def injected_context(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        neutral = {member: 1.0 for member in coalition.members}
        return coalition.bundle, coalition.initial, neutral, coalition.context

    def random_population(*args: object, **kwargs: object) -> object:
        # A complete injected seed (union of singleton solutions) becomes the
        # reference candidate; empty seeds keep the pure-random construction.
        kwargs["include_reference_candidate"] = (
            not coalition.initial.unserved_customers
        )
        kwargs["require_complete_feasible"] = True
        kwargs["witness_seed"] = None
        built = original_build_population(*args, **kwargs)
        if not isinstance(built, InitialPopulationResult):
            raise TypeError("unexpected initial-population result")
        feasible_index = next(
            index
            for index, (candidate, evaluation) in enumerate(
                zip(built.candidates, built.evaluations, strict=True)
            )
            if evaluation.feasible and not candidate.unserved_customers
        )
        order = (feasible_index, *(
            index for index in range(built.actual_size) if index != feasible_index
        ))
        return replace(
            built,
            candidates=tuple(built.candidates[index] for index in order),
            evaluations=tuple(built.evaluations[index] for index in order),
        )

    def coalition_route_engine(*args: object, **kwargs: object) -> object:
        kwargs.update(
            rebuilt_volume_capacity_enabled=True,
            rebuilt_shift_neighbours_only=True,
            shift_aware_ev_unit_cost_enabled=True,
        )
        return original_route_engine(*args, **kwargs)

    try:
        private_runner._build_context = injected_context
        private_runner.build_initial_population = random_population
        private_runner.IndependentKernelDutyRouteProposalEngine = (
            coalition_route_engine
        )
        sys.argv = [
            str(Path(private_runner.__file__).resolve()),
            str(output),
            "--instance-id",
            coalition.bundle.instance_id,
            "--fleet-parameter-class",
            "endogenous",
            "--depot-assignment-operator",
            "--arm",
            f"coalition-enumeration/{coalition.label}",
        ]
        try:
            private_runner.main()
        # Mirror the private entry's failure-package boundary; never mark it done.
        except Exception as exc:  # noqa: BLE001
            private_runner._write_failure_package(output, exc)
            error = exc
    finally:
        private_runner._build_context = original_build_context
        private_runner.build_initial_population = original_build_population
        private_runner.IndependentKernelDutyRouteProposalEngine = original_route_engine
        sys.argv = original_argv
    if error is not None:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "label": coalition.label,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return False
    accepted = _enrich_output(output, coalition, perf_counter() - started)
    return accepted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    parser.add_argument(
        "--coalition",
        required=True,
        help="comma-separated depot ids or all-singletons",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--seed-from-dirs",
        default=None,
        help=(
            "comma-separated run dirs whose best solutions are merged into "
            "the coalition seed (overrides --seed-singletons-root)"
        ),
    )
    parser.add_argument(
        "--seed-singletons-root",
        type=Path,
        default=None,
        help=(
            "root holding D1..Dn singleton products; multi-member coalitions "
            "seed the union of their members' best solutions"
        ),
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    source = _load_problem(repo, args.instance_id)
    if args.coalition == "all-singletons":
        requested = [(depot,) for depot in source.depot_ids]
        requested.sort(
            key=lambda members: sum(
                home in members for home in source.bundle.customer_home_depot.values()
            )
        )
    else:
        requested = [tuple(item.strip() for item in args.coalition.split(",") if item.strip())]
    for members in requested:
        coalition = _slice_problem(source, members)
        if args.seed_from_dirs:
            from dataclasses import replace as _dc_replace
            routes=[]; actions=[]; services=[]
            for run_dir in args.seed_from_dirs.split(','):
                payload=json.loads((Path(run_dir.strip())/"best_solution.json").read_text(encoding="utf-8"))
                sol=solution_from_dict(payload["evaluation"]["prepared_solution"])
                routes.extend(sol.routes); actions.extend(sol.charging_actions); services.extend(sol.cross_site_services)
            merged=Solution(routes=routes, charging_actions=actions, cross_site_services=services)
            seed=DutyIndividual.from_solution(merged, customer_node_ids=coalition.customer_ids, source="union-of-products")
            coalition=_dc_replace(coalition, initial=register_all_vehicle_slots(seed, coalition.bundle))
        elif args.seed_singletons_root is not None and len(coalition.members) >= 2:
            from dataclasses import replace as _dc_replace
            coalition = _dc_replace(
                coalition,
                initial=_union_seed(
                    args.seed_singletons_root.resolve(),
                    source,
                    coalition,
                ),
            )
        print(
            json.dumps(
                {
                    "status": "STARTING",
                    "label": coalition.label,
                    "members": coalition.members,
                    "customers": len(coalition.customer_ids),
                    "demand_kg": coalition.demand_kg,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if not _run_one(args.output_dir.resolve(), coalition):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
