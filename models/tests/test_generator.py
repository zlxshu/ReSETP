from __future__ import annotations

import json
from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

import numpy as np

from setp_instance_lab import DynamicEventConfig, ScenarioConfig, generate_scenario, write_scenario_bundle
from setp_instance_lab.catalog import migrate_goeke_instances, resolve_goeke_instance
from setp_instance_lab.evrptwmf import parse_evrptwmf


class ScenarioGeneratorTests(unittest.TestCase):
    def test_fixed_seed_synthetic_bundle(self) -> None:
        config = ScenarioConfig(
            n_depots=2,
            n_stations=3,
            n_customers=25,
            seed=7,
            dynamic_event_config=DynamicEventConfig(enabled=True, n_events=12, event_ratio=(0, 2, 1, 1)),
        )
        scenario = generate_scenario(config)
        self.assertTrue(scenario.validation["passed"], scenario.validation)
        self.assertEqual(scenario.validation["depot_count"], 2)
        self.assertEqual(scenario.validation["station_count"], 3)
        self.assertEqual(scenario.validation["customer_count"], 25)
        customer_due_max = max(node.due_time for node in scenario.nodes if node.node_type == "c")
        station_due_max = max(node.due_time for node in scenario.nodes if node.node_type == "f")
        depot_due_max = max(node.due_time for node in scenario.nodes if node.node_type == "d")
        self.assertLessEqual(customer_due_max, 32400.0)
        self.assertLessEqual(station_due_max, 32400.0)
        self.assertLessEqual(depot_due_max, 32400.0)
        self.assertEqual(scenario.distance_matrix.shape, (30, 30))
        self.assertEqual(len(scenario.dynamic_events), 12)
        self.assertEqual([event.t_appear for event in scenario.dynamic_events], sorted(event.t_appear for event in scenario.dynamic_events))
        self.assertTrue(all(config.horizon_start <= event.t_appear <= config.horizon_end for event in scenario.dynamic_events))

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_scenario_bundle(scenario, tmp, config=config.to_dict())
            for path in paths.values():
                self.assertTrue(Path(path).is_file(), path)
            manifest = json.loads(Path(paths["scenario_manifest_json"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["seed"], 7)
            self.assertIn("distance_matrix_npy", manifest["hashes"])
            matrix = np.load(paths["distance_matrix_npy"])
            self.assertEqual(matrix.shape, (30, 30))

    def test_station_node_overlap_avoidance_on_by_default(self) -> None:
        config = ScenarioConfig(
            n_depots=2,
            n_stations=3,
            n_customers=25,
            seed=7,
            min_customer_distance=10,
        )
        scenario = generate_scenario(config)
        depots = [(node.x, node.y) for node in scenario.nodes if node.node_type == "d"]
        customers = [(node.x, node.y) for node in scenario.nodes if node.node_type == "c"]
        stations = [(node.x, node.y) for node in scenario.nodes if node.node_type == "f"]
        anchor_nodes = depots + customers
        self.assertTrue(anchor_nodes)
        for sx, sy in stations:
            min_dist = min((sx - nx) ** 2 + (sy - ny) ** 2 for nx, ny in anchor_nodes) ** 0.5
            self.assertGreaterEqual(min_dist, config.station_min_node_distance)

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_scenario_bundle(scenario, tmp, config=config.to_dict(), export_dynamic=False)
            manifest = json.loads(Path(paths["scenario_manifest_json"]).read_text(encoding="utf-8"))
            instance = json.loads(Path(paths["instance_json"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["metadata"]["station_avoid_node_overlap"], True)
            self.assertEqual(manifest["metadata"]["station_min_node_distance"], config.station_min_node_distance)
            self.assertEqual(instance["metadata"]["station_avoid_node_overlap"], True)
            self.assertEqual(instance["metadata"]["station_min_node_distance"], config.station_min_node_distance)

    def test_fleet_counts_are_reproducible_metadata(self) -> None:
        # v2026-06-12: M0 EV-heavy variants must carry explicit m^g/m^e counts for solver search gates.
        config = ScenarioConfig(
            n_depots=1,
            n_stations=1,
            n_customers=4,
            seed=11,
            num_cv=3,
            num_ev=8,
            min_customer_distance=10,
        )
        scenario = generate_scenario(config)
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_scenario_bundle(scenario, tmp, config=config.to_dict(), export_dynamic=False)
            manifest = json.loads(Path(paths["scenario_manifest_json"]).read_text(encoding="utf-8"))
            instance = json.loads(Path(paths["instance_json"]).read_text(encoding="utf-8"))
            text = Path(paths["evrptwmf_txt"]).read_text(encoding="utf-8")

        self.assertEqual(manifest["config"]["num_cv"], 3)
        self.assertEqual(manifest["config"]["num_ev"], 8)
        self.assertEqual(manifest["metadata"]["num_cv"], 3)
        self.assertEqual(manifest["metadata"]["num_ev"], 8)
        self.assertEqual(manifest["metadata"]["public_station_chargers"], 1)
        self.assertEqual(manifest["metadata"]["depot_chargers_policy"], "customer_count_route_upper_bound")
        self.assertEqual(manifest["metadata"]["depot_chargers"], 4)
        self.assertEqual(instance["metadata"]["num_cv"], 3)
        self.assertEqual(instance["metadata"]["num_ev"], 8)
        depot_rows = [node for node in instance["nodes"] if node["node_type"] == "d"]
        station_rows = [node for node in instance["nodes"] if node["node_type"] == "f"]
        self.assertEqual({node["station_chargers"] for node in depot_rows}, {4})
        self.assertEqual({node["station_chargers"] for node in station_rows}, {1})
        self.assertIn("m numPetrolVeh /3/", text)
        self.assertIn("m numElectroVeh /8/", text)

    def test_station_node_overlap_avoidance_can_be_disabled(self) -> None:
        base_config = ScenarioConfig(
            n_depots=2,
            n_stations=1,
            n_customers=4,
            seed=9,
            station_min_node_distance=250000.0,
            station_avoid_node_overlap=True,
            min_customer_distance=10,
        )
        with self.assertRaisesRegex(ValueError, "No feasible station candidates"):
            generate_scenario(base_config)

        no_filter = replace(
            base_config,
            station_avoid_node_overlap=False,
        )
        scenario = generate_scenario(no_filter)
        depots = [(node.x, node.y) for node in scenario.nodes if node.node_type == "d"]
        customers = [(node.x, node.y) for node in scenario.nodes if node.node_type == "c"]
        stations = [(node.x, node.y) for node in scenario.nodes if node.node_type == "f"]
        anchor_nodes = depots + customers
        self.assertTrue(stations)
        min_station_to_node = min(
            (sx - nx) ** 2 + (sy - ny) ** 2 for sx, sy in stations for nx, ny in anchor_nodes
        ) ** 0.5
        self.assertLess(min_station_to_node, no_filter.station_min_node_distance)

    def test_customer_demands_are_capped(self) -> None:
        config = ScenarioConfig(n_customers=40, vehicle_capacity=1000, max_customer_demand_ratio=0.5, demand_mode="lognormal")
        scenario = generate_scenario(config)
        customer_demands = [node.demand for node in scenario.nodes if node.node_type == "c"]
        self.assertLessEqual(max(customer_demands), 500)

    def test_evrptwmf_parser_and_empirical_generation(self) -> None:
        sample = """StringID  Type  x y demand ReadyTime DueDate ServiceTime
D0 d 0 0 0 0 10000 0
C1 c 1000 0 100 0 5000 100
C2 c 2000 0 200 500 6500 120
F1 f 1500 500 0 0 10000 0

DistanceMatrix
0 1000 2000 1581
1000 0 1000 707
2000 1000 0 707
1581 707 707 0
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "E-TEST_01.txt"
            path.write_text(sample, encoding="utf-8")
            nodes, matrix = parse_evrptwmf(path)
            self.assertEqual(len(nodes), 4)
            self.assertEqual(matrix.shape, (4, 4))
            config = ScenarioConfig(
                n_depots=1,
                n_stations=1,
                n_customers=6,
                coord_mode="empirical",
                demand_mode="empirical",
                time_window_mode="empirical",
                base_instance_path=str(path),
                min_customer_distance=10,
            )
            scenario = generate_scenario(config)
            self.assertTrue(scenario.validation["passed"], scenario.validation)

    def test_five_demand_and_time_window_modes(self) -> None:
        demand_modes = ["empirical", "uniform", "truncnorm", "gamma", "lognormal"]
        time_window_modes = ["empirical", "uniform", "clustered", "tight", "mixed"]
        sample = """StringID  Type  x y demand ReadyTime DueDate ServiceTime
D0 d 0 0 0 0 28800 0
C1 c 1000 0 100 0 7200 100
C2 c 2000 0 200 3600 14400 120
C3 c 3000 0 300 7200 21600 120
F1 f 1500 500 0 0 28800 0

DistanceMatrix
0 1000 2000 3000 1581
1000 0 1000 2000 707
2000 1000 0 1000 707
3000 2000 1000 0 1581
1581 707 707 1581 0
"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "E-UK3_01.txt"
            base.write_text(sample, encoding="utf-8")
            for demand_mode in demand_modes:
                for tw_mode in time_window_modes:
                    config = ScenarioConfig(
                        n_depots=1,
                        n_stations=1,
                        n_customers=3,
                        coord_mode="empirical",
                        demand_mode=demand_mode,
                        time_window_mode=tw_mode,
                        base_instance_path=str(base),
                        min_customer_distance=10,
                    )
                    scenario = generate_scenario(config)
                    self.assertEqual(scenario.validation["customer_count"], 3)
                    self.assertEqual(scenario.distance_matrix.shape, (5, 5))

    def test_add_events_use_real_goeke_donor_customers(self) -> None:
        base_sample = """StringID  Type  x y demand ReadyTime DueDate ServiceTime
D0 d 0 0 0 0 28800 0
C1 c 1000 0 100 0 7200 100
C2 c 2000 0 200 3600 14400 120
F1 f 1500 500 0 0 28800 0

DistanceMatrix
0 1000 2000 1581
1000 0 1000 707
2000 1000 0 707
1581 707 707 0
"""
        donor_sample = """StringID  Type  x y demand ReadyTime DueDate ServiceTime
D0 d 0 0 0 0 28800 0
C9 c 9000 9000 300 7200 14400 100
C10 c 9500 9200 400 7200 18000 120
F1 f 8500 8500 0 0 28800 0

DistanceMatrix
0 12728 13224 12021
12728 0 539 707
13224 539 0 1140
12021 707 1140 0
"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "E-UK2_01.txt"
            donor = Path(tmp) / "E-UK2_02.txt"
            base.write_text(base_sample, encoding="utf-8")
            donor.write_text(donor_sample, encoding="utf-8")
            config = ScenarioConfig(
                n_depots=1,
                n_stations=1,
                n_customers=4,
                coord_mode="empirical",
                demand_mode="empirical",
                time_window_mode="empirical",
                base_instance_path=str(base),
                add_event_source_paths=(str(donor),),
                min_customer_distance=10,
                dynamic_event_config=DynamicEventConfig(enabled=True, n_events=3, event_ratio=(3, 0, 0, 0)),
            )
            scenario = generate_scenario(config)
            self.assertEqual(len(scenario.dynamic_events), 3)
            for event in scenario.dynamic_events:
                self.assertEqual(event.source, "goeke_donor_overlay")
                self.assertEqual(event.donor_instance_id, "E-UK2_02")
                self.assertIn(event.donor_customer_id, {"C9", "C10"})
                self.assertIn((event.x, event.y), {(9000.0, 9000.0), (9500.0, 9200.0)})
                self.assertEqual(event.demand_source, "donor_inherited")
                self.assertEqual(event.time_window_source, "donor_inherited")

    def test_add_events_keep_donor_coordinate_but_regenerate_bad_attributes(self) -> None:
        base_sample = """StringID  Type  x y demand ReadyTime DueDate ServiceTime
D0 d 0 0 0 0 28800 0
C1 c 1000 0 100 0 7200 100
C2 c 2000 0 200 3600 14400 120
F1 f 1500 500 0 0 28800 0

DistanceMatrix
0 1000 2000 1581
1000 0 1000 707
2000 1000 0 707
1581 707 707 0
"""
        donor_sample = """StringID  Type  x y demand ReadyTime DueDate ServiceTime
D0 d 0 0 0 0 28800 0
C99 c 9000 9000 9999 100 200 100
F1 f 8500 8500 0 0 28800 0

DistanceMatrix
0 12728 12021
12728 0 707
12021 707 0
"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "E-UK2_01.txt"
            donor = Path(tmp) / "E-UK2_99.txt"
            base.write_text(base_sample, encoding="utf-8")
            donor.write_text(donor_sample, encoding="utf-8")
            config = ScenarioConfig(
                n_depots=1,
                n_stations=1,
                n_customers=2,
                coord_mode="empirical",
                demand_mode="empirical",
                time_window_mode="empirical",
                base_instance_path=str(base),
                add_event_source_paths=(str(donor),),
                min_customer_distance=10,
                dynamic_event_config=DynamicEventConfig(enabled=True, n_events=1, event_ratio=(1, 0, 0, 0)),
            )
            scenario = generate_scenario(config)
            event = scenario.dynamic_events[0]
            self.assertEqual((event.x, event.y), (9000.0, 9000.0))
            self.assertEqual(event.donor_instance_id, "E-UK2_99")
            self.assertEqual(event.donor_customer_id, "C99")
            self.assertEqual(event.demand_source, "generated_from_current_instance")
            self.assertEqual(event.time_window_source, "generated_from_current_instance")
            self.assertLessEqual(event.new_demand, config.vehicle_capacity * config.max_customer_demand_ratio)
            self.assertGreaterEqual(event.new_due_time - event.new_ready_time, config.time_window_min_width)

    def test_add_events_require_donor_pool(self) -> None:
        config = ScenarioConfig(dynamic_event_config=DynamicEventConfig(enabled=True, n_events=1, event_ratio=(1, 0, 0, 0)))
        with self.assertRaisesRegex(ValueError, "require add_event_source_paths"):
            generate_scenario(config)

    def test_migrate_goeke_catalog_and_generate_from_base_id(self) -> None:
        sample = """StringID  Type  x y demand ReadyTime DueDate ServiceTime
D0 d 0 0 0 0 10000 0
C1 c 1000 0 100 0 5000 100
C2 c 2000 0 200 500 6500 120
F1 f 1500 500 0 0 10000 0

DistanceMatrix
0 1000 2000 1581
1000 0 1000 707
2000 1000 0 707
1581 707 707 0
"""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source"
            root = Path(tmp) / "bundle"
            src.mkdir()
            (src / "E-UK2_01.txt").write_text(sample, encoding="utf-8")
            catalog = migrate_goeke_instances(src, root)
            self.assertEqual(catalog["entry_count"], 1)
            base_path = resolve_goeke_instance(root, "E-UK2_01")
            self.assertTrue(base_path.is_file())
            config = ScenarioConfig(
                n_depots=1,
                n_stations=1,
                n_customers=4,
                coord_mode="empirical",
                demand_mode="empirical",
                time_window_mode="empirical",
                base_instance_path=str(base_path),
                min_customer_distance=10,
            )
            scenario = generate_scenario(config)
            self.assertTrue(scenario.validation["passed"], scenario.validation)


if __name__ == "__main__":
    unittest.main()
