from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from setp_solver.algorithms.resetp_alns.kernel.alns_core import (
    AlnsState,
    SearchPolicy,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    WinnerOperatorSet,
    _run_winner_kernel_loop,
    e2_alns_variant_flags,
)
from setp_solver.algorithms.resetp_alns.operators.sisr_string_removal import (
    _random_substring_start_including,
    sisr_string_removal,
)
from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.solution import Route, Solution


@dataclass(frozen=True)
class _ToyInstance:
    nodes: tuple[SimpleNamespace, ...]

    def distance(self, left: str, right: str) -> float:
        def coordinate(node_id: str) -> int:
            return 0 if node_id == "D0" else int(node_id[1:])

        return float(abs(coordinate(left) - coordinate(right)))


def _toy_state() -> AlnsState:
    nodes = (
        SimpleNamespace(node_id="D0", node_type="d"),
        *(
            SimpleNamespace(node_id=f"C{index}", node_type="c")
            for index in range(1, 13)
        ),
    )
    instance = _ToyInstance(nodes=nodes)
    solution = Solution(
        routes=[
            Route("CV1", "cv", "D0", ["D0", "C1", "C2", "C3", "C4", "D0"]),
            Route("CV2", "cv", "D0", ["D0", "C5", "C6", "C7", "C8", "D0"]),
            Route("CV3", "cv", "D0", ["D0", "C9", "C10", "C11", "C12", "D0"]),
        ]
    )
    context = EvaluationContext(instance, [])
    return AlnsState(
        solution,
        context,
        objective_value=0.0,
        policy=SearchPolicy(max_cv=3, max_ev=0),
    )


def _solution_signature(solution: Solution) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(route.node_sequence) for route in solution.routes)


class SisrStringRemovalTests(unittest.TestCase):
    def test_substring_start_always_contains_required_index(self) -> None:
        for seed in range(20):
            start = _random_substring_start_including(
                full_length=8,
                substring_length=3,
                required_index=4,
                rng=np.random.default_rng(seed),
            )
            self.assertLessEqual(start, 4)
            self.assertGreater(start + 3, 4)

    def test_same_seed_is_deterministic_and_removes_each_customer_once(self) -> None:
        first = sisr_string_removal(_toy_state(), np.random.default_rng(17))
        second = sisr_string_removal(_toy_state(), np.random.default_rng(17))

        self.assertEqual(first.removed_customers, second.removed_customers)
        self.assertEqual(
            _solution_signature(first.solution),
            _solution_signature(second.solution),
        )
        self.assertTrue(first.removed_customers)
        self.assertEqual(
            len(first.removed_customers),
            len(set(first.removed_customers)),
        )
        self.assertTrue(
            set(first.removed_customers)
            <= {f"C{index}" for index in range(1, 13)}
        )

    def test_each_affected_route_has_at_most_two_removed_blocks(self) -> None:
        original_routes = [
            ["C1", "C2", "C3", "C4"],
            ["C5", "C6", "C7", "C8"],
            ["C9", "C10", "C11", "C12"],
        ]
        for seed in range(40):
            result = sisr_string_removal(
                _toy_state(),
                np.random.default_rng(seed),
            )
            removed = set(result.removed_customers)
            for route in original_routes:
                mask = [customer in removed for customer in route]
                block_count = sum(
                    selected and (index == 0 or not mask[index - 1])
                    for index, selected in enumerate(mask)
                )
                self.assertLessEqual(block_count, 2)

    def test_operator_is_opt_in_and_adds_exactly_one_destroy_operator(self) -> None:
        baseline = WinnerOperatorSet.create(allow_cross_depot=False)
        candidate = WinnerOperatorSet.create(
            allow_cross_depot=False,
            include_sisr_string_removal=True,
        )
        baseline_names = [name for name, _ in baseline.destroy_ops]
        candidate_names = [name for name, _ in candidate.destroy_ops]

        self.assertNotIn("sisr_string_removal", baseline_names)
        self.assertEqual(candidate_names.count("sisr_string_removal"), 1)
        candidate_names.remove("sisr_string_removal")
        self.assertEqual(candidate_names, baseline_names)

    def test_zero_and_tiny_budgets_close_without_target_plus_one(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        bundle = load_search_bundle(
            repo
            / "models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-10c-01"
        )
        initial = build_initial_solution(
            bundle.instance,
            bundle.carbon_profile,
        )
        signatures: dict[int, tuple[float, tuple[tuple[str, ...], ...]]] = {}
        for target in (0, 1, 2, 5):
            run = _run_winner_kernel_loop(
                initial,
                bundle.instance,
                bundle.carbon_profile,
                config=WinnerKernelConfig(
                    seed=19,
                    eval_budget=target,
                    max_runtime_seconds=120.0,
                    include_sisr_string_removal=True,
                ),
                variant_flags=e2_alns_variant_flags(),
            )
            self.assertEqual(run.evaluations, target)
            self.assertEqual(run.candidate_scores, target)
            self.assertTrue(run.feasible)
            signatures[target] = (
                run.best_obj,
                _solution_signature(run.best_solution),
            )

        replay = _run_winner_kernel_loop(
            initial,
            bundle.instance,
            bundle.carbon_profile,
            config=WinnerKernelConfig(
                seed=19,
                eval_budget=2,
                max_runtime_seconds=120.0,
                include_sisr_string_removal=True,
            ),
            variant_flags=e2_alns_variant_flags(),
        )
        self.assertEqual(
            (replay.best_obj, _solution_signature(replay.best_solution)),
            signatures[2],
        )


if __name__ == "__main__":
    unittest.main()
