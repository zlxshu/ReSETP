from __future__ import annotations

from pathlib import Path
import unittest

from setp_solver.check import check_solution
from setp_solver.cost import CARBON_N_SLOTS
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.alns_wouda import AlnsState, SearchPolicy, run_alns_wouda, vehicle_type_swap
from setp_solver.search.bundle import load_search_bundle
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
from setp_solver.search.evaluation import EvaluationContext, model_cost, penalized_obj
from setp_solver.search.fleet import FleetLimits, UNBOUNDED_FLEET, fleet_probe_diagnostic, infer_fleet_limits, vehicle_type_semantics_report
from setp_solver.search.gates import b2_feasible_domain_gate
from setp_solver.search.scout import scout_reference_algorithms
from setp_solver.solution import Route, Solution


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

        repaired, actions = repair_route_charging(route, instance, _profile())

        self.assertIn("F1", repaired.node_sequence)
        # v2026-06-12: S0 keeps depot charging in the return-to-next-departure window.
        self.assertEqual([action.station_id for action in actions], ["D0", "F1"])
        self.assertGreaterEqual(actions[0].charge_start_second, 5600.0)
        self.assertEqual(actions[1].charge_start_second, 5400.0)
        violations = [v for v in check_solution(Solution(routes=[repaired], charging_actions=actions), instance) if v.type in {"CHARGING_START", "CHARGING_POWER", "BATTERY", "TIME_WINDOW"}]
        self.assertEqual(violations, [])

    # v2026-06-12: H0 verifies fleet count is unbounded and routes can need charging if made EV.
    def test_h0_fleet_diagnostic_finds_ev_capacity_and_charge_candidates(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        cv_seed = build_initial_solution(bundle.instance, bundle.carbon_profile, introduce_ev=False)

        limits = infer_fleet_limits(FIXTURE_DIR)
        diagnostic = fleet_probe_diagnostic(FIXTURE_DIR, cv_seed, bundle.instance)

        self.assertEqual((limits.cv, limits.ev), (UNBOUNDED_FLEET, UNBOUNDED_FLEET))
        self.assertEqual(diagnostic.customer_count, 25)
        self.assertEqual(diagnostic.battery_kwh, 80.0)
        self.assertGreaterEqual(diagnostic.charging_candidate_count, 1)

    # v2026-06-11: H1 records paper evidence that type is dispatch/choice, not customer-fixed.
    def test_h1_vehicle_type_semantics_report_has_paper_evidence(self) -> None:
        report = vehicle_type_semantics_report()

        self.assertIn("派遣", report.conclusion)
        self.assertTrue(any(":190" in line for line in report.evidence_lines))
        self.assertTrue(any(":218" in line for line in report.evidence_lines))
        self.assertTrue(any(":665" in line for line in report.evidence_lines))

    # v2026-06-11: G3 seed solution must be feasible on the real carbon-aligned fixture.
    def test_initial_solution_feasible_and_penalty_preserves_feasible_objective(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(bundle.instance, bundle.carbon_profile)
        context = EvaluationContext(bundle.instance, bundle.carbon_profile)

        self.assertEqual(check_solution(solution, bundle.instance), [])
        self.assertLessEqual(sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"), 10)
        self.assertGreaterEqual(sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"), 1)
        self.assertGreater(sum(action.energy_kwh for action in solution.charging_actions), 0.0)
        self.assertAlmostEqual(penalized_obj(solution, context), model_cost(solution, context), delta=1e-9)

    # v2026-06-11: H2 deterministic witness forces a nonzero EV charging seed for E5.
    def test_h2_initial_solution_contains_deterministic_ev_charging_witness(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(bundle.instance, bundle.carbon_profile)

        ev_routes = [route for route in solution.routes if route.vehicle_type.lower() == "ev"]
        self.assertTrue(any(route.node_sequence == ["D0", "F2", "C3", "D0"] for route in ev_routes))
        self.assertEqual(check_solution(solution, bundle.instance), [])
        self.assertGreater(sum(action.energy_kwh for action in solution.charging_actions), 0.0)

    # v2026-06-12: M0/M1 EV-heavy seed must honor a low CV cap and keep real charging stake.
    def test_m0_evheavy_initial_solution_respects_fleet_limits_and_charges(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
            fleet_limits=FleetLimits(cv=3, ev=8, source="test"),
        )

        self.assertEqual(check_solution(solution, bundle.instance), [])
        self.assertLessEqual(sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"), 3)
        self.assertLessEqual(sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"), 8)
        self.assertGreaterEqual(len(solution.charging_actions), 2)
        self.assertGreater(sum(action.energy_kwh for action in solution.charging_actions), 50.0)

    # v2026-06-11: H2 vehicle_type_swap can flip a route while preserving feasibility.
    def test_h2_vehicle_type_swap_can_change_type_and_remain_feasible(self) -> None:
        import numpy as np

        bundle = load_search_bundle(FIXTURE_DIR)
        solution = build_initial_solution(bundle.instance, bundle.carbon_profile)
        state = AlnsState(
            solution,
            EvaluationContext(bundle.instance, bundle.carbon_profile),
            policy=SearchPolicy(require_charging_signal=False),
        )

        swapped = vehicle_type_swap(state, np.random.default_rng(2))

        self.assertNotEqual(swapped.solution, solution)
        self.assertEqual(check_solution(swapped.solution, bundle.instance), [])

    # v2026-06-11: G4 ALNS-Wouda smoke test must run through the local package without installation.
    def test_alns_wouda_smoke_returns_feasible_not_worse_than_seed(self) -> None:
        result = run_alns_wouda(FIXTURE_DIR, iterations=1, seed=1)

        self.assertTrue(result.feasible)
        self.assertLessEqual(result.best_obj, result.initial_obj + 1e-9)
        self.assertGreater(result.evaluations, 0)
        self.assertGreater(result.charging_energy_kwh, 0.0)

    # v2026-06-11: H3 keeps a nonzero EV charging signal after the short ALNS pass.
    def test_h3_short_alns_has_nonzero_charging_signal(self) -> None:
        result = run_alns_wouda(FIXTURE_DIR, iterations=1, seed=1)

        self.assertGreater(result.charging_energy_kwh, 0.0)

    # v2026-06-11: G5 slot aggregation replays any returned charging under true gamma profile.
    def test_e5_probe_outputs_two_18_slot_tables(self) -> None:
        probe = run_e5_probe(FIXTURE_DIR, iterations=1, seed=1)

        self.assertEqual(len(probe.carbon_on.rows), CARBON_N_SLOTS)
        self.assertEqual(len(probe.carbon_off.rows), CARBON_N_SLOTS)
        self.assertGreater(probe.carbon_on.total_charge_kwh, 0.0)
        self.assertGreater(probe.carbon_off.total_charge_kwh, 0.0)
        self.assertAlmostEqual(
            probe.delta_carbon,
            probe.carbon_off.charge_carbon_kg - probe.carbon_on.charge_carbon_kg,
            delta=1e-9,
        )

    # v2026-06-12: K0/K1 E5 gate must improve under budget and expose timing diagnostics.
    def test_k0_k1_e5_budget_probe_improves_and_reports_timing_freedom(self) -> None:
        probe = run_e5_probe(FIXTURE_DIR, iterations=5, seed=1, enforce_k0=True)

        self.assertLess(probe.carbon_on.run.best_obj, probe.carbon_on.run.initial_obj)
        self.assertLess(probe.carbon_off.run.best_obj, probe.carbon_off.run.initial_obj)
        self.assertTrue(probe.carbon_on.timing_diagnostics)
        self.assertTrue(probe.carbon_off.timing_diagnostics)
        self.assertGreaterEqual(sum(row.gamma_gap for row in probe.carbon_on.timing_diagnostics), 0.0)

    # v2026-06-11: G5 table helper must expose 18 slots even for no-charge solutions.
    def test_slot_charge_table_shape(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        rows = slot_charge_table(Solution(), bundle.instance, bundle.carbon_profile)

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
        seed = build_initial_solution(bundle.instance, bundle.carbon_profile, introduce_ev=False)

        chromosome = solution_to_random_key(seed, bundle.instance)
        decoded = random_key_to_solution(chromosome, bundle.instance, bundle.carbon_profile)

        self.assertEqual(check_solution(decoded, bundle.instance), [])
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
        report = run_z1_smoke(REPO_ROOT, FIXTURE_DIR, seed=1, eval_budget=8, max_runtime_seconds=60.0)

        self.assertEqual(report.gate, "PASS")
        self.assertTrue(report.alns_wouda_feasible)
        self.assertGreaterEqual(report.feasible_candidate_count, 4)
        self.assertEqual(len(report.rows), 8)
        self.assertTrue(all(row["collapse_status"] != "red" for row in report.rows))

    # v2026-06-12: W1e/W1f require formal-budget diagnostics and no warm-start handback for repaired red algorithms.
    def test_w1_formal_budget_vns_and_dr_alns_leave_shared_seed_with_diagnostics(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        warm_start = make_shared_initial_solution(bundle)
        warm_start_hash = solution_signature_hash(warm_start)

        for algorithm in ("VNS@Valdecy", "DR-ALNS"):
            result = run_candidate(
                algorithm,
                FIXTURE_DIR,
                seed=1,
                eval_budget=2000,
                max_runtime_seconds=120.0,
                initial_solution=warm_start,
            )

            self.assertTrue(result.feasible, algorithm)
            self.assertNotEqual(result.solution_signature_hash, warm_start_hash, algorithm)
            self.assertGreater(result.search_diagnostics["candidate_generated"], 0, algorithm)
            self.assertGreater(result.search_diagnostics["candidate_feasible"], 0, algorithm)
            self.assertGreater(result.search_diagnostics["candidate_accepted"], 0, algorithm)
            self.assertTrue(result.search_diagnostics["diagnosis"], algorithm)


if __name__ == "__main__":
    unittest.main()
