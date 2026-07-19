"""Zero-search tests for the electrification relocate-resize operator."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import electrification_relocate_resize_solver as solver  # noqa: E402
import run_electrification_relocate_resize_behavior_gate as gate  # noqa: E402
from contextual_expert_fixtures import (  # noqa: E402
    PLATEAU_BUNDLE,
    PRICES_280,
    plateau_solution,
)
from prototype import independent_cost  # noqa: E402
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)
from terminal_completion import CompletionResult  # noqa: E402


SAVED_WITNESSES = (
    HERE
    / "contextual_expert_p1_training_gate/solution_witnesses.json"
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
            solution = row["solution"]
            return Solution(
                routes=[
                    Route(
                        str(route["vehicle_id"]),
                        str(route["vehicle_type"]),
                        str(route["home_depot_id"]),
                        [str(node) for node in route["node_sequence"]],
                    )
                    for route in solution.get("routes", [])
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
                    for action in solution.get("charging_actions", [])
                ],
                cross_site_services=[
                    CrossSiteService(
                        str(item["customer_id"]),
                        str(item["served_by_depot_id"]),
                    )
                    for item in solution.get("cross_site_services", [])
                ],
            )
    raise AssertionError(f"missing saved final: {instance}/{arm}")


class ElectrificationRelocateResizeSolverTest(unittest.TestCase):
    def test_candidates_exist_but_no_dual_gain_is_exact_noop(self) -> None:
        source = plateau_solution()
        bundle = load_search_bundle(PLATEAU_BUNDLE)

        def no_gain_completion(
            bundle_dir: str | Path,
            candidate: Solution,
            *,
            prices: object,
        ) -> CompletionResult:
            cost = independent_cost(bundle_dir, candidate, prices)
            violations = check_solution(
                candidate,
                bundle.instance,
                prices,
            )
            return CompletionResult(
                solution=candidate,
                cost=float(cost),
                source_cost=float(cost),
                feasible=not violations,
                selected_branch="test_no_gain",
                activity={
                    "full_solution_replays": 1,
                    "route_local_exact_evaluations": 0,
                    "route_proxy_evaluations": 0,
                    "route_local_schedule_evaluations": 0,
                    "full_feasibility_checks": 1,
                    "complete_route_search_evaluations": 0,
                },
            )

        with patch.object(
            solver,
            "apply_terminal_completion",
            side_effect=no_gain_completion,
        ):
            result = solver.apply_electrification_relocate_resize(
                PLATEAU_BUNDLE,
                source,
                prices=PRICES_280,
            )

        self.assertGreater(result.activity["enumerated_moves"], 0)
        self.assertGreater(result.activity["prescored_moves"], 0)
        self.assertLessEqual(
            result.activity["prescore_selected_moves"],
            12,
        )
        self.assertEqual(
            result.activity["terminal_completion_calls"],
            3,
        )
        self.assertEqual(
            result.activity["counterfactual_terminal_completion_calls"],
            1,
        )
        self.assertFalse(result.changed)
        self.assertEqual(asdict(result.solution), asdict(source))
        self.assertTrue(
            gate._audit_activity_ledgers(result.activity)["passed"]
        )

    def test_saved_all_ev_v7_solution_is_exact_noop(self) -> None:
        source = _saved_final(
            "L-main-threeshift-25c-01",
            "control",
        )
        self.assertFalse(
            any(route.vehicle_type.lower() == "cv" for route in source.routes)
        )
        bundle = (
            REPO
            / "models/data_bundle/generated_instances/"
            "L-main_size_preserving_v2_archive_20260710/"
            "L-main-threeshift-25c-01"
        )
        result = solver.apply_electrification_relocate_resize(
            bundle,
            source,
            prices=PRICES_280,
        )

        self.assertFalse(result.changed)
        self.assertEqual(result.activity["enumerated_moves"], 0)
        self.assertEqual(
            result.activity["terminal_completion_calls"],
            0,
        )
        self.assertEqual(
            result.activity["counterfactual_terminal_completion_calls"],
            0,
        )
        self.assertEqual(asdict(result.solution), asdict(source))
        self.assertAlmostEqual(result.cost, result.source_cost, places=12)

    def test_hashes_separate_order_from_semantics(self) -> None:
        source = plateau_solution()
        reordered = Solution(
            routes=list(reversed(source.routes)),
            charging_actions=list(reversed(source.charging_actions)),
            cross_site_services=list(reversed(source.cross_site_services)),
        )
        self.assertNotEqual(
            solver._full_content_hash(source),
            solver._full_content_hash(reordered),
        )
        self.assertEqual(
            solver._semantic_hash(source),
            solver._semantic_hash(reordered),
        )
        self.assertEqual(
            solver._full_content_hash(source),
            gate._runner_full_content_hash(source),
        )
        self.assertEqual(
            solver._semantic_hash(source),
            gate._runner_semantic_hash(source),
        )

    def test_declared_transfer_and_completion_proofs(self) -> None:
        before = plateau_solution()
        instance = load_search_bundle(PLATEAU_BUNDLE).instance
        source_index = next(
            index
            for index, route in enumerate(before.routes)
            if route.vehicle_type.lower() == "cv"
            and len(solver._customer_ids(route, instance)) >= 2
        )
        target_index = next(
            index
            for index in range(len(before.routes))
            if index != source_index
        )
        source_customers = solver._customer_ids(
            before.routes[source_index],
            instance,
        )
        target_customers = solver._customer_ids(
            before.routes[target_index],
            instance,
        )
        segment = (source_customers[0],)
        reduced = source_customers[1:]
        expanded = [*segment, *target_customers]
        routes = list(before.routes)
        routes[source_index] = replace(
            routes[source_index],
            vehicle_type="cv",
            node_sequence=[
                routes[source_index].home_depot_id,
                *reduced,
                routes[source_index].home_depot_id,
            ],
        )
        routes[target_index] = replace(
            routes[target_index],
            vehicle_type="cv",
            node_sequence=[
                routes[target_index].home_depot_id,
                *expanded,
                routes[target_index].home_depot_id,
            ],
        )
        neutral = Solution(
            routes=routes,
            charging_actions=[],
            cross_site_services=list(before.cross_site_services),
        )
        self.assertTrue(
            solver._declared_transfer_holds(
                before,
                neutral,
                instance,
                source_index,
                target_index,
                0,
                segment,
                0,
            )
        )
        self.assertTrue(
            gate._runner_declared_transfer_holds(
                before,
                neutral,
                instance,
                source_index,
                target_index,
                0,
                segment,
                0,
            )
        )
        self.assertTrue(
            solver._completed_transfer_holds(
                neutral,
                instance,
                source_index,
                target_index,
                segment,
            )
        )
        self.assertTrue(
            gate._runner_completed_transfer_holds(
                neutral,
                instance,
                source_index,
                target_index,
                segment,
            )
        )
        undone_routes = list(neutral.routes)
        undone_routes[target_index] = replace(
            undone_routes[target_index],
            node_sequence=[
                undone_routes[target_index].home_depot_id,
                *target_customers,
                undone_routes[target_index].home_depot_id,
            ],
        )
        undone = Solution(
            routes=undone_routes,
            charging_actions=[],
            cross_site_services=list(neutral.cross_site_services),
        )
        self.assertFalse(
            solver._completed_transfer_holds(
                undone,
                instance,
                source_index,
                target_index,
                segment,
            )
        )
        self.assertFalse(
            gate._runner_completed_transfer_holds(
                undone,
                instance,
                source_index,
                target_index,
                segment,
            )
        )

    def test_witness_recorder_duplicate_reorder_and_microfloat(self) -> None:
        with self.assertRaises(ValueError):
            json.loads(
                '{"duplicate": 1, "duplicate": 2}',
                object_pairs_hook=gate._reject_duplicate_json_keys,
            )
        raw = plateau_solution()
        source = Solution(
            routes=list(raw.routes),
            charging_actions=[
                *raw.charging_actions,
                ChargingAction(
                    "__hash_vehicle__",
                    "__hash_station__",
                    1.0,
                    2.0,
                    3.0,
                    0,
                ),
            ],
            cross_site_services=list(raw.cross_site_services),
        )
        witnesses: dict[str, object] = {}
        gate._add_witness(witnesses, source, {"kind": "first"})
        gate._add_witness(witnesses, source, {"kind": "duplicate"})
        self.assertEqual(len(witnesses), 1)
        only = next(iter(witnesses.values()))
        self.assertEqual(len(only["uses"]), 2)

        reordered = Solution(
            routes=list(reversed(source.routes)),
            charging_actions=list(reversed(source.charging_actions)),
            cross_site_services=list(reversed(source.cross_site_services)),
        )
        gate._add_witness(witnesses, reordered, {"kind": "reordered"})
        self.assertEqual(len(witnesses), 2)
        self.assertEqual(
            solver._semantic_hash(source),
            solver._semantic_hash(reordered),
        )

        changed_actions = list(source.charging_actions)
        changed_actions[-1] = replace(
            changed_actions[-1],
            energy_kwh=changed_actions[-1].energy_kwh + 1.0e-12,
        )
        microchanged = Solution(
            routes=list(source.routes),
            charging_actions=changed_actions,
            cross_site_services=list(source.cross_site_services),
        )
        gate._add_witness(
            witnesses,
            microchanged,
            {"kind": "microchange"},
        )
        self.assertEqual(len(witnesses), 3)
        self.assertNotEqual(
            solver._full_content_hash(source),
            solver._full_content_hash(microchanged),
        )

    def test_frozen_caps_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            solver.apply_electrification_relocate_resize(
                PLATEAU_BUNDLE,
                plateau_solution(),
                prices=PRICES_280,
                config=solver.ElectrificationRelocateResizeConfig(
                    exact_capacity=2,
                ),
            )

    def test_route_search_guard_blocks_entrypoint(self) -> None:
        with gate._forbid_route_search() as state:
            with self.assertRaises(RuntimeError):
                gate.prototype_module.run_pure_alns(
                    PLATEAU_BUNDLE,
                    seed=1,
                    eval_budget=1,
                    prices=PRICES_280,
                )
        self.assertTrue(state["installed"])
        self.assertEqual(len(state["attempts"]), 1)
        self.assertTrue(
            state["attempts"][0].endswith(".run_pure_alns")
        )


if __name__ == "__main__":
    unittest.main()
