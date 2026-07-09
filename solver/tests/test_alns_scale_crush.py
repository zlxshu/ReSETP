from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from setp_solver.search.alns_crush import ALNS_DEFAULT_INSTANCE_ORDER
from setp_solver.search.alns_crush_v2 import V2_INSTANCE_DIRS
from setp_solver.search.alns_scale_crush import (
    capacity_route_lower_bound,
    first_fit_decreasing_bin_count,
    kept_count_by_shift,
    scale_verdict_row,
)


def _load_scale_builder():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "models/scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "build_scale_three_shift_instances",
        scripts_dir / "build_scale_three_shift_instances.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scale builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AlnsScaleCrushTests(unittest.TestCase):
    def test_scale_config_disables_dynamic_events(self) -> None:
        builder = _load_scale_builder()
        child = builder.ScaleChildSpec("E-UK100_01", 1, 0.0, 10, "Scale-Test")

        config = builder._config(child, cluster_std_ratio=0.12)

        self.assertFalse(config.dynamic_event_config.enabled)

    def test_target_hit_search_uses_premerge_counts_not_posthoc_deletion(self) -> None:
        builder = _load_scale_builder()

        plan = builder.choose_child_counts(150, lambda n3: n3 // 5, max_child_n=100, preferred_child_n=66)

        n1, n2, n3 = plan.n_customers_by_child
        self.assertTrue(plan.exact_hit)
        self.assertEqual(n1 + n2 + n3 // 5, 150)
        self.assertFalse(hasattr(plan, "posthoc_deleted_customer_count"))

    def test_kept_customer_manifest_counts_by_shift(self) -> None:
        manifest = {
            "kept_customers": [
                {"new_node_id": "C001", "shift_seconds": 0.0},
                {"new_node_id": "C002", "shift_seconds": 0.0},
                {"new_node_id": "C101", "shift_seconds": 32400.0},
                {"new_node_id": "C201", "shift_seconds": 64800.0},
            ]
        }

        self.assertEqual(kept_count_by_shift(manifest), {"0": 2, "1": 1, "2": 1})

    def test_capacity_and_ffd_diagnostics(self) -> None:
        self.assertEqual(capacity_route_lower_bound([600.0, 700.0, 701.0], 1000.0), 3)

        ffd = first_fit_decreasing_bin_count([800.0, 700.0, 600.0, 300.0, 200.0], 1000.0)

        self.assertEqual(ffd["bin_count"], 3)
        self.assertAlmostEqual(ffd["total_demand"], 2600.0)
        self.assertAlmostEqual(ffd["total_slack"], 400.0)

    def test_paired_verdict_requires_all_crush_gates(self) -> None:
        fair_reference = {
            "instances": {
                "Scale-X": {
                    "scikit-opt-SA": {
                        "mean_total_cost": 100.0,
                        "best_total_cost": 90.0,
                        "std_total_cost": 10.0,
                    }
                }
            }
        }
        summary = {
            "variant": "winner_kernel_only",
            "instance": "Scale-X",
            "algorithm": "ALNS-Wouda",
            "mean_total_cost": 98.9,
            "best_total_cost": 88.0,
            "std_total_cost": 12.4,
        }
        wilcoxon = [
            {
                "variant": "winner_kernel_only",
                "instance": "Scale-X",
                "algorithm": "ALNS-Wouda",
                "wins_alg_lower": 8,
                "n_pairs": 10,
                "p_value_less": 0.049,
                "p_value_greater": 0.99,
            }
        ]

        verdict = scale_verdict_row(summary, fair_reference, wilcoxon)
        self.assertEqual(verdict["verdict"], "碾压")

        summary["mean_total_cost"] = 99.2
        verdict = scale_verdict_row(summary, fair_reference, wilcoxon)
        self.assertEqual(verdict["verdict"], "持平")

        summary["mean_total_cost"] = 101.2
        wilcoxon[0]["wins_alg_lower"] = 3
        wilcoxon[0]["p_value_less"] = 0.96
        wilcoxon[0]["p_value_greater"] = 0.04
        verdict = scale_verdict_row(summary, fair_reference, wilcoxon)
        self.assertEqual(verdict["verdict"], "失败")

    def test_v2_default_instances_do_not_expand_when_scale_registered(self) -> None:
        self.assertEqual(tuple(V2_INSTANCE_DIRS), ALNS_DEFAULT_INSTANCE_ORDER)
        self.assertEqual(len(V2_INSTANCE_DIRS), 23)


if __name__ == "__main__":
    unittest.main()
