"""Contract tests for the immutable D2 gate runner."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_fresh_d2_gate as runner  # noqa: E402


class FreshD2RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(
            (runner.BUNDLES / "manifest.json").read_text(encoding="utf-8")
        )

    def _rows(
        self,
        *,
        costs: dict[tuple[str, str], float] | None = None,
        signatures: dict[tuple[str, str], str] | None = None,
        elapsed: dict[tuple[str, str], float] | None = None,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for instance in self.manifest["instances"]:
            instance_id = str(instance["instance_id"])
            for arm in runner.ARMS:
                key = (instance_id, arm)
                default_cost = (
                    90.0
                    if arm == runner.CANDIDATE
                    else 95.0
                    if arm == runner.RAW_SELECTOR
                    else 90.1
                    if arm == runner.NO_MID
                    else 100.0
                )
                rows.append(
                    {
                        "instance_id": instance_id,
                        "arm": arm,
                        "recomputed_cost": (
                            costs[key] if costs and key in costs else default_cost
                        ),
                        "elapsed_seconds": (
                            elapsed[key] if elapsed and key in elapsed else 1.0
                        ),
                        "solution_signature": (
                            signatures[key]
                            if signatures and key in signatures
                            else f"{instance_id}:{arm}"
                        ),
                        "feasible": True,
                        "cost_match": True,
                        "budget_exact": True,
                    }
                )
        return rows

    def test_full_prelock_is_deterministic_and_valid(self) -> None:
        primary = runner._run_order(
            self.manifest["instances"],
            phase="primary",
        )
        backup = runner._run_order(
            self.manifest["backup_instances"],
            phase="saturation_backup",
        )
        first = runner.make_blind_lock(self.manifest, primary, backup)
        second = runner.make_blind_lock(self.manifest, primary, backup)
        self.assertEqual(runner.sha_json(first), runner.sha_json(second))
        self.assertEqual(
            runner.validate_lock(first, self.manifest, primary, backup),
            [],
        )
        self.assertTrue(first["official_hgs_install"]["verified"])
        self.assertGreater(
            first["dependency_trees"]["solver_src"]["file_count"],
            0,
        )
        changed = json.loads(json.dumps(first))
        changed["parameters"]["seed"] = 999
        self.assertIn(
            "blind_lock_full_payload_mismatch",
            runner.validate_lock(
                changed,
                self.manifest,
                primary,
                backup,
            ),
        )

    def test_good_synthetic_rows_pass(self) -> None:
        decision = runner.build_decision(
            self._rows(),
            self.manifest["instances"],
            [],
            dataset_role="primary",
        )
        self.assertEqual(
            decision["verdict"],
            "GO_SMALL_MULTI_SEED_CONFIRMATION",
        )
        self.assertTrue(decision["wall_pass"])

    def test_equal_cost_but_different_solutions_is_not_saturation(self) -> None:
        costs: dict[tuple[str, str], float] = {}
        for instance in self.manifest["instances"]:
            for arm in runner.ARMS:
                costs[(str(instance["instance_id"]), arm)] = 100.0
        decision = runner.build_decision(
            self._rows(costs=costs),
            self.manifest["instances"],
            [],
            dataset_role="primary",
        )
        self.assertFalse(decision["all_saturated"])
        self.assertEqual(
            decision["verdict"],
            "STOP_DUAL_BASIN_MECHANISM_ALNS_D2",
        )

    def test_equal_cost_and_same_solution_is_saturation(self) -> None:
        costs: dict[tuple[str, str], float] = {}
        signatures: dict[tuple[str, str], str] = {}
        for instance in self.manifest["instances"]:
            instance_id = str(instance["instance_id"])
            for arm in runner.ARMS:
                costs[(instance_id, arm)] = 100.0
                signatures[(instance_id, arm)] = f"same:{instance_id}"
        decision = runner.build_decision(
            self._rows(costs=costs, signatures=signatures),
            self.manifest["instances"],
            [],
            dataset_role="primary",
        )
        self.assertTrue(decision["all_saturated"])
        self.assertEqual(
            decision["verdict"],
            "INCONCLUSIVE_SATURATED_SMALL_D2",
        )

    def test_wall_gate_is_checked_on_each_instance(self) -> None:
        elapsed: dict[tuple[str, str], float] = {}
        instance_ids = [
            str(item["instance_id"])
            for item in self.manifest["instances"]
        ]
        for arm in runner.ARMS:
            elapsed[(instance_ids[0], arm)] = 1.0
            elapsed[(instance_ids[1], arm)] = 1.0
        elapsed[(instance_ids[1], runner.CANDIDATE)] = 2.0
        decision = runner.build_decision(
            self._rows(elapsed=elapsed),
            self.manifest["instances"],
            [],
            dataset_role="primary",
        )
        self.assertFalse(decision["wall_pass"])
        self.assertEqual(
            decision["candidate_wall_ratio_by_instance"][instance_ids[1]],
            2.0,
        )

    def test_reference_replay_ledger_avoids_nested_double_count(self) -> None:
        activity = {
            "route_source": {"reference_replays": 1},
            "common_completion": {
                "full_solution_replays": 3,
                "responsibility": {"independent_final_replays": 1},
            },
        }
        self.assertEqual(runner._reference_replays(activity), 4)
        candidate = {
            "reference_replay_ledger": {
                "selector": 1,
                "final_completion": 3,
                "total_reported": 7,
            },
            "selector": {"reference_replays": 1},
        }
        self.assertEqual(runner._reference_replays(candidate), 7)

    def test_arm_exception_is_caught_as_a_frozen_failure(self) -> None:
        instance = self.manifest["instances"][0]
        rows: list[dict[str, object]] = []
        witnesses: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        item = {
            "phase": "primary",
            "instance_id": str(instance["instance_id"]),
            "arm": runner.CANDIDATE,
        }
        with patch.object(
            runner,
            "run_arm",
            side_effect=RuntimeError("intentional test failure"),
        ):
            completed = runner._execute_order(
                [item],
                {str(instance["instance_id"]): instance},
                rows,
                witnesses,
                failures,
            )
        self.assertFalse(completed)
        self.assertEqual(rows, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["exception_type"], "RuntimeError")

    def test_prelocked_backup_runs_only_after_true_primary_saturation(
        self,
    ) -> None:
        calls: list[tuple[str, str]] = []

        def fake_run(arm: str, bundle_dir: Path) -> object:
            calls.append((bundle_dir.name, arm))
            return object()

        def fake_normalize(
            *,
            arm: str,
            instance_row: dict[str, object],
            bundle_dir: Path,
            result: object,
        ) -> tuple[dict[str, object], dict[str, object]]:
            _ = bundle_dir, result
            role = str(instance_row["role"])
            if role == "primary":
                cost = 100.0
                signature = f"same:{instance_row['instance_id']}"
            else:
                cost = (
                    90.0
                    if arm == runner.CANDIDATE
                    else 95.0
                    if arm == runner.RAW_SELECTOR
                    else 90.1
                    if arm == runner.NO_MID
                    else 100.0
                )
                signature = f"{instance_row['instance_id']}:{arm}"
            row = {field: "" for field in runner.RAW_FIELDS}
            row.update(
                {
                    "instance_id": str(instance_row["instance_id"]),
                    "dataset_role": role,
                    "source_scale": int(instance_row["source_scale"]),
                    "actual_customer_count": int(
                        instance_row["actual_customer_count"]
                    ),
                    "actual_depot_count": int(
                        instance_row["actual_depot_count"]
                    ),
                    "seed": runner.SEED,
                    "budget": runner.BUDGET,
                    "arm": arm,
                    "reported_algorithm": arm,
                    "reported_cost": cost,
                    "recomputed_cost": cost,
                    "cost_match": True,
                    "evaluations": runner.BUDGET,
                    "budget_exact": True,
                    "complete_resetp_candidate_budget_equalized": True,
                    "total_compute_equalized": False,
                    "elapsed_seconds": 1.0,
                    "feasible": True,
                    "violation_count": 0,
                    "solution_signature": signature,
                    "hgs_native_calls_reported": 0,
                }
            )
            return row, {
                "instance_id": str(instance_row["instance_id"]),
                "dataset_role": role,
                "arm": arm,
            }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "gate"
            with (
                patch.object(runner, "OUT", output),
                patch.object(runner, "run_arm", side_effect=fake_run),
                patch.object(
                    runner,
                    "normalize_row",
                    side_effect=fake_normalize,
                ),
            ):
                exit_code = runner.main()
            self.assertEqual(exit_code, 0)
            decision = json.loads(
                (output / "decision.json").read_text(encoding="utf-8")
            )
            self.assertTrue(decision["backup_activated"])
            self.assertEqual(
                decision["decision_dataset_role"],
                "saturation_backup",
            )
            self.assertEqual(
                len(calls),
                2 * len(runner.ARMS) * 2,
            )
            for required in (
                "blind_lock.json",
                "metadata.json",
                "raw_runs.csv",
                "decision.json",
                "run_failures.json",
                "solution_witnesses.json",
                "artifact_hashes.json",
                "report.md",
            ):
                self.assertTrue((output / required).is_file())


if __name__ == "__main__":
    unittest.main()
