from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_e7_full_day_value_20260714 import (  # noqa: E402
    EXPECTED_STREAMS,
    EvidenceError,
    EventDisposition,
    FORMAL_RUN_RELATIVE_PATH,
    _verify_recorded_file,
    compare_stream,
    file_sha256,
    overall_decision_status,
    reconstruct_arm_ledger,
    require_formal_streams,
    retain_all_streams,
    validate_artifact_manifest,
    validate_event_coverage,
    validate_formal_input_contract,
    validate_new_output_directory,
    validate_revenue_source,
)


def node(node_id: str, node_type: str, demand: int = 0) -> dict:
    return {
        "node_id": node_id,
        "node_type": node_type,
        "demand": demand,
        "ready_time": 0,
        "due_time": 1000,
        "service_time": 10 if node_type == "c" else 0,
        "x": 0,
        "y": 0,
    }


INSTANCE = {
    "nodes": [
        node("D0", "d"),
        node("D1", "d"),
        node("C1", "c", 10),
        node("C2", "c", 20),
    ]
}
OWNERS = [
    {"customer_id": "C1", "owner_depot_id": "D0"},
    {"customer_id": "C2", "owner_depot_id": "D1"},
]
CANCEL_EVENT = {
    "events": [
        {
            "event_id": "E1",
            "event_type": "cancel",
            "customer_id": "C1",
            "t_appear": 100,
        }
    ]
}


def route(vehicle: str, depot: str, customers: list[str]) -> dict:
    return {
        "vehicle_id": vehicle,
        "vehicle_type": "cv",
        "home_depot_id": depot,
        "node_sequence": [depot, *customers, depot],
        "departure_time": 0,
        "return_time": 100,
        "trip_index": 1,
    }


def cost_breakdown(total: int | float) -> dict:
    return {
        "cost_fix": total,
        "cost_km": 0,
        "cost_fuel": 0,
        "cost_elec": 0,
        "cost_occ": 0,
        "cost_transship": 0,
        "cost_carbon": 0,
        "total_cost": total,
    }


def raw_row(arm: str, *, applied: bool) -> dict:
    return {
        "arm": arm,
        "stream_seed": 1,
        "stage": 1,
        "event_ids": "E1",
        "applied_event_ids": "E1" if applied else "",
        "ignored_locked_event_ids": "" if applied else "E1",
    }


def stage_payload(
    arm: str,
    *,
    locked: list[dict],
    active: list[str],
    committed: list[str],
    future: list[str],
    solution_routes: list[dict],
    total: int | float,
) -> dict:
    solution = {"routes": solution_routes, "charging_actions": [], "cross_site_services": []}
    return {
        "arm": arm,
        "stream_seed": 1,
        "stage": 1,
        "locked_routes": locked,
        "active_customer_ids": sorted(active),
        "committed_customer_ids": sorted(committed),
        "future_customer_ids": sorted(future),
        "solution": solution,
        "certificate": {},
        "cost_breakdown": cost_breakdown(total),
    }


def build_ledger(
    arm: str,
    *,
    locked: list[dict],
    applied: bool,
    active: list[str],
    committed: list[str],
    future: list[str],
    total: int | float,
    session_total: int | float | None = None,
):
    final_routes = [route(f"{arm}-V2", "D1", future)] if future else []
    evidence = stage_payload(
        arm,
        locked=locked,
        active=active,
        committed=committed,
        future=future,
        solution_routes=final_routes,
        total=total,
    )
    return reconstruct_arm_ledger(
        stream_seed=1,
        arm=arm,
        instance_payload=INSTANCE,
        event_payload=CANCEL_EVENT,
        owner_rows=OWNERS,
        raw_stage_rows=[raw_row(arm, applied=applied)],
        stage_evidence=[evidence],
        final_solution=evidence["solution"],
        session_row={
            "final_total_cost": total if session_total is None else session_total
        },
    )


