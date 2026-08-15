from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from setp_solver.check import check_solution
from setp_solver.cost import CARBON_N_SLOTS
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters, UK_2025_PRICES
from setp_solver.search.alns_wouda import (
    AlnsState,
    SearchPolicy,
    _insertion_options,
    _adaptive_remove_count,
    _try_cv_to_ev_candidates,
    _try_ev_to_cv_candidates,
    run_alns_wouda,
    vehicle_type_swap,
)
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.carbon_operators import low_carbon_charging_share
from setp_solver.search.charging import repair_route_charging
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.candidates import (
    make_shared_initial_solution,
    random_key_to_solution,
    run_candidate,
    run_z1_smoke,
    solution_signature_hash,
    solution_to_random_key,
)
from setp_solver.search.e5_probe import run_e5_probe, slot_charge_table
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, model_cost, penalized_obj, score_candidate, score_reference
from setp_solver.search.feasible_repair import enumerate_feasible_insertions, repair_removed_customers
from setp_solver.search.fleet import FleetLimits, UNBOUNDED_FLEET, fleet_probe_diagnostic, infer_fleet_limits, normalize_solution_vehicle_trips, vehicle_type_semantics_report
from setp_solver.search.gates import b2_feasible_domain_gate
from setp_solver.search.root_cause import _breakdown_for, _operator_summary_rows, solution_churn
from setp_solver.search.scout import scout_reference_algorithms
from setp_solver.solution import ChargingAction, Route, Solution, physical_vehicle_id


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "models" / "data_bundle" / "generated_instances" / "verify_20251113"


def _charging_instance() -> Instance:
    return Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, demand=0.0, due_time=20_000.0),
            Node("C1", "c", 0.0, 0.0, demand=100.0, due_time=20_000.0),
            Node("F1", "f", 0.0, 0.0, demand=0.0, due_time=20_000.0, charge_power_kw=60.0),
        ],
        distance_matrix=[
            [0.0, 100_000.0, 20_000.0],
            [100_000.0, 0.0, 20_000.0],
            [20_000.0, 20_000.0, 0.0],
        ],
    )


def _profile() -> list[dict[str, float]]:
    return [
        {"time_index": idx, "horizon_second_start": float(idx * 1800), "actual_gco2_per_kwh": gamma}
        for idx, gamma in enumerate([300.0, 250.0, 200.0, 50.0, 100.0, *([150.0] * 13)])
    ]


def _legacy_battery_prices() -> PriceParameters:
    return replace(UK_2025_PRICES, B_battery_kwh=80.0)


