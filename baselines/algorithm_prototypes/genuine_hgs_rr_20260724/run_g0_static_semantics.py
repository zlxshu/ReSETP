"""Run the zero-search static semantics gate for the genuine hybrid."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
from typing import Callable

from setp_solver.instance_loader import Instance, Node
from setp_solver.solution import ChargingAction, Route, Solution

from contracts import (
    AlgorithmArm,
    CandidateSource,
    CompleteEvaluationLedger,
    DecoderCacheKey,
    HybridLineageLedger,
    TransferDirection,
)
from hybrid_orchestrator import make_arm_budget_plan
from operator_effects import verify_operator_effect
from operator_plans import (
    OperatorKind,
    bidirectional_cross_depot_segment_plan,
    charge_departure_retiming_plan,
    cross_depot_route_reassignment_plan,
    dynamic_unexecuted_tail_plan,
    time_window_pressure_string_plan,
    vehicle_type_flip_plan,
)
from recreate import remove_customers_from_skeleton
from rr_engine import (
    _bidirectional_exchange_skeleton,
    _select_plan,
    _whole_route_reassignment_skeleton,
)


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
OUT = PACKAGE / "g0_static_semantics_gate_v10"
CONTRACT = ROOT / "docs/handoff/e2_genuine_hybrid_hgs_rr_contract_20260724.md"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _fixture() -> tuple[Instance, Solution, frozenset[str]]:
    nodes = [
        Node("D_GZ", "d", 0, 0, 0, 0, 100, 0),
        Node("D_SZ", "d", 1, 1, 0, 0, 100, 0),
        Node("S1", "f", 0.5, 0.5, 0, 0, 100, 0),
        Node("C1", "c", 0, 1, 1, 0, 80, 1),
        Node("C2", "c", 0, 2, 1, 10, 20, 1),
        Node("C3", "c", 0, 3, 1, 0, 70, 1),
        Node("C4", "c", 1, 2, 1, 0, 60, 1),
        Node("C5", "c", 1, 3, 1, 0, 50, 1),
        Node("C6", "c", 1, 4, 1, 0, 40, 1),
    ]
    size = len(nodes)
    matrix = [
        [
            0.0 if left == right else float(abs(left - right) + 1)
            for right in range(size)
        ]
        for left in range(size)
    ]
    instance = Instance(nodes=nodes, distance_matrix=matrix)
    solution = Solution(
        routes=[
            Route(
                vehicle_id="CV1",
                vehicle_type="cv",
                home_depot_id="D_GZ",
                node_sequence=[
                    "D_GZ",
                    "C1",
                    "C2",
                    "C3",
                    "D_GZ",
                ],
            ),
            Route(
                vehicle_id="EV1",
                vehicle_type="ev",
                home_depot_id="D_SZ",
                node_sequence=[
                    "D_SZ",
                    "C4",
                    "S1",
                    "C5",
                    "C6",
                    "D_SZ",
                ],
            ),
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id="EV1",
                station_id="S1",
                energy_kwh=15.0,
                occupancy_minutes=30.0,
                charge_start_second=25_000.0,
            )
        ],
    )
    customers = frozenset(
        node.node_id for node in nodes if node.node_type.lower() == "c"
    )
    return instance, solution, customers


def _checks() -> list[tuple[str, Callable[[], None]]]:
    instance, solution, customers = _fixture()

    def budgets() -> None:
        assert make_arm_budget_plan(
            AlgorithmArm.COOPERATIVE,
            80,
        ).hgs_epoch_evaluations == (16, 16, 16)
        assert make_arm_budget_plan(
            AlgorithmArm.COOPERATIVE,
            280,
        ).rr_phase_evaluations == (56, 55)

    def budget_ledger() -> None:
        ledger = CompleteEvaluationLedger(
            arm=AlgorithmArm.COOPERATIVE,
            limit=3,
        )
        ledger.register(
            signature="same",
            source=CandidateSource.HGS_ARCHIVE,
            feasible=True,
            objective=10.0,
            violation_count=0,
        )
        duplicate = ledger.register(
            signature="same",
            source=CandidateSource.RUIN_RECREATE,
            feasible=True,
            objective=10.0,
            violation_count=0,
        )
        ledger.register(
            signature="bad",
            source=CandidateSource.RUIN_RECREATE,
            feasible=False,
            objective=None,
            violation_count=1,
        )
        assert duplicate.duplicate_of_index == 1
        ledger.assert_exactly_closed()

    def station_is_not_customer() -> None:
        partial = remove_customers_from_skeleton(
            solution,
            ("C5",),
            known_customer_ids=customers,
        )
        assert "S1" not in partial.routes[1].node_sequence

    def whole_route_effect() -> None:
        plan = cross_depot_route_reassignment_plan(
            solution,
            route_index=0,
            depot_ids=("D_GZ", "D_SZ"),
            customer_ids=customers,
        )
        candidate = _whole_route_reassignment_skeleton(
            solution,
            plan,
            customer_ids=customers,
        )
        assert verify_operator_effect(
            solution,
            candidate,
            plan,
            customer_ids=customers,
        ).passed

    def bidirectional_effect() -> None:
        plan = bidirectional_cross_depot_segment_plan(
            solution,
            first_route_index=0,
            second_route_index=1,
            rng=random.Random(3),
            customer_ids=customers,
            max_segment_length=1,
        )
        candidate = _bidirectional_exchange_skeleton(
            solution,
            plan,
            customer_ids=customers,
        )
        assert verify_operator_effect(
            solution,
            candidate,
            plan,
            customer_ids=customers,
        ).passed

    def type_flip_effect() -> None:
        plan = vehicle_type_flip_plan(
            solution,
            route_index=0,
            customer_ids=customers,
        )
        first = solution.routes[0]
        candidate = Solution(
            routes=[
                Route(
                    first.vehicle_id,
                    "ev",
                    first.home_depot_id,
                    list(first.node_sequence),
                ),
                solution.routes[1],
            ],
            charging_actions=list(solution.charging_actions),
        )
        assert verify_operator_effect(
            solution,
            candidate,
            plan,
            customer_ids=customers,
        ).passed

    def charge_effect() -> None:
        plan = charge_departure_retiming_plan(
            solution,
            route_index=1,
            customer_ids=customers,
        )
        action = solution.charging_actions[0]
        candidate = Solution(
            routes=list(solution.routes),
            charging_actions=[
                ChargingAction(
                    action.vehicle_id,
                    action.station_id,
                    action.energy_kwh,
                    action.occupancy_minutes,
                    action.charge_start_second + 1800.0,
                )
            ],
        )
        assert verify_operator_effect(
            solution,
            candidate,
            plan,
            customer_ids=customers,
        ).passed

    def time_window_effect() -> None:
        plan = time_window_pressure_string_plan(
            solution,
            instance,
            radius=1,
        )
        route_index = plan.route_indices[0]
        route = solution.routes[route_index]
        route_customers = [
            node_id for node_id in route.node_sequence if node_id in customers
        ]
        routes = list(solution.routes)
        routes[route_index] = Route(
            route.vehicle_id,
            route.vehicle_type,
            route.home_depot_id,
            [
                route.home_depot_id,
                *reversed(route_customers),
                route.home_depot_id,
            ],
        )
        candidate = Solution(
            routes=routes,
            charging_actions=list(solution.charging_actions),
        )
        assert verify_operator_effect(
            solution,
            candidate,
            plan,
            customer_ids=customers,
        ).passed

    def time_window_pool_diversifies() -> None:
        selected = {
            time_window_pressure_string_plan(
                solution,
                instance,
                radius=0,
                rng=random.Random(seed),
                candidate_pool_size=6,
            ).removed_customer_ids
            for seed in range(1, 20)
        }
        assert len(selected) > 1

    def single_depot_disables_cross_depot_move() -> None:
        class Bundle:
            fleet_caps_by_depot = {
                "D_GZ": {"num_cv": 2, "num_ev": 1},
            }

        bundle = Bundle()
        bundle.instance = instance
        assert (
            _select_plan(
                Solution(routes=[solution.routes[0]]),
                bundle,
                operator=OperatorKind.CROSS_DEPOT_ROUTE_REASSIGNMENT,
                rng=random.Random(1),
                max_segment_length=4,
                time_window_candidate_pool=8,
                cross_depot_pair_pool=12,
            )
            is None
        )

    def dynamic_tail_effect() -> None:
        plan = dynamic_unexecuted_tail_plan(
            solution,
            route_index=0,
            executed_customer_ids=frozenset({"C1"}),
            customer_ids=customers,
        )
        route = solution.routes[0]
        candidate = Solution(
            routes=[
                Route(
                    route.vehicle_id,
                    route.vehicle_type,
                    route.home_depot_id,
                    ["D_GZ", "C1", "C3", "C2", "D_GZ"],
                ),
                solution.routes[1],
            ],
            charging_actions=list(solution.charging_actions),
        )
        assert verify_operator_effect(
            solution,
            candidate,
            plan,
            customer_ids=customers,
        ).passed

    def bidirectional_lineage() -> None:
        lineage = HybridLineageLedger()
        lineage.add_transfer(
            direction=TransferDirection.HGS_TO_RR,
            parent_signature="h0",
            child_signature="h0",
            parent_objective=100.0,
            child_objective=100.0,
            complete_evaluation_index=10,
            accepted_into_next_hgs_epoch=False,
            next_hgs_epoch=None,
        )
        lineage.add_transfer(
            direction=TransferDirection.RR_TO_HGS,
            parent_signature="h0",
            child_signature="r1",
            parent_objective=100.0,
            child_objective=99.0,
            complete_evaluation_index=20,
            accepted_into_next_hgs_epoch=True,
            next_hgs_epoch=2,
        )
        lineage.add_hgs_descendant(
            epoch=2,
            injected_rr_signature="r1",
            descendant_signature="h2",
            injected_objective=99.0,
            descendant_objective=98.0,
            complete_evaluation_index=30,
        )
        lineage.assert_genuine_cooperation(
            require_post_injection_gain=True,
        )

    def cache_identity() -> None:
        base = dict(
            instance_id="cn-prd-25c-02",
            date="2025-02-12",
            region="prd",
            city="guangzhou",
            price_area_id="guangdong_prd_five_city",
            carbon_source_column="Guangdong",
            diesel_zone="guangdong",
            home_depot_id="D_GZ",
            vehicle_type="ev",
            charge_strategy="integrated",
            carbon_weight=1.0,
            node_sequence=("D_GZ", "C1", "D_GZ"),
            dynamic_state_hash="static",
            runtime_parameter_authority="runtime-v4",
            fleet_authority="fleet-v1",
        )
        first = DecoderCacheKey(**base)
        assert (
            first.digest()
            != DecoderCacheKey(**{**base, "home_depot_id": "D_SZ"}).digest()
        )
        assert (
            first.digest() != DecoderCacheKey(**{**base, "date": "2025-02-13"}).digest()
        )

    return [
        ("budget_split_80_280", budgets),
        ("duplicate_and_infeasible_budget", budget_ledger),
        ("charging_station_excluded_from_customers", station_is_not_customer),
        ("whole_route_reassignment_effect", whole_route_effect),
        ("bidirectional_cross_depot_effect", bidirectional_effect),
        ("vehicle_type_flip_effect", type_flip_effect),
        ("charge_schedule_effect", charge_effect),
        ("time_window_structure_effect", time_window_effect),
        ("time_window_result_blind_diversity", time_window_pool_diversifies),
        (
            "single_depot_cross_depot_operator_disabled",
            single_depot_disables_cross_depot_move,
        ),
        ("dynamic_frozen_prefix_effect", dynamic_tail_effect),
        ("bidirectional_lineage", bidirectional_lineage),
        ("cache_city_date_dynamic_identity", cache_identity),
    ]


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite existing gate: {OUT}")
    OUT.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for check_id, check in _checks():
        try:
            check()
        except Exception as exc:
            rows.append(
                {
                    "check_id": check_id,
                    "status": "FAIL",
                    "detail": f"{type(exc).__name__}:{exc}",
                }
            )
        else:
            rows.append(
                {
                    "check_id": check_id,
                    "status": "PASS",
                    "detail": "",
                }
            )
    passed = all(row["status"] == "PASS" for row in rows)
    timestamp = datetime.now(timezone.utc).isoformat()
    source_files = [
        CONTRACT,
        *sorted(
            path for path in PACKAGE.glob("*.py") if not path.name.startswith("._")
        ),
    ]
    metadata = {
        "schema": "resetp.genuine-hybrid-g0-static.v1",
        "created_at_utc": timestamp,
        "search_evaluations": 0,
        "scope": (
            "static semantics only; real China81 bundle completion and "
            "search remain pending"
        ),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip(),
        "input_hashes": {
            str(path.relative_to(ROOT)): _sha256(path) for path in source_files
        },
    }
    with (OUT / "raw_runs.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["check_id", "status", "detail"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    _write_json(OUT / "metadata.json", metadata)
    decision = {
        "schema": "resetp.genuine-hybrid-g0-static-decision.v1",
        "decision": (
            "PASS_G0_STATIC_SEMANTICS__REAL_BUNDLE_PREFLIGHT_PENDING"
            if passed
            else "HALT_G0_STATIC_SEMANTICS"
        ),
        "passed_checks": sum(row["status"] == "PASS" for row in rows),
        "total_checks": len(rows),
        "search_evaluations": 0,
        "claim_boundary": (
            "Does not prove algorithm quality, real-instance feasibility, or 1+1>2."
        ),
    }
    _write_json(OUT / "decision.json", decision)
    report = "\n".join(
        [
            "# G0 static semantics gate",
            "",
            f"Decision: `{decision['decision']}`.",
            "",
            (
                f"{decision['passed_checks']}/{decision['total_checks']} "
                "zero-search checks passed."
            ),
            "",
            (
                "This gate proves only budget, operator-effect, city/date "
                "cache identity, and bidirectional-lineage semantics. It "
                "does not load a real China81 bundle, run HGS/RR search, or "
                "support any performance claim."
            ),
            "",
        ]
    )
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hash_targets = [
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "report.md",
    ]
    _write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {path.name: _sha256(path) for path in hash_targets},
        },
    )
    if not passed:
        raise SystemExit(2)
    print(decision["decision"])


if __name__ == "__main__":
    main()