class ReconstructionTests(unittest.TestCase):
    def test_same_workload_unlocks_direct_cost_percentage(self) -> None:
        cooperative = build_ledger(
            "cooperative",
            locked=[],
            applied=True,
            active=["C2"],
            committed=[],
            future=["C2"],
            total=8,
        )
        independent = build_ledger(
            "independent",
            locked=[],
            applied=True,
            active=["C2"],
            committed=[],
            future=["C2"],
            total=10,
        )

        comparison = compare_stream(cooperative, independent)

        self.assertTrue(comparison["workload_equal"])
        self.assertEqual(comparison["status"], "COMPARABLE_SAME_WORKLOAD")
        self.assertEqual(Decimal(comparison["cost_change_percent"]), Decimal("20"))
        self.assertIsNone(comparison["net_benefit_change"])
        self.assertEqual(cooperative.served_demand_kg, Decimal("20"))

    def test_different_workload_blanks_cost_and_uses_net_benefit(self) -> None:
        cooperative = build_ledger(
            "cooperative",
            locked=[route("cooperative-V1", "D0", ["C1"])],
            applied=False,
            active=["C1", "C2"],
            committed=["C1"],
            future=["C2"],
            total=12,
        )
        independent = build_ledger(
            "independent",
            locked=[],
            applied=True,
            active=["C2"],
            committed=[],
            future=["C2"],
            total=10,
        )

        comparison = compare_stream(cooperative, independent)

        self.assertFalse(comparison["workload_equal"])
        self.assertEqual(comparison["status"], "DIFFERENT_WORKLOAD")
        self.assertIsNone(comparison["cost_change_percent"])
        expected = (Decimal("30") * Decimal("0.18936") - Decimal("12")) - (
            Decimal("20") * Decimal("0.18936") - Decimal("10")
        )
        self.assertEqual(Decimal(comparison["net_benefit_change"]), expected)
        reason = json.loads(comparison["difference_reason_json"])
        self.assertEqual(reason["customers"][0]["customer_id"], "C1")
        self.assertEqual(
            reason["customers"][0]["differences"], ["served_only_by_cooperative"]
        )
        self.assertEqual(
            reason["customers"][0]["cooperative_events"][0]["status"],
            "ignored_locked",
        )
        self.assertEqual(
            reason["customers"][0]["independent_events"][0]["status"],
            "applied",
        )

    def test_open_cost_ledger_blocks_both_effect_metrics(self) -> None:
        cooperative = build_ledger(
            "cooperative",
            locked=[],
            applied=True,
            active=["C2"],
            committed=[],
            future=["C2"],
            total=8,
            session_total=9,
        )
        independent = build_ledger(
            "independent",
            locked=[],
            applied=True,
            active=["C2"],
            committed=[],
            future=["C2"],
            total=10,
        )

        comparison = compare_stream(cooperative, independent)

        self.assertEqual(comparison["status"], "INCOMPARABLE_COST_LEDGER_OPEN")
        self.assertIsNone(comparison["cost_change_percent"])
        self.assertIsNone(comparison["net_benefit_change"])

    def test_ignored_event_without_locked_service_is_rejected(self) -> None:
        with self.assertRaisesRegex(EvidenceError, "not locked by service"):
            build_ledger(
                "cooperative",
                locked=[],
                applied=False,
                active=["C1", "C2"],
                committed=[],
                future=["C1", "C2"],
                total=8,
            )

    def test_all_five_streams_are_retained_even_when_missing(self) -> None:
        rows = retain_all_streams(
            {
                1: {"stream_seed": 1, "status": "COMPARABLE_SAME_WORKLOAD"},
                3: {"stream_seed": 3, "status": "DIFFERENT_WORKLOAD"},
            }
        )

        self.assertEqual([row["stream_seed"] for row in rows], [1, 2, 3, 4, 5])
        self.assertEqual(rows[1]["status"], "MISSING_EVIDENCE")
        self.assertEqual(rows[4]["status"], "MISSING_EVIDENCE")


