"""Zero-search tests for the electrification relocate-resize operator."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
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
        audit, row_fields = gate._ledger_audit_row_fields(
            result.activity
        )
        self.assertEqual(
            set(audit),
            {"passed", "checks", "per_round"},
        )
        self.assertTrue(audit["passed"])
        self.assertTrue(
            audit["checks"]["per_round_caps_closed"]
        )
        self.assertTrue(row_fields["actual_round_caps_closed"])
        self.assertTrue(row_fields["activity_ledgers_reconciled"])
        self.assertFalse(
            row_fields["final_validation_failed_closed"]
        )
        inconsistent = dict(result.activity)
        inconsistent["prescore_selected_moves"] = (
            int(result.activity["prescore_selected_moves"]) + 1
        )
        inconsistent_audit = gate._audit_activity_ledgers(
            inconsistent
        )
        self.assertFalse(inconsistent_audit["passed"])
        self.assertFalse(
            inconsistent_audit["checks"][
                "prescore_round_summaries_close"
            ]
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
        audit, row_fields = gate._ledger_audit_row_fields(
            result.activity
        )
        self.assertTrue(audit["passed"])
        self.assertEqual(len(audit["per_round"]), 1)
        self.assertEqual(
            audit["per_round"][0]["summary_unique_candidates"],
            0,
        )
        self.assertEqual(
            audit["per_round"][0]["summary_exact_attempted"],
            0,
        )
        self.assertTrue(row_fields["actual_round_caps_closed"])
        self.assertTrue(row_fields["activity_ledgers_reconciled"])
        self.assertFalse(
            row_fields["final_validation_failed_closed"]
        )

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

    def test_ledger_consumer_rejects_malformed_audit_shape(
        self,
    ) -> None:
        valid = {
            "passed": True,
            "checks": {"per_round_caps_closed": True},
            "per_round": [],
        }
        self.assertTrue(gate._ledger_per_round_caps_closed(valid))
        invalid = (
            {
                "passed": True,
                "per_round": [],
            },
            {
                "passed": True,
                "checks": {},
                "per_round": [],
            },
            {
                "passed": True,
                "checks": {"per_round_caps_closed": "true"},
                "per_round": [],
            },
            {
                "passed": "true",
                "checks": {"per_round_caps_closed": True},
                "per_round": [],
            },
            {
                "passed": True,
                "checks": {"per_round_caps_closed": True},
                "per_round": {},
            },
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(RuntimeError):
                    gate._ledger_per_round_caps_closed(payload)

    def test_solution_chain_closes_and_detects_detachment(
        self,
    ) -> None:
        source = plateau_solution()
        routes = list(source.routes)
        routes[0] = replace(
            routes[0],
            vehicle_type=(
                "ev"
                if routes[0].vehicle_type.lower() == "cv"
                else "cv"
            ),
        )
        completed = Solution(
            routes=routes,
            charging_actions=list(source.charging_actions),
            cross_site_services=list(source.cross_site_services),
        )
        cv_count = lambda solution: sum(  # noqa: E731
            route.vehicle_type.lower() == "cv"
            for route in solution.routes
        )
        activity = {
            "accepted_moves": [
                {
                    "round": 1,
                    "source_solution_snapshot": asdict(source),
                    "completed_solution_snapshot": asdict(completed),
                }
            ],
            "round_summaries": [
                {"round": 1, "accepted": True}
            ],
            "source_cv_route_count": cv_count(source),
            "final_cv_route_count": cv_count(completed),
            "changed": True,
        }
        audit = gate._audit_solution_chain(
            activity,
            source,
            completed,
        )
        self.assertTrue(audit["passed"])
        detached = gate._audit_solution_chain(
            activity,
            source,
            source,
        )
        self.assertFalse(detached["passed"])
        self.assertFalse(
            detached["checks"]["last_round_ends_at_scenario_final"]
        )
        bad_count = dict(activity)
        bad_count["source_cv_route_count"] = cv_count(source) + 1
        bad_count_audit = gate._audit_solution_chain(
            bad_count,
            source,
            completed,
        )
        self.assertFalse(bad_count_audit["passed"])
        self.assertFalse(
            bad_count_audit["checks"][
                "activity_source_cv_count_closes"
            ]
        )

    def test_execution_recovery_fails_closed_on_evidence_changes(
        self,
    ) -> None:
        original_parent = (
            HERE / "electrification_relocate_resize_behavior_gate"
        )
        original_manifest = json.loads(
            (
                HERE
                / "electrification_relocate_resize_execution_"
                "recovery_v2_20260719.json"
            ).read_text(encoding="utf-8")
        )

        def sha256(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        def sync_hashes(
            parent: Path,
            manifest: dict[str, object],
            manifest_path: Path,
        ) -> None:
            internal_path = parent / "artifact_hashes.json"
            internal = json.loads(
                internal_path.read_text(encoding="utf-8")
            )
            internal["artifacts"] = {
                path.name: sha256(path)
                for path in sorted(parent.iterdir())
                if path.is_file()
                and path.name != "artifact_hashes.json"
                and not path.name.startswith("._")
            }
            internal_path.write_text(
                json.dumps(internal, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            manifest["parent_failure_artifact_hashes"] = {
                path.name: sha256(path)
                for path in sorted(parent.iterdir())
                if path.is_file()
                and not path.name.startswith("._")
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )

        def clean_parent_appledouble(parent: Path) -> None:
            for appledouble in parent.rglob("._*"):
                appledouble.unlink()
            (parent.parent / f"._{parent.name}").unlink(
                missing_ok=True
            )

        with tempfile.TemporaryDirectory(
            prefix=".relocate_recovery_test_",
            dir=HERE,
        ) as temp_name:
            temp = Path(temp_name)
            companion = temp.parent / f"._{temp.name}"
            self.addCleanup(companion.unlink, missing_ok=True)
            parent = temp / "parent"
            recovery = temp / "recovery"
            manifest_path = temp / "recovery.json"
            shutil.copytree(original_parent, parent)
            manifest = dict(original_manifest)
            manifest["parent_failure_directory"] = gate._relative(
                parent
            )
            manifest["recovery_output_directory"] = gate._relative(
                recovery
            )
            sync_hashes(parent, manifest, manifest_path)
            clean_parent_appledouble(parent)
            self.assertEqual(gate._appledouble_paths(parent), [])
            parent_metadata = json.loads(
                (parent / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            expected_sources = {
                *parent_metadata["source_hashes"],
                gate._relative(manifest_path),
                *{
                    gate._relative(parent / name)
                    for name in manifest[
                        "parent_failure_artifact_hashes"
                    ]
                },
            }

            with (
                patch.object(gate, "CANONICAL_OUTPUT", parent),
                patch.object(
                    gate,
                    "EXECUTION_RECOVERY_OUTPUT",
                    recovery,
                ),
                patch.object(
                    gate,
                    "EXECUTION_RECOVERY_MANIFEST",
                    manifest_path,
                ),
                patch.object(
                    gate,
                    "_all_source_files",
                    return_value=tuple(sorted(expected_sources)),
                ) as source_files_mock,
                patch.object(
                    gate.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ),
            ):
                gate._require_execution_recovery_eligibility()

                explicit_appledouble = parent / "._explicit_drift"
                explicit_appledouble.write_text(
                    "drift",
                    encoding="utf-8",
                )
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                clean_parent_appledouble(parent)
                gate._require_execution_recovery_eligibility()

                frozen_false = manifest.pop(
                    "algorithm_change_allowed"
                )
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                manifest["algorithm_change_allowed"] = frozen_false
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )

                allowed_changes = list(
                    manifest["allowed_execution_harness_changes"]
                )
                manifest["allowed_execution_harness_changes"] = [
                    *allowed_changes,
                    "unregistered change",
                ]
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                manifest["allowed_execution_harness_changes"] = (
                    allowed_changes
                )
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )

                hidden_results = parent / "extra_results"
                hidden_results.mkdir()
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                hidden_results.rmdir()

                report_path = parent / "report.md"
                report_backup = temp / "report.backup"
                report_path.rename(report_backup)
                report_path.symlink_to(report_backup)
                clean_parent_appledouble(parent)
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                report_path.unlink()
                report_backup.rename(report_path)

                source_files_mock.return_value = (
                    *tuple(sorted(expected_sources)),
                    "solver/src/unregistered_extra.py",
                )
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                source_files_mock.return_value = tuple(
                    sorted(expected_sources)
                )

                recovery.mkdir()
                with self.assertRaises(FileExistsError):
                    gate._require_execution_recovery_eligibility()
                recovery.rmdir()

                report_original = report_path.read_bytes()
                report_path.write_bytes(report_original + b"drift")
                clean_parent_appledouble(parent)
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                report_path.write_bytes(report_original)
                sync_hashes(parent, manifest, manifest_path)
                clean_parent_appledouble(parent)

                metadata_path = parent / "metadata.json"
                metadata_original = metadata_path.read_bytes()
                metadata = json.loads(
                    metadata_original.decode("utf-8")
                )
                metadata["completed_scenario_count"] = 1
                metadata_path.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                sync_hashes(parent, manifest, manifest_path)
                clean_parent_appledouble(parent)
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                metadata_path.write_bytes(metadata_original)

                raw_path = parent / "raw_runs.csv"
                raw_original = raw_path.read_bytes()
                raw_path.write_text(
                    "status,source_cost,final_cost\n"
                    "PASS,10.0,9.0\n",
                    encoding="utf-8",
                )
                sync_hashes(parent, manifest, manifest_path)
                clean_parent_appledouble(parent)
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()
                raw_path.write_bytes(raw_original)

                metadata = json.loads(
                    metadata_original.decode("utf-8")
                )
                metadata["route_search_guard_attempts"] = 1
                metadata_path.write_text(
                    json.dumps(metadata, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                sync_hashes(parent, manifest, manifest_path)
                clean_parent_appledouble(parent)
                with self.assertRaises(RuntimeError):
                    gate._require_execution_recovery_eligibility()

    def test_failure_seal_preserves_pre_row_route_search_ledger(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".relocate_failure_seal_test_",
        ) as temp_name:
            output = Path(temp_name) / "failure"
            output.mkdir()
            with (
                patch.object(gate, "CANONICAL_OUTPUT", output),
                patch.object(
                    gate,
                    "EXECUTION_RECOVERY_ACTIVE",
                    True,
                ),
                patch.object(
                    gate,
                    "_clean_appledouble",
                    return_value={
                        "returncode": 0,
                        "stdout": "",
                        "stderr": "",
                    },
                ),
                patch.object(
                    gate,
                    "_appledouble_paths",
                    return_value=[],
                ),
                patch.object(
                    gate,
                    "_git",
                    return_value="test-head",
                ),
            ):
                gate._seal_execution_failure(
                    RuntimeError("test failure"),
                    rows=[],
                    source_hashes={},
                    protected_hashes={},
                    input_hashes={},
                    route_search_attempts=[],
                    observed_complete_route_search_evaluations=7,
                )
            metadata = json.loads(
                (output / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                metadata["complete_route_search_evaluations"],
                7,
            )
            self.assertTrue(metadata["execution_recovery_v2"])
            decision = json.loads(
                (output / "decision.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(decision["execution_recovery_v2"])
            self.assertIn(
                "execution_recovery_v2",
                (output / "report.md").read_text(encoding="utf-8"),
            )
            artifact_manifest = json.loads(
                (output / "artifact_hashes.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                set(artifact_manifest["artifacts"]),
                {
                    "decision.json",
                    "execution_failure.json",
                    "metadata.json",
                    "raw_runs.csv",
                    "report.md",
                },
            )


if __name__ == "__main__":
    unittest.main()
