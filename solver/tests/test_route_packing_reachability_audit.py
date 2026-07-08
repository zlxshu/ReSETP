from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class RoutePackingReachabilityAuditTests(unittest.TestCase):
    def test_solution_from_json_round_trips_routes_and_actions(self) -> None:
        from baselines.e2_alns import route_packing_reachability_audit as audit

        payload = {
            "routes": [
                {
                    "vehicle_id": "CV1#T1",
                    "vehicle_type": "cv",
                    "home_depot_id": "D0",
                    "node_sequence": ["D0", "C1", "D0"],
                }
            ],
            "charging_actions": [
                {
                    "vehicle_id": "EV1#T1",
                    "station_id": "F1",
                    "energy_kwh": 3.5,
                    "occupancy_minutes": 12.0,
                    "charge_start_second": 100.0,
                }
            ],
            "cross_site_services": [
                {
                    "customer_id": "C1",
                    "served_by_depot_id": "D0",
                }
            ],
        }

        solution = audit.solution_from_json(json.dumps(payload))

        self.assertEqual(solution.routes[0].vehicle_id, "CV1#T1")
        self.assertEqual(solution.routes[0].node_sequence, ["D0", "C1", "D0"])
        self.assertEqual(solution.charging_actions[0].energy_kwh, 3.5)
        self.assertEqual(solution.cross_site_services[0].customer_id, "C1")

    def test_reachability_decision_requires_sixty_percent_success(self) -> None:
        from baselines.e2_alns import route_packing_reachability_audit as audit

        rows = [
            {"a7_loses": True, "best_reachable": True, "best_no_blowup": True},
            {"a7_loses": True, "best_reachable": True, "best_no_blowup": True},
            {"a7_loses": True, "best_reachable": True, "best_no_blowup": True},
            {"a7_loses": True, "best_reachable": False, "best_no_blowup": True},
            {"a7_loses": True, "best_reachable": False, "best_no_blowup": True},
        ]

        decision = audit.build_decision({"head": "abc123"}, [], rows)

        self.assertEqual(decision["verdict"], "ROUTE_PACKING_REACHABILITY_SUPPORTED")
        self.assertEqual(decision["losing_rows"], 5)
        self.assertAlmostEqual(decision["reachable_fraction"], 0.6)

    def test_artifact_hash_excludes_appledouble_and_cache_dirs(self) -> None:
        from baselines.e2_alns import route_packing_reachability_audit as audit

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.csv").write_text("x\n", encoding="utf-8")
            (root / "._keep.csv").write_text("sidecar\n", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "x.pyc").write_text("cache\n", encoding="utf-8")
            (root / ".tasks").mkdir()
            (root / ".tasks" / "x.json").write_text("{}\n", encoding="utf-8")

            audit.write_hashes(root)
            payload = json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8"))

        self.assertEqual(list(payload["files"]), ["keep.csv"])


if __name__ == "__main__":
    unittest.main()