class FormalContractHardeningTests(unittest.TestCase):
    def test_all_55_events_must_be_covered_exactly_once(self) -> None:
        events = {str(index): {"event_id": index} for index in range(1, 56)}
        dispositions = [
            EventDisposition(str(index), f"C{index}", "change", 1, "applied")
            for index in range(1, 56)
        ]
        validate_event_coverage(events, dispositions, expected_count=55)

        with self.assertRaisesRegex(EvidenceError, "exactly once"):
            validate_event_coverage(events, dispositions[:-1], expected_count=55)
        with self.assertRaisesRegex(EvidenceError, "exactly once"):
            validate_event_coverage(
                events,
                [*dispositions[:-1], dispositions[0]],
                expected_count=55,
            )
        with self.assertRaisesRegex(EvidenceError, "must contain 55"):
            validate_event_coverage(
                {**events, "56": {"event_id": 56}},
                dispositions,
                expected_count=55,
            )

    def test_reconstruction_calls_the_55_event_gate(self) -> None:
        with self.assertRaisesRegex(EvidenceError, "must contain 55"):
            reconstruct_arm_ledger(
                stream_seed=1,
                arm="cooperative",
                instance_payload=INSTANCE,
                event_payload=CANCEL_EVENT,
                owner_rows=OWNERS,
                raw_stage_rows=[raw_row("cooperative", applied=True)],
                stage_evidence=[
                    stage_payload(
                        "cooperative",
                        locked=[],
                        active=["C2"],
                        committed=[],
                        future=["C2"],
                        solution_routes=[route("V1", "D1", ["C2"])],
                        total=10,
                    )
                ],
                final_solution={
                    "routes": [route("V1", "D1", ["C2"])],
                    "charging_actions": [],
                    "cross_site_services": [],
                },
                session_row={"final_total_cost": 10},
                expected_event_count=55,
            )

    def test_formal_streams_are_fixed_and_ordered(self) -> None:
        require_formal_streams(EXPECTED_STREAMS)
        for changed in ((1, 2, 3, 4), (5, 4, 3, 2, 1), (1, 2, 3, 4, 5, 5)):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(EvidenceError, "requires streams"):
                    require_formal_streams(changed)

    def test_any_open_cost_ledger_forces_overall_fail(self) -> None:
        self.assertEqual(
            overall_decision_status(
                failures={},
                cost_closure_failures=[],
                ledger_count=10,
                complete_event_coverage=True,
            ),
            "PASS",
        )
        self.assertEqual(
            overall_decision_status(
                failures={},
                cost_closure_failures=["stream3__cooperative"],
                ledger_count=10,
                complete_event_coverage=True,
            ),
            "FAIL",
        )

    def test_output_must_be_new_and_separate_from_every_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sealed = root / "sealed"
            sealed.mkdir()
            safe = root / "new-output"
            validate_new_output_directory(safe, [sealed])

            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(EvidenceError, "must be new"):
                validate_new_output_directory(existing, [sealed])
            with self.assertRaisesRegex(EvidenceError, "overlaps"):
                validate_new_output_directory(sealed / "child", [sealed])
            with self.assertRaisesRegex(EvidenceError, "overlaps"):
                validate_new_output_directory(root, [sealed])

    def test_revenue_is_read_from_the_run_commit_and_fingerprinted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            prices = repo / "solver/src/setp_solver/prices.py"
            prices.parent.mkdir(parents=True)
            prices.write_text("revenue_per_kg = 0.18936\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "freeze"], cwd=repo, check=True)
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()

            evidence = validate_revenue_source(
                repo, {"source_commit": commit, "run_start_commit": commit}
            )
            self.assertEqual(evidence["revenue_per_kg"], "0.18936")
            self.assertEqual(evidence["commit"], commit)
            self.assertEqual(evidence["path"], "solver/src/setp_solver/prices.py")
            self.assertEqual(evidence["sha256"], file_sha256(prices))

            prices.write_text("revenue_per_kg = 0.2\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "wrong"], cwd=repo, check=True)
            wrong = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            with self.assertRaisesRegex(EvidenceError, "expected 0.18936"):
                validate_revenue_source(
                    repo, {"source_commit": wrong, "run_start_commit": wrong}
                )
            with self.assertRaisesRegex(EvidenceError, "differ"):
                validate_revenue_source(
                    repo, {"source_commit": wrong, "run_start_commit": commit}
                )

    def test_artifact_manifest_rejects_mutation_and_unlisted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run = repo / FORMAL_RUN_RELATIVE_PATH
            run.mkdir(parents=True)
            for name, value in (
                ("metadata.json", "{}\n"),
                ("session_summary.csv", "stream_seed,arm\n"),
                ("raw_runs.csv", "stream_seed,arm\n"),
            ):
                (run / name).write_text(value, encoding="utf-8")

            entries = []
            for path in sorted(run.iterdir()):
                entries.append(
                    {
                        "path": path.relative_to(repo).as_posix(),
                        "sha256": file_sha256(path),
                        "bytes": path.stat().st_size,
                    }
                )
            (run / "artifact_hashes.json").write_text(
                json.dumps(
                    {
                        "algorithm": "sha256",
                        "excluded": ["artifact_hashes.json", "._*"],
                        "artifacts": entries,
                    }
                ),
                encoding="utf-8",
            )
            validate_artifact_manifest(repo, run)

            (run / "metadata.json").write_text('{"mutated":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "hash differs"):
                validate_artifact_manifest(repo, run)
            (run / "metadata.json").write_text("{}\n", encoding="utf-8")
            (run / "unlisted.txt").write_text("extra\n", encoding="utf-8")
            with self.assertRaisesRegex(EvidenceError, "does not exactly close"):
                validate_artifact_manifest(repo, run)

    def test_recorded_path_must_be_relative_exact_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            expected = Path("frozen/input.json")
            path = repo / expected
            path.parent.mkdir(parents=True)
            path.write_text("{}\n", encoding="utf-8")
            row = {"path": expected.as_posix(), "sha": file_sha256(path)}
            self.assertEqual(
                _verify_recorded_file(
                    repo,
                    row,
                    "path",
                    "sha",
                    expected_relative_path=expected,
                ),
                path.resolve(),
            )
            with self.assertRaisesRegex(EvidenceError, "frozen path"):
                _verify_recorded_file(
                    repo,
                    {"path": "other.json", "sha": row["sha"]},
                    "path",
                    "sha",
                    expected_relative_path=expected,
                )
            with self.assertRaisesRegex(EvidenceError, "repository-relative"):
                _verify_recorded_file(
                    repo,
                    {"path": str(path.resolve()), "sha": row["sha"]},
                    "path",
                    "sha",
                )

    def test_formal_batch_and_instance_paths_cannot_be_substituted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            with self.assertRaisesRegex(EvidenceError, "not the frozen formal batch"):
                validate_formal_input_contract(
                    run_dir=repo / "another-run",
                    repo_root=repo,
                    instance_path=repo / "anything.json",
                    metadata={},
                    sessions=[],
                    raw_rows=[],
                )
            formal = repo / FORMAL_RUN_RELATIVE_PATH
            formal.mkdir(parents=True)
            with self.assertRaisesRegex(EvidenceError, "not the frozen 221-customer"):
                validate_formal_input_contract(
                    run_dir=formal,
                    repo_root=repo,
                    instance_path=repo / "anything.json",
                    metadata={},
                    sessions=[],
                    raw_rows=[],
                )


if __name__ == "__main__":
    unittest.main()
