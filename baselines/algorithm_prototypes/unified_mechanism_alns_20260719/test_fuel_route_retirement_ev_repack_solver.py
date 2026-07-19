"""Zero-search tests for fuel-route retirement and EV-aware repacking."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import fuel_route_retirement_ev_repack_solver as solver  # noqa: E402
import fast_mechanism_completion as fast_completion  # noqa: E402
from contextual_expert_fixtures import (  # noqa: E402
    PLATEAU_BUNDLE,
    PRICES_280,
    plateau_solution,
)
from fast_mechanism_completion import (  # noqa: E402
    FastCompletionResult,
)
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import (  # noqa: E402
    EvalBudget,
    EvaluationContext,
)
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)


SAVED_WITNESSES = HERE / "contextual_expert_p1_training_gate/solution_witnesses.json"


def _score(value: float) -> solver.RoutePlanScore:
    return solver.RoutePlanScore(
        proxy_cost=float(value),
        variant_count=1,
        cv_proxy_cost=float(value),
        ev_proxy_cost=None,
    )


def _saved_final(instance: str, arm: str) -> Solution:
    payload = json.loads(SAVED_WITNESSES.read_text(encoding="utf-8"))
    for row in payload.values():
        if any(
            use.get("kind") == "final"
            and use.get("instance") == instance
            and use.get("arm") == arm
            for use in row.get("uses", [])
        ):
            raw = row["solution"]
            return Solution(
                routes=[
                    Route(
                        str(route["vehicle_id"]),
                        str(route["vehicle_type"]),
                        str(route["home_depot_id"]),
                        [str(node_id) for node_id in route["node_sequence"]],
                    )
                    for route in raw.get("routes", [])
                ],
                charging_actions=[
                    ChargingAction(
                        str(action["vehicle_id"]),
                        str(action["station_id"]),
                        float(action["energy_kwh"]),
                        float(action["occupancy_minutes"]),
                        float(action["charge_start_second"]),
                        int(action.get("charge_day_offset", 0)),
                    )
                    for action in raw.get(
                        "charging_actions",
                        [],
                    )
                ],
                cross_site_services=[
                    CrossSiteService(
                        str(item["customer_id"]),
                        str(item["served_by_depot_id"]),
                    )
                    for item in raw.get(
                        "cross_site_services",
                        [],
                    )
                ],
            )
    raise AssertionError(f"missing saved final: {instance}/{arm}")


def _empty_completion_activity() -> dict[str, int]:
    return {
        "route_proxy_evaluations": 0,
        "route_local_schedule_evaluations": 0,
        "full_feasibility_checks": 0,
        "complete_candidate_evaluations": 0,
        "complete_route_search_evaluations": 0,
        "search_candidate_score_calls": 0,
    }


class FuelRouteRetirementSolverTest(unittest.TestCase):
    def test_semantic_hash_ignores_only_collection_order(self) -> None:
        first = Solution(
            routes=[
                Route("V1", "cv", "D0", ["D0", "C1", "D0"]),
                Route("V2", "ev", "D1", ["D1", "C2", "D1"]),
            ],
            charging_actions=[
                ChargingAction("V2", "S1", 10.0, 5.0, 100.0, 0),
                ChargingAction("V2", "S2", 5.0, 2.5, 200.0, 0),
            ],
            cross_site_services=[
                CrossSiteService("C1", "D0"),
                CrossSiteService("C2", "D1"),
            ],
        )
        reordered = Solution(
            routes=list(reversed(first.routes)),
            charging_actions=list(reversed(first.charging_actions)),
            cross_site_services=list(reversed(first.cross_site_services)),
        )

        self.assertNotEqual(
            solver._full_content_hash(first),
            solver._full_content_hash(reordered),
        )
        self.assertEqual(
            solver._semantic_solution_hash(first),
            solver._semantic_solution_hash(reordered),
        )

    def test_regret2_places_unique_option_customer_first(self) -> None:
        plans = (
            solver.RoutePlan(0, "D0", ()),
            solver.RoutePlan(1, "D1", ()),
        )

        def scorer(plan: solver.RoutePlan) -> solver.RoutePlanScore | None:
            allowed = {
                (0, ()): 0.0,
                (1, ()): 0.0,
                (0, ("A",)): 1.0,
                (0, ("B",)): 2.0,
                (1, ("B",)): 5.0,
                (0, ("A", "B")): 3.0,
                (0, ("B", "A")): 4.0,
            }
            value = allowed.get((plan.original_index, plan.customers))
            return None if value is None else _score(value)

        repaired, trace = solver._regret2_repair(
            plans,
            ("B", "A"),
            scorer,
            blocked_original_indices={},
            activity=None,
        )

        self.assertIsNotNone(repaired)
        self.assertEqual(
            trace["insertions"][0]["customer_id"],
            "A",
        )
        self.assertTrue(trace["insertions"][0]["only_feasible_position"])
        self.assertEqual(
            sorted(customer for plan in repaired or () for customer in plan.customers),
            ["A", "B"],
        )

    def test_one_level_ejection_cannot_return_to_origin(self) -> None:
        direct_plans = (
            solver.RoutePlan(0, "D0", ()),
            solver.RoutePlan(1, "D1", ("X",)),
            solver.RoutePlan(2, "D2", ("Y",)),
        )

        def scorer(plan: solver.RoutePlan) -> solver.RoutePlanScore | None:
            allowed = {
                (0, ()): 0.0,
                (1, ()): 0.0,
                (2, ("Y",)): 1.0,
                (0, ("X",)): 1.0,
                (1, ("X",)): 1.0,
                (1, ("A",)): 1.0,
            }
            value = allowed.get((plan.original_index, plan.customers))
            return None if value is None else _score(value)

        direct, direct_trace = solver._regret2_repair(
            direct_plans,
            ("A",),
            scorer,
            blocked_original_indices={},
            activity=None,
        )
        self.assertIsNone(direct)
        self.assertEqual(
            direct_trace["reason"],
            "no_feasible_insertion",
        )

        ejection_plans = (
            solver.RoutePlan(0, "D0", ()),
            solver.RoutePlan(1, "D1", ()),
            solver.RoutePlan(2, "D2", ("Y",)),
        )
        repaired, trace = solver._regret2_repair(
            ejection_plans,
            ("A", "X"),
            scorer,
            blocked_original_indices={"X": 1},
            activity=None,
        )

        self.assertIsNotNone(repaired)
        assert repaired is not None
        self.assertEqual(repaired[0].customers, ("X",))
        self.assertEqual(repaired[1].customers, ("A",))
        self.assertNotIn("X", repaired[1].customers)
        self.assertEqual(len(trace["insertions"]), 2)

    def test_nonfinite_route_score_fails_closed(self) -> None:
        plans = (solver.RoutePlan(0, "D0", ()),)

        def scorer(plan: solver.RoutePlan) -> solver.RoutePlanScore:
            return _score(0.0 if not plan.customers else float("nan"))

        repaired, trace = solver._regret2_repair(
            plans,
            ("A",),
            scorer,
            blocked_original_indices={},
            activity=None,
        )
        self.assertIsNone(repaired)
        self.assertEqual(trace["reason"], "no_feasible_insertion")

    def test_completion_route_search_ledger_is_mandatory(self) -> None:
        activity = solver._new_activity(plateau_solution())
        with self.assertRaises(RuntimeError):
            solver._accumulate_completion_activity(
                activity,
                {
                    "route_proxy_evaluations": 0,
                    "route_local_schedule_evaluations": 0,
                    "full_feasibility_checks": 0,
                },
                kind="test",
            )
        with self.assertRaises(RuntimeError):
            solver._accumulate_completion_activity(
                activity,
                {
                    "route_proxy_evaluations": 0,
                    "route_local_schedule_evaluations": 0,
                    "full_feasibility_checks": 0,
                    "complete_route_search_evaluations": True,
                },
                kind="test",
            )

    def test_fast_completion_rejects_nested_search_self_report(
        self,
    ) -> None:
        source = _saved_final(
            "L-main-threeshift-25c-01",
            "control",
        )
        bundle = load_search_bundle(
            REPO / "models/data_bundle/generated_instances/"
            "L-main_size_preserving_v2_archive_20260710/"
            "L-main-threeshift-25c-01"
        )
        joint = {
            "objective_delta": 0.0,
            "exact_decoder_updates": 0,
            "route_proxy_evaluations": 0,
            "feasibility_checks": 0,
            "complete_evaluations": 1,
        }
        carbon = {
            "objective_delta": 0.0,
            "exact_decoder_updates": 0,
            "actions_retimed": 0,
            "route_local_schedule_evaluations": 0,
            "feasibility_checks": 0,
            "complete_evaluations": 0,
        }
        with (
            patch.object(
                fast_completion,
                "exact_joint_fleet_charge_decode",
                return_value=(source, 0.0, joint),
            ),
            patch.object(
                fast_completion,
                "carbon_aware_depot_retime",
                return_value=(source, 0.0, carbon),
            ),
            patch.object(
                fast_completion,
                "check_solution",
                return_value=[],
            ),
            self.assertRaises(RuntimeError),
        ):
            fast_completion.apply_fast_route_local_completion(
                source,
                bundle,
                prices=PRICES_280,
            )

    def test_repair_is_deterministic(self) -> None:
        plans = (
            solver.RoutePlan(0, "D0", ()),
            solver.RoutePlan(1, "D1", ()),
        )

        def scorer(plan: solver.RoutePlan) -> solver.RoutePlanScore | None:
            if len(plan.customers) > 2:
                return None
            return _score(float(len(plan.customers) + 0.1 * plan.original_index))

        first = solver._regret2_repair(
            plans,
            ("C2", "C1"),
            scorer,
            blocked_original_indices={},
            activity=None,
        )
        second = solver._regret2_repair(
            plans,
            ("C2", "C1"),
            scorer,
            blocked_original_indices={},
            activity=None,
        )
        self.assertEqual(first, second)

    def test_real_plateau_enumeration_preserves_coverage_and_slots(
        self,
    ) -> None:
        source = plateau_solution()
        bundle = load_search_bundle(PLATEAU_BUNDLE)
        owners = infer_customer_home_depots(bundle.instance)
        context = EvaluationContext(
            bundle.instance,
            bundle.carbon_profile,
            prices=PRICES_280,
            budget=EvalBudget(limit=0, target=0),
            customer_home_depot=owners,
            allow_cross_depot=True,
        )
        activity = solver._new_activity(source)
        scorer = solver.RoutePlanScorer(
            context,
            owners,
            activity,
        )
        candidates = solver._enumerate_repack_candidates(
            source,
            context,
            scorer,
            solver.FuelRouteRetirementConfig(),
            8,
            activity,
        )

        self.assertGreater(len(candidates), 0)
        expected = solver._customer_counter(
            source,
            bundle.instance,
        )
        for candidate in candidates:
            self.assertEqual(
                solver._customer_counter(
                    candidate.neutral_solution,
                    bundle.instance,
                ),
                expected,
            )
            self.assertLessEqual(
                len(candidate.neutral_solution.routes),
                len(source.routes),
            )
            self.assertNotEqual(
                solver._route_skeleton_signature(
                    candidate.neutral_solution,
                    bundle.instance,
                ),
                solver._route_skeleton_signature(
                    source,
                    bundle.instance,
                ),
            )
            if candidate.seed_kind == "one_level_ejection":
                self.assertTrue(
                    solver._ejection_holds(
                        candidate,
                        candidate.neutral_solution,
                        bundle.instance,
                    )
                )

    def test_all_ev_saved_solution_is_exact_noop(self) -> None:
        source = _saved_final(
            "L-main-threeshift-25c-01",
            "control",
        )
        self.assertEqual(solver._cv_route_count(source), 0)
        bundle = (
            REPO / "models/data_bundle/generated_instances/"
            "L-main_size_preserving_v2_archive_20260710/"
            "L-main-threeshift-25c-01"
        )
        result = solver.apply_fuel_route_retirement_ev_repack(
            bundle,
            source,
            prices=PRICES_280,
        )

        self.assertFalse(result.changed)
        self.assertEqual(asdict(result.solution), asdict(source))
        self.assertEqual(
            result.activity["source_routes_considered"],
            0,
        )
        self.assertEqual(
            result.activity["repair_attempts"],
            0,
        )
        self.assertEqual(
            result.activity["candidate_completion_calls"],
            0,
        )
        self.assertEqual(
            result.activity["counterfactual_completion_calls"],
            0,
        )
        self.assertEqual(
            result.activity["complete_route_search_evaluations"],
            0,
        )

    def test_mock_strict_gain_accepts_and_retires_source(self) -> None:
        source = plateau_solution()
        bundle = load_search_bundle(PLATEAU_BUNDLE)
        instance = bundle.instance
        plans = tuple(
            solver.RoutePlan(
                index,
                route.home_depot_id,
                tuple(solver._customer_ids(route, instance)),
            )
            for index, route in enumerate(source.routes)
        )
        source_index = 2
        moved = plans[source_index].customers[0]
        changed_plans = list(plans)
        changed_plans[0] = replace(
            changed_plans[0],
            customers=(moved, *changed_plans[0].customers),
        )
        changed_plans[source_index] = replace(
            changed_plans[source_index],
            customers=changed_plans[source_index].customers[1:],
        )
        owners = infer_customer_home_depots(instance)
        context = EvaluationContext(
            instance,
            bundle.carbon_profile,
            prices=PRICES_280,
            budget=EvalBudget(limit=0, target=0),
            customer_home_depot=owners,
            allow_cross_depot=True,
        )
        neutral, mapping = solver._solution_from_plans(
            source,
            tuple(changed_plans),
            context,
        )
        completed = Solution(
            routes=[replace(route, vehicle_type="ev") for route in neutral.routes],
            charging_actions=list(neutral.charging_actions),
            cross_site_services=list(neutral.cross_site_services),
        )
        candidate = solver.RepackCandidate(
            source_original_index=source_index,
            seed_kind="direct",
            ejected_original_index=None,
            ejected_customer_id=None,
            plans=tuple(changed_plans),
            neutral_solution=neutral,
            plan_to_output=mapping,
            prescore=90.0,
            route_skeleton_sha256=solver._route_skeleton_hash(
                neutral,
                instance,
            ),
            repair_trace={"test": True},
        )

        def completion(
            incoming: Solution,
            _bundle: object,
            *,
            prices: object,
        ) -> FastCompletionResult:
            del prices
            returned = (
                source
                if solver._same_route_skeleton(
                    incoming,
                    source,
                    instance,
                )
                else completed
            )
            return FastCompletionResult(
                solution=returned,
                changed=returned is completed,
                activity=_empty_completion_activity(),
            )

        def cost(
            incoming: Solution,
            _context: object,
        ) -> float:
            return (
                100.0
                if solver._same_route_skeleton(
                    incoming,
                    source,
                    instance,
                )
                else 90.0
            )

        with (
            patch.object(
                solver,
                "_enumerate_repack_candidates",
                return_value=[candidate],
            ),
            patch.object(
                solver,
                "apply_fast_route_local_completion",
                side_effect=completion,
            ),
            patch.object(
                solver,
                "_model_cost",
                side_effect=cost,
            ),
            patch.object(
                solver,
                "_independent_model_cost",
                side_effect=cost,
            ),
            patch.object(
                solver,
                "check_solution",
                return_value=[],
            ),
        ):
            result = solver.apply_fuel_route_retirement_ev_repack(
                PLATEAU_BUNDLE,
                source,
                prices=PRICES_280,
            )

        self.assertTrue(result.changed)
        self.assertEqual(len(result.activity["accepted_moves"]), 1)
        self.assertEqual(result.cost, 90.0)
        self.assertEqual(result.activity["final_cv_route_count"], 0)
        self.assertTrue(result.activity["accepted_moves"][0]["source_route_retired"])
        self.assertEqual(
            result.activity["accepted_moves"][0]["independent_replay_error"],
            0.0,
        )

    def test_candidate_requires_cost_and_cv_gain_together(self) -> None:
        source = plateau_solution()
        bundle = load_search_bundle(PLATEAU_BUNDLE)
        instance = bundle.instance
        plans = tuple(
            solver.RoutePlan(
                index,
                route.home_depot_id,
                tuple(solver._customer_ids(route, instance)),
            )
            for index, route in enumerate(source.routes)
        )
        source_index = 2
        moved = plans[source_index].customers[0]
        changed_plans = list(plans)
        changed_plans[0] = replace(
            changed_plans[0],
            customers=(moved, *changed_plans[0].customers),
        )
        changed_plans[source_index] = replace(
            changed_plans[source_index],
            customers=changed_plans[source_index].customers[1:],
        )
        owners = infer_customer_home_depots(instance)
        context = EvaluationContext(
            instance,
            bundle.carbon_profile,
            prices=PRICES_280,
            budget=EvalBudget(limit=0, target=0),
            customer_home_depot=owners,
            allow_cross_depot=True,
        )
        neutral, mapping = solver._solution_from_plans(
            source,
            tuple(changed_plans),
            context,
        )
        all_ev = Solution(
            routes=[replace(route, vehicle_type="ev") for route in neutral.routes],
            charging_actions=list(neutral.charging_actions),
            cross_site_services=list(neutral.cross_site_services),
        )
        candidate = solver.RepackCandidate(
            source_original_index=source_index,
            seed_kind="direct",
            ejected_original_index=None,
            ejected_customer_id=None,
            plans=tuple(changed_plans),
            neutral_solution=neutral,
            plan_to_output=mapping,
            prescore=90.0,
            route_skeleton_sha256=solver._route_skeleton_hash(
                neutral,
                instance,
            ),
            repair_trace={"test": True},
        )

        for label, completed, candidate_cost in (
            ("cost_only", neutral, 90.0),
            ("cv_only_but_worse_cost", all_ev, 110.0),
            ("cv_only_but_cost_tie", all_ev, 100.0),
        ):
            with self.subTest(label=label):

                def completion(
                    incoming: Solution,
                    _bundle: object,
                    *,
                    prices: object,
                ) -> FastCompletionResult:
                    del prices
                    returned = (
                        source
                        if solver._same_route_skeleton(
                            incoming,
                            source,
                            instance,
                        )
                        else completed
                    )
                    return FastCompletionResult(
                        solution=returned,
                        changed=returned is completed,
                        activity=_empty_completion_activity(),
                    )

                def cost(
                    incoming: Solution,
                    _context: object,
                ) -> float:
                    return (
                        100.0
                        if solver._same_route_skeleton(
                            incoming,
                            source,
                            instance,
                        )
                        else candidate_cost
                    )

                with (
                    patch.object(
                        solver,
                        "_enumerate_repack_candidates",
                        return_value=[candidate],
                    ),
                    patch.object(
                        solver,
                        "apply_fast_route_local_completion",
                        side_effect=completion,
                    ),
                    patch.object(
                        solver,
                        "_model_cost",
                        side_effect=cost,
                    ),
                    patch.object(
                        solver,
                        "_independent_model_cost",
                        side_effect=cost,
                    ),
                    patch.object(
                        solver,
                        "check_solution",
                        return_value=[],
                    ),
                ):
                    result = solver.apply_fuel_route_retirement_ev_repack(
                        PLATEAU_BUNDLE,
                        source,
                        prices=PRICES_280,
                    )

                self.assertFalse(result.changed)
                self.assertEqual(
                    asdict(result.solution),
                    asdict(source),
                )
                self.assertFalse(result.activity["exact_candidates"][0]["eligible"])

    def test_completion_that_moves_customers_fails_closed(self) -> None:
        source = plateau_solution()
        bundle = load_search_bundle(PLATEAU_BUNDLE)
        instance = bundle.instance
        plans = tuple(
            solver.RoutePlan(
                index,
                route.home_depot_id,
                tuple(solver._customer_ids(route, instance)),
            )
            for index, route in enumerate(source.routes)
        )
        source_index = 2
        moved = plans[source_index].customers[0]
        changed_plans = list(plans)
        changed_plans[0] = replace(
            changed_plans[0],
            customers=(moved, *changed_plans[0].customers),
        )
        changed_plans[source_index] = replace(
            changed_plans[source_index],
            customers=changed_plans[source_index].customers[1:],
        )
        owners = infer_customer_home_depots(instance)
        context = EvaluationContext(
            instance,
            bundle.carbon_profile,
            prices=PRICES_280,
            budget=EvalBudget(limit=0, target=0),
            customer_home_depot=owners,
            allow_cross_depot=True,
        )
        neutral, mapping = solver._solution_from_plans(
            source,
            tuple(changed_plans),
            context,
        )
        candidate = solver.RepackCandidate(
            source_original_index=source_index,
            seed_kind="direct",
            ejected_original_index=None,
            ejected_customer_id=None,
            plans=tuple(changed_plans),
            neutral_solution=neutral,
            plan_to_output=mapping,
            prescore=90.0,
            route_skeleton_sha256=solver._route_skeleton_hash(
                neutral,
                instance,
            ),
            repair_trace={"test": True},
        )

        def completion(
            incoming: Solution,
            _bundle: object,
            *,
            prices: object,
        ) -> FastCompletionResult:
            del prices
            returned = source
            return FastCompletionResult(
                solution=returned,
                changed=False,
                activity=_empty_completion_activity(),
            )

        with (
            patch.object(
                solver,
                "_enumerate_repack_candidates",
                return_value=[candidate],
            ),
            patch.object(
                solver,
                "apply_fast_route_local_completion",
                side_effect=completion,
            ),
            patch.object(
                solver,
                "_model_cost",
                return_value=100.0,
            ),
            patch.object(
                solver,
                "_independent_model_cost",
                return_value=100.0,
            ),
            patch.object(
                solver,
                "check_solution",
                return_value=[],
            ),
        ):
            result = solver.apply_fuel_route_retirement_ev_repack(
                PLATEAU_BUNDLE,
                source,
                prices=PRICES_280,
            )

        self.assertFalse(result.changed)
        self.assertEqual(asdict(result.solution), asdict(source))
        self.assertFalse(
            result.activity["exact_candidates"][0]["fixed_skeleton_preserved"]
        )

    def test_frozen_config_and_zero_ablation_entry(self) -> None:
        source = _saved_final(
            "L-main-threeshift-25c-01",
            "control",
        )
        bundle = (
            REPO / "models/data_bundle/generated_instances/"
            "L-main_size_preserving_v2_archive_20260710/"
            "L-main-threeshift-25c-01"
        )
        with self.assertRaises(ValueError):
            solver.apply_fuel_route_retirement_ev_repack(
                bundle,
                source,
                prices=PRICES_280,
                config=solver.FuelRouteRetirementConfig(
                    exact_candidate_capacity=3,
                ),
            )
        ablation = solver.apply_fuel_route_retirement_without_ejection(
            PLATEAU_BUNDLE,
            plateau_solution(),
            prices=PRICES_280,
        )
        self.assertGreater(
            ablation.activity["source_routes_considered"],
            0,
        )
        self.assertGreater(ablation.activity["repair_attempts"], 0)
        self.assertEqual(
            ablation.activity["repair_attempts"],
            ablation.activity["source_routes_considered"],
        )
        self.assertEqual(
            ablation.activity["effective_ejection_seed_limit"],
            0,
        )
        self.assertEqual(
            ablation.activity["one_level_ejection_attempts"],
            0,
        )
        self.assertEqual(
            ablation.activity["ejection_seed_scoring_attempts"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