class SearchGateTests(unittest.TestCase):
    # v2026-06-11: Bundle loader must preserve station pi_s for paper CHARGING_POWER.
    def test_bundle_loader_preserves_station_power(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        station_powers = [node.charge_power_kw for node in bundle.instance.nodes if node.node_type.lower() == "f"]

        self.assertTrue(station_powers)
        self.assertEqual(set(station_powers), {60.0})
        self.assertEqual(len(bundle.carbon_profile), CARBON_N_SLOTS)

    # v2026-06-11: corrected B2 gate uses depot return deadline, not latest station window plus full charge.
    def test_b2_feasible_domain_gate_is_safe_for_fixture(self) -> None:
        gate = b2_feasible_domain_gate(FIXTURE_DIR)

        self.assertTrue(gate.safe)
        self.assertEqual(gate.return_deadline, 32400.0)
        self.assertEqual(gate.window_end, 32400.0)

    # v2026-06-11: G2 charging repair must satisfy CHARGING_START/POWER/BATTERY/TIME_WINDOW and prefer lower gamma.
    def test_charging_repair_feasible_and_carbon_aware(self) -> None:
        instance = _charging_instance()
        route = Route("EV1", "ev", "D0", ["D0", "C1", "D0"])
        prices = _legacy_battery_prices()

        repaired, actions = repair_route_charging(route, instance, _profile(), prices)

        self.assertIn("F1", repaired.node_sequence)
        # v2026-06-12: S0 keeps depot charging in the return-to-next-departure window.
        self.assertEqual([action.station_id for action in actions], ["D0", "F1"])
        self.assertGreaterEqual(actions[0].charge_start_second, 5600.0)
        self.assertEqual(actions[1].charge_start_second, 5400.0)
        violations = [
            v
            for v in check_solution(Solution(routes=[repaired], charging_actions=actions), instance, prices)
            if v.type in {"CHARGING_START", "CHARGING_POWER", "BATTERY", "TIME_WINDOW"}
        ]
        self.assertEqual(violations, [])

    def test_low_carbon_charging_share_uses_actual_gamma_slots(self) -> None:
        instance = _charging_instance()
        prices = _legacy_battery_prices()
        profile = [
            {"slot_index": 0, "actual_gco2_per_kwh": 500.0, "forecast_gco2_per_kwh": 500.0},
            {"slot_index": 1, "actual_gco2_per_kwh": 50.0, "forecast_gco2_per_kwh": 50.0},
            {"slot_index": 2, "actual_gco2_per_kwh": 600.0, "forecast_gco2_per_kwh": 600.0},
            {"slot_index": 3, "actual_gco2_per_kwh": 650.0, "forecast_gco2_per_kwh": 650.0},
        ]
        solution = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "F1", "C1", "D0"])],
            charging_actions=[
                ChargingAction("EV1", "F1", energy_kwh=10.0, occupancy_minutes=30.0, charge_start_second=1800.0),
                ChargingAction("EV1", "F1", energy_kwh=30.0, occupancy_minutes=30.0, charge_start_second=0.0),
            ],
        )

        self.assertAlmostEqual(low_carbon_charging_share(solution, instance, profile, prices), 0.25)

    def test_battery_override_changes_fixed_ev_referee_path(self) -> None:
        instance = _charging_instance()
        profile = _profile()
        solution = Solution(routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])])
        low = replace(UK_2025_PRICES, B_battery_kwh=80.0, initial_ev_battery_kwh=80.0)
        high = replace(UK_2025_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=280.0)

        low_violations = check_solution(solution, instance, low)
        high_violations = check_solution(solution, instance, high)

        self.assertTrue(any(violation.type == "BATTERY" for violation in low_violations))
        self.assertEqual(high_violations, [])

        low_context = EvaluationContext(instance, profile, prices=low)
        high_context = EvaluationContext(instance, profile, prices=high)
        low_objective = score_candidate(solution, low_context)
        high_objective = score_candidate(solution, high_context)

        self.assertGreater(low_objective, high_objective + 1.0)
        self.assertAlmostEqual(high_objective, model_cost(solution, high_context), delta=1e-9)

    # v2026-06-12: H0 verifies fleet metadata and reports charge candidates.
    def test_h0_fleet_diagnostic_finds_ev_capacity_and_charge_candidates(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        cv_seed = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
            introduce_ev=False,
        )

        limits = infer_fleet_limits(FIXTURE_DIR)
        diagnostic = fleet_probe_diagnostic(
            FIXTURE_DIR,
            cv_seed,
            bundle.instance,
            UK_2025_PRICES,
        )

        self.assertEqual((limits.cv, limits.ev), (10, 10))
        self.assertEqual(diagnostic.customer_count, 25)
        self.assertEqual(diagnostic.battery_kwh, 80.0)
        self.assertGreaterEqual(diagnostic.charging_candidate_count, 1)

        legacy = fleet_probe_diagnostic(FIXTURE_DIR, cv_seed, bundle.instance, _legacy_battery_prices())
        self.assertEqual(legacy.battery_kwh, 80.0)
        self.assertGreaterEqual(legacy.charging_candidate_count, 1)

        modern = fleet_probe_diagnostic(
            FIXTURE_DIR,
            cv_seed,
            bundle.instance,
            replace(UK_2025_PRICES, B_battery_kwh=280.0),
        )
        self.assertEqual(modern.battery_kwh, 280.0)
        self.assertEqual(modern.charging_candidate_count, 0)

    def test_fleet_trip_retagger_packs_routes_into_physical_vehicle_cap(self) -> None:
        base = _charging_instance()
        instance = Instance(nodes=base.nodes, distance_matrix=base.distance_matrix, num_cv=1, num_ev=1)
        solution = Solution(
            routes=[
                Route("CV_A", "cv", "D0", ["D0", "C1", "D0"]),
                Route("CV_B", "cv", "D0", ["D0", "F1", "D0"]),
            ]
        )

        packed = normalize_solution_vehicle_trips(solution, instance)

        self.assertEqual([route.vehicle_id for route in packed.routes], ["CV1#T1", "CV1#T2"])
        self.assertEqual(check_solution(packed, instance, UK_2025_PRICES), [])

    def test_fleet_limits_read_hard_caps_from_instance_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            (bundle_dir / "instance.json").write_text(
                json.dumps({"metadata": {"num_cv": 4, "num_ev": 3}}, ensure_ascii=False),
                encoding="utf-8",
            )

            limits = infer_fleet_limits(bundle_dir)

        self.assertEqual((limits.cv, limits.ev), (4, 3))
        self.assertIn("hard fleet caps", limits.source)

    # v2026-06-11: H1 records paper evidence that type is dispatch/choice, not customer-fixed.
    def test_h1_vehicle_type_semantics_report_has_paper_evidence(self) -> None:
        report = vehicle_type_semantics_report()

        self.assertIn("派遣", report.conclusion)
        self.assertTrue(any("K^tau" in line for line in report.evidence_lines))
        self.assertTrue(any("z_k^tau" in line for line in report.evidence_lines))
        self.assertTrue(any("m^g/m^e" in line for line in report.evidence_lines))

    # v2026-06-11: G3 seed solution must be feasible on the real carbon-aligned fixture.
    def test_initial_solution_feasible_and_penalty_preserves_feasible_objective(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
            require_charging_signal=False,
        )
        context = EvaluationContext(
            bundle.instance,
            bundle.carbon_profile,
            prices=UK_2025_PRICES,
        )

        self.assertEqual(check_solution(solution, bundle.instance, UK_2025_PRICES), [])
        self.assertLessEqual(sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"), 10)
        self.assertGreaterEqual(sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"), 1)
        self.assertGreaterEqual(sum(action.energy_kwh for action in solution.charging_actions), 0.0)
        self.assertAlmostEqual(penalized_obj(solution, context), model_cost(solution, context), delta=1e-9)

    # v2026-06-15: Root-cause diagnostics measure structural churn on customer
    # positions only, ignoring depots and charging stations.
    def test_root_cause_solution_churn_counts_customer_position_changes(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        depot = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d")
        station = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "f")
        customers = [node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"][:3]
        base = Solution(routes=[Route("CV1", "cv", depot, [depot, customers[0], station, customers[1], customers[2], depot])])
        same_customers_extra_station = Solution(routes=[Route("CV1", "cv", depot, [depot, station, customers[0], customers[1], customers[2], depot])])
        swapped = Solution(routes=[Route("CV1", "cv", depot, [depot, customers[1], customers[0], customers[2], depot])])
        moved_route = Solution(
            routes=[
                Route("CV1", "cv", depot, [depot, customers[1], customers[2], depot]),
                Route("CV2", "cv", depot, [depot, customers[0], depot]),
            ]
        )

        self.assertEqual(solution_churn(base, same_customers_extra_station, bundle.instance), 0)
        self.assertEqual(solution_churn(base, swapped, bundle.instance), 2)
        self.assertEqual(solution_churn(base, moved_route, bundle.instance), 3)

    # v2026-06-15: Diagnostic score breakdowns must distinguish budgeted
    # candidate scores from free reference/warm-start scoring.
    def test_root_cause_score_breakdown_reference_does_not_consume_budget(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
            require_charging_signal=False,
        )
        context = EvaluationContext(
            bundle.instance,
            bundle.carbon_profile,
            prices=UK_2025_PRICES,
            budget=EvalBudget(limit=5, target=5),
        )

        score_reference(solution, context)
        reference = _breakdown_for(solution, context)
        self.assertEqual(context.budget.count, 0)
        self.assertTrue(reference.feasible)

        score_candidate(solution, context)
        candidate = _breakdown_for(solution, context)
        self.assertEqual(context.budget.count, 1)
        self.assertEqual(context.score_counts["candidate"], 1)
        self.assertAlmostEqual(candidate.objective, candidate.raw_cost, delta=1e-9)

    # v2026-06-15: Root-cause operator summary is the H5 evidence source.
    def test_root_cause_operator_summary_counts_use_accept_and_best(self) -> None:
        rows = [
            {"instance": "I", "algorithm": "ALNS-Wouda", "destroy_op": "D1", "repair_op": "R1", "accepted": "True", "improved_best": "False", "churn": "2", "remove_count_q": "3", "feasible": "True", "penalty": "0"},
            {"instance": "I", "algorithm": "ALNS-Wouda", "destroy_op": "D1", "repair_op": "R1", "accepted": "False", "improved_best": "True", "churn": "0", "remove_count_q": "1", "feasible": "False", "penalty": "100"},
        ]

        summary = _operator_summary_rows(rows)

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["used"], 2)
        self.assertEqual(summary[0]["accepted"], 1)
        self.assertEqual(summary[0]["best_improved"], 1)
        self.assertEqual(summary[0]["avg_churn"], 1.0)

    # v2026-06-11: H2 deterministic witness forces a nonzero EV charging seed under the legacy 80 kWh battery.
    def test_h2_initial_solution_contains_deterministic_ev_charging_witness(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        prices = _legacy_battery_prices()
        solution = build_initial_solution(bundle.instance, bundle.carbon_profile, prices=prices)

        ev_routes = [route for route in solution.routes if route.vehicle_type.lower() == "ev"]
        self.assertTrue(any(route.node_sequence == ["D0", "F2", "C3", "D0"] for route in ev_routes))
        self.assertEqual(check_solution(solution, bundle.instance, prices), [])
        self.assertGreater(sum(action.energy_kwh for action in solution.charging_actions), 0.0)

    # v2026-06-26: finite fleet limits cap physical vehicles, not route/trip rows.
    def test_m0_evheavy_initial_solution_respects_fleet_limits_and_charges(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
            fleet_limits=FleetLimits(cv=3, ev=8, source="test"),
        )

        self.assertEqual(check_solution(solution, bundle.instance, UK_2025_PRICES), [])
        self.assertLessEqual(len({physical_vehicle_id(route.vehicle_id) for route in solution.routes if route.vehicle_type.lower() == "cv"}), 3)
        self.assertLessEqual(len({physical_vehicle_id(route.vehicle_id) for route in solution.routes if route.vehicle_type.lower() == "ev"}), 8)

    # v2026-06-11: H2 vehicle_type_swap can flip a route while preserving feasibility.
    def test_h2_vehicle_type_swap_can_change_type_and_remain_feasible(self) -> None:
        import numpy as np

        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
            require_charging_signal=False,
        )
        state = AlnsState(
            solution,
            EvaluationContext(
                bundle.instance,
                bundle.carbon_profile,
                prices=UK_2025_PRICES,
            ),
            policy=SearchPolicy(require_charging_signal=False),
        )

        swapped = vehicle_type_swap(state, np.random.default_rng(2))

        self.assertNotEqual(swapped.solution, solution)
        self.assertEqual(check_solution(swapped.solution, bundle.instance, UK_2025_PRICES), [])

    # v2026-06-14: ALNS-Wouda vehicle_type_swap must consider both CV->EV and
    # EV->CV candidates and choose using the shared repair scorer.
    def test_vehicle_type_swap_bidirectional_candidates_use_shared_scorer(self) -> None:
        import numpy as np

        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
            require_charging_signal=False,
        )
        policy = SearchPolicy(require_charging_signal=False)
        expected_rng = np.random.default_rng(2)

        cv_to_ev = _try_cv_to_ev_candidates(AlnsState(solution, EvaluationContext(bundle.instance, bundle.carbon_profile, prices=UK_2025_PRICES), policy=policy), np.random.default_rng(2))
        ev_to_cv = _try_ev_to_cv_candidates(AlnsState(solution, EvaluationContext(bundle.instance, bundle.carbon_profile, prices=UK_2025_PRICES), policy=policy), np.random.default_rng(2))
        candidates = [
            *_try_cv_to_ev_candidates(AlnsState(solution, EvaluationContext(bundle.instance, bundle.carbon_profile, prices=UK_2025_PRICES), policy=policy), expected_rng),
            *_try_ev_to_cv_candidates(AlnsState(solution, EvaluationContext(bundle.instance, bundle.carbon_profile, prices=UK_2025_PRICES), policy=policy), expected_rng),
        ]

        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=UK_2025_PRICES)
        swapped = vehicle_type_swap(AlnsState(solution, context, policy=policy), np.random.default_rng(2))

        self.assertGreater(len(cv_to_ev), 0)
        self.assertGreater(len(ev_to_cv), 0)
        self.assertIn(swapped.solution, candidates)
        self.assertEqual(context.score_counts["repair_delta"], len(candidates))
        self.assertEqual(context.score_counts.get("candidate", 0), 0)
        self.assertEqual(check_solution(swapped.solution, bundle.instance, UK_2025_PRICES), [])

    # v2026-06-14: Repair insertion ranking scores full CV and EV candidate
    # solutions through the shared accounting path.
    def test_alns_wouda_repair_insertions_account_cv_and_ev_scores(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        customer_id = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c")
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=UK_2025_PRICES)

        options = _insertion_options(
            Solution(),
            customer_id,
            context,
            SearchPolicy(require_charging_signal=False),
        )

        vehicle_types = {route.vehicle_type.lower() for _, solution in options for route in solution.routes}
        self.assertIn("cv", vehicle_types)
        self.assertIn("ev", vehicle_types)
        self.assertEqual(context.score_counts["repair_delta"], len(options))
        self.assertEqual(context.score_counts.get("candidate", 0), 0)

    # v2026-06-15: Feasible repair options must be route-locally feasible and
    # must not consume complete candidate eval budget.
    def test_feasible_repair_insertions_are_feasible_and_delta_only(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
            require_charging_signal=False,
        )
        customer_id = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c")
        partial_routes = [
            Route(route.vehicle_id, route.vehicle_type, route.home_depot_id, [node for node in route.node_sequence if node != customer_id])
            for route in solution.routes
        ]
        partial = Solution(routes=[route for route in partial_routes if len([node for node in route.node_sequence if node.startswith("C")]) > 0])
        context = EvaluationContext(
            bundle.instance,
            bundle.carbon_profile,
            prices=UK_2025_PRICES,
            budget=EvalBudget(limit=10, target=10),
        )

        options = enumerate_feasible_insertions(partial, customer_id, context, SearchPolicy(require_charging_signal=False))

        self.assertTrue(options)
        self.assertGreater(context.score_counts["repair_delta"], 0)
        self.assertEqual(context.score_counts.get("candidate", 0), 0)
        repaired = repair_removed_customers(partial, [customer_id], context, SearchPolicy(require_charging_signal=False), mode="regret2")
        self.assertIsNotNone(repaired)
        self.assertEqual(check_solution(repaired, bundle.instance, UK_2025_PRICES), [])

    # v2026-06-15: Destroy scale follows the ALNS strong plan and never falls
    # back to the old fixed q=1 behavior.
    def test_alns_wouda_destroy_q_uses_fractional_customer_scale(self) -> None:
        import numpy as np

        with patch.dict("os.environ", {"SETP_ALNS_CRUSH_ADAPTIVE_Q": "1"}):
            draws = [_adaptive_remove_count(100, np.random.default_rng(seed)) for seed in range(20)]
            late_draws = [_adaptive_remove_count(100, np.random.default_rng(seed), progress=1.0) for seed in range(20)]

        self.assertTrue(all(10 <= value <= 40 for value in draws))
        self.assertTrue(any(value > 12 for value in draws))
        self.assertTrue(all(4 <= value <= 13 for value in late_draws))
        self.assertTrue(all(value != 1 for value in draws))

    # v2026-06-11: G4 ALNS-Wouda smoke test must run through the local package without installation.
    def test_alns_wouda_smoke_returns_feasible_not_worse_than_seed(self) -> None:
        result = run_alns_wouda(
            FIXTURE_DIR,
            iterations=1,
            seed=1,
            prices=UK_2025_PRICES,
        )

        self.assertTrue(result.feasible)
        self.assertLessEqual(result.best_obj, result.initial_obj + 1e-9)
        self.assertEqual(result.evaluations, 1)
        self.assertEqual(result.actual_moves, 1)
        self.assertEqual(result.candidate_scores, 1)
        self.assertGreater(result.repair_scores, 0)
        self.assertEqual(result.repair_scores, result.repair_delta_count)
        self.assertIn("destroy", result.operator_counts)
        self.assertIn("repair", result.operator_counts)
        self.assertNotIn("identity_repair", result.operator_counts["repair"])
        self.assertGreaterEqual(result.charging_energy_kwh, 0.0)

    # v2026-06-15: Strong Wouda accounting is one complete score per move.
    def test_alns_wouda_eval_budget_matches_moves_after_repair_failures(self) -> None:
        result = run_alns_wouda(
            FIXTURE_DIR,
            iterations=None,
            eval_budget=30,
            max_runtime_seconds=20.0,
            seed=1,
            prices=UK_2025_PRICES,
        )

        self.assertTrue(result.feasible)
        self.assertEqual(result.evaluations, 30)
        self.assertGreater(result.actual_moves, 0)
        self.assertLessEqual(result.actual_moves, result.evaluations)
        self.assertEqual(result.candidate_scores, 30)

    # v2026-06-11: H3 keeps a nonzero EV charging signal after the short ALNS pass under the legacy 80 kWh battery.
    def test_h3_short_alns_has_nonzero_charging_signal(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        prices = _legacy_battery_prices()
        initial = build_initial_solution(bundle.instance, bundle.carbon_profile, prices=prices)
        result = run_alns_wouda(
            FIXTURE_DIR,
            iterations=1,
            seed=1,
            policy=SearchPolicy(require_charging_signal=True),
            prices=prices,
            initial_solution=initial,
        )

        self.assertGreater(result.charging_energy_kwh, 0.0)

    # v2026-06-11: G5 slot aggregation replays any returned charging under true gamma profile.
    def test_e5_probe_outputs_two_18_slot_tables(self) -> None:
        probe = run_e5_probe(
            FIXTURE_DIR,
            iterations=1,
            seed=1,
            policy=SearchPolicy(require_charging_signal=False),
            allow_zero_charge=True,
            prices=UK_2025_PRICES,
        )

        self.assertEqual(len(probe.carbon_on.rows), CARBON_N_SLOTS)
        self.assertEqual(len(probe.carbon_off.rows), CARBON_N_SLOTS)
        self.assertGreaterEqual(probe.carbon_on.total_charge_kwh, 0.0)
        self.assertGreaterEqual(probe.carbon_off.total_charge_kwh, 0.0)
        self.assertAlmostEqual(
            probe.delta_carbon,
            probe.carbon_off.charge_carbon_kg - probe.carbon_on.charge_carbon_kg,
            delta=1e-9,
        )

    # v2026-06-12: K0/K1 E5 gate must improve under budget and expose timing diagnostics.
    def test_k0_k1_e5_budget_probe_improves_and_reports_timing_freedom(self) -> None:
        probe = run_e5_probe(
            FIXTURE_DIR,
            iterations=5,
            seed=1,
            enforce_k0=True,
            policy=SearchPolicy(require_charging_signal=False),
            allow_zero_charge=True,
            prices=UK_2025_PRICES,
        )

        self.assertLess(probe.carbon_on.run.best_obj, probe.carbon_on.run.initial_obj)
        self.assertLess(probe.carbon_off.run.best_obj, probe.carbon_off.run.initial_obj)
        self.assertGreaterEqual(len(probe.carbon_on.timing_diagnostics), 0)
        self.assertGreaterEqual(len(probe.carbon_off.timing_diagnostics), 0)
        self.assertGreaterEqual(sum(row.gamma_gap for row in probe.carbon_on.timing_diagnostics), 0.0)

    # v2026-06-11: G5 table helper must expose 18 slots even for no-charge solutions.
    def test_slot_charge_table_shape(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        rows = slot_charge_table(
            Solution(),
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
        )

        self.assertEqual(len(rows), CARBON_N_SLOTS)
        self.assertEqual(sum(row.energy_kwh for row in rows), 0.0)

    # v2026-06-11: G6 candidate board is diagnostic-only and must not block on failed imports.
    def test_candidate_scout_returns_status_board(self) -> None:
        board = scout_reference_algorithms(REPO_ROOT)

        self.assertGreaterEqual(len(board), 7)
        self.assertTrue(any(row.name == "ALNS-Wouda" and row.can_import for row in board))

    # v2026-06-12: Z1 candidate codec must round-trip through Solution and the shared checker.
    def test_z1_candidate_codec_round_trip_returns_feasible_solution(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        seed = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
            introduce_ev=False,
        )

        chromosome = solution_to_random_key(seed, bundle.instance)
        decoded = random_key_to_solution(
            chromosome,
            bundle.instance,
            bundle.carbon_profile,
            UK_2025_PRICES,
        )

        self.assertEqual(check_solution(decoded, bundle.instance, UK_2025_PRICES), [])
        served = {
            node_id
            for route in decoded.routes
            for node_id in route.node_sequence
            if node_id.startswith("C")
        }
        expected = {node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"}
        self.assertEqual(served, expected)

    # v2026-06-12: Z1 tiny smoke only proves feasible adapters; formal W1 budgets own collapse checks.
    def test_z1_smoke_board_passes_on_fixture_with_tiny_budget(self) -> None:
        report = run_z1_smoke(
            REPO_ROOT,
            FIXTURE_DIR,
            seed=1,
            eval_budget=8,
            max_runtime_seconds=60.0,
            prices=UK_2025_PRICES,
        )

        self.assertEqual(report.gate, "PASS")
        self.assertTrue(report.alns_wouda_feasible)
        self.assertGreaterEqual(report.feasible_candidate_count, 4)
        self.assertEqual(len(report.rows), 8)
        self.assertTrue(all(row["collapse_status"] != "red" for row in report.rows))

    # v2026-06-12: W1e/W1f require formal-budget diagnostics and no warm-start handback for repaired red algorithms.
    def test_w1_formal_budget_vns_and_dr_alns_leave_shared_seed_with_diagnostics(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        warm_start = make_shared_initial_solution(bundle, UK_2025_PRICES)
        warm_start_hash = solution_signature_hash(warm_start)

        for algorithm in ("VNS@Valdecy", "DR-ALNS"):
            result = run_candidate(
                algorithm,
                FIXTURE_DIR,
                seed=1,
                eval_budget=2000,
                max_runtime_seconds=120.0,
                initial_solution=warm_start,
                prices=UK_2025_PRICES,
            )

            self.assertTrue(result.feasible, algorithm)
            self.assertNotEqual(result.solution_signature_hash, warm_start_hash, algorithm)
            self.assertGreater(result.search_diagnostics["candidate_generated"], 0, algorithm)
            self.assertGreater(result.search_diagnostics["candidate_feasible"], 0, algorithm)
            self.assertGreater(result.search_diagnostics["candidate_accepted"], 0, algorithm)
            self.assertTrue(result.search_diagnostics["diagnosis"], algorithm)

    # v2026-06-14: Candidate adapters report evals as shared scorer calls, not
    # as the number of outer moves attempted by their hand-written loops.
    def test_candidate_adapter_evals_are_shared_scorer_calls(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        warm_start = make_shared_initial_solution(bundle, UK_2025_PRICES)

        for algorithm in (
            "VNS@Valdecy",
            "PyGAD",
            "scikit-opt-GA",
            "scikit-opt-SA",
            "NSGA-II@haris989",
            "ALNS@wangqianlongucas",
            "DR-ALNS",
        ):
            result = run_candidate(
                algorithm,
                FIXTURE_DIR,
                seed=1,
                eval_budget=30,
                max_runtime_seconds=60.0,
                initial_solution=warm_start,
                prices=UK_2025_PRICES,
            )

            self.assertTrue(result.feasible, algorithm)
            self.assertEqual(result.evals, result.candidate_scores, algorithm)
            self.assertGreaterEqual(result.evals, result.actual_moves, algorithm)
            self.assertGreater(result.candidate_scores, 0, algorithm)
            if algorithm == "DR-ALNS":
                self.assertGreater(result.repair_delta_count, 0, algorithm)
                self.assertEqual(result.repair_scores, result.repair_delta_count, algorithm)


if __name__ == "__main__":
    unittest.main()
