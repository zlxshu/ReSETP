from __future__ import annotations

import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

WORK = Path(__file__).resolve().parent
if str(WORK) not in sys.path:
    sys.path.insert(0, str(WORK))

import validate_e7_records_independent_20260714 as audit
from setp_solver.instance_loader import Instance, Node


REPO_ROOT = Path("/Volumes/移动硬盘（512G）/ReSETP")


def stream1_stage1_fixture() -> dict:
    run_dir = (
        REPO_ROOT
        / "baselines/e7_dynamic/e7_v2_20260714/preflight/"
        "shared_start_stream1_400_route_fix"
    )
    summaries = {
        (int(row["stream_seed"]), row["arm"]): row
        for row in audit.read_csv(run_dir / "session_summary.csv")
    }
    summary = summaries[(1, "cooperative")]
    evidence = audit.read_json(REPO_ROOT / summary["stage_evidence_path"])
    bundle = audit.load_search_bundle(REPO_ROOT / audit.BASE_BUNDLE)
    prices = audit.formal_prices()
    initial_solution = audit.solution_from_dict(
        audit.read_json(REPO_ROOT / summary["initial_solution_path"])
    )
    initial_certificate = audit.certificate_from_dict(
        audit.read_json(REPO_ROOT / summary["initial_certificate_path"])
    )
    _, owners, batches = audit.validate_event_stream(REPO_ROOT, 1)
    batch = batches[0]
    cut = audit.derive_initial_cut(
        initial_solution,
        initial_certificate,
        bundle.instance,
        prices,
        batch.trigger_second,
    )
    committed = {
        customer_id
        for route in cut.locked_routes
        for customer_id in audit._route_customers(asdict(route), bundle.instance)
    }
    effective = audit.apply_event_batch(bundle.instance, batch.events, committed).instance
    return {
        "run_dir": run_dir,
        "summary": summary,
        "evidence": evidence,
        "bundle": bundle,
        "prices": prices,
        "batch": batch,
        "cut": cut,
        "effective": effective,
        "owners": owners,
    }


def tiny_instance() -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node("D1", "d", 10.0, 0.0, due_time=100_000.0),
        Node("C1", "c", 1.0, 0.0, demand=10.0, ready_time=0.0, due_time=1000.0, service_time=5.0),
        Node("C2", "c", 9.0, 0.0, demand=20.0, ready_time=0.0, due_time=1000.0, service_time=5.0),
        Node("C3", "c", 5.0, 0.0, demand=30.0, ready_time=0.0, due_time=1000.0, service_time=5.0),
    ]
    matrix = [
        [abs(left.x - right.x) for right in nodes]
        for left in nodes
    ]
    return Instance(nodes=nodes, distance_matrix=matrix, num_cv=1, num_ev=1)


def event(
    event_id: str,
    event_type: str,
    customer_id: str,
    old: float,
    new: float,
    x: float,
    *,
    appear: float = 1.0,
    service: float | None = None,
) -> dict:
    return {
        "seed": 1,
        "event_id": event_id,
        "event_type": event_type,
        "t_appear": appear,
        "customer_id": customer_id,
        "old_demand": old,
        "new_demand": new,
        "delta_demand": new - old,
        "x": x,
        "y": 0.0,
        "old_ready_time": 0.0,
        "old_due_time": 1000.0,
        "new_ready_time": 0.0,
        "new_due_time": 1000.0,
        "new_service_time": service,
    }


class FrozenStreamTests(unittest.TestCase):
    def test_all_five_streams_derive_the_frozen_stage_counts(self) -> None:
        root = REPO_ROOT / audit.EVENT_ROOT
        observed = {}
        for seed in audit.EXPECTED_STREAMS:
            events = audit.read_json(root / f"stream_seed{seed}.events.json")
            batches = audit.derive_trigger_batches(events)
            observed[seed] = len(batches)
            self.assertEqual(sum(len(batch.events) for batch in batches), 55)
        self.assertEqual(observed, audit.EXPECTED_STAGE_COUNTS)

    def test_all_five_frozen_stream_indexes_close(self) -> None:
        for seed in audit.EXPECTED_STREAMS:
            events, owners, batches = audit.validate_event_stream(REPO_ROOT, seed)
            self.assertEqual(len(events), 55)
            self.assertGreaterEqual(len(owners), 221)
            self.assertEqual(len(batches), audit.EXPECTED_STAGE_COUNTS[seed])

    def test_trigger_mutation_is_detected_without_touching_frozen_file(self) -> None:
        root = REPO_ROOT / audit.EVENT_ROOT
        events = audit.read_json(root / "stream_seed1.events.json")
        mutated = copy.deepcopy(events)
        mutated[0]["t_appear"] = 50_000.0
        original = audit.derive_trigger_batches(events)
        changed = audit.derive_trigger_batches(mutated)
        self.assertNotEqual(
            [(item.trigger_second, [e["event_id"] for e in item.events]) for item in original],
            [(item.trigger_second, [e["event_id"] for e in item.events]) for item in changed],
        )

    def test_stream1_preflight_replay_finds_the_known_workload_difference(self) -> None:
        run_dir = (
            REPO_ROOT
            / "baselines/e7_dynamic/e7_v2_20260714/preflight/"
            "shared_start_stream1_400_route_fix"
        )
        raw_rows = audit.read_csv(run_dir / "raw_runs.csv")
        raw_by_key = {
            (int(row["stream_seed"]), row["arm"], int(row["stage"])): row
            for row in raw_rows
        }
        summaries = {
            (int(row["stream_seed"]), row["arm"]): row
            for row in audit.read_csv(run_dir / "session_summary.csv")
        }
        _, owners, batches = audit.validate_event_stream(REPO_ROOT, 1)
        base = audit.load_search_bundle(REPO_ROOT / audit.BASE_BUNDLE).instance
        bundle = audit.load_search_bundle(REPO_ROOT / audit.BASE_BUNDLE)
        replayed = {
            arm: audit.replay_session_records(
                repo_root=REPO_ROOT,
                run_dir=run_dir,
                stream_seed=1,
                arm=arm,
                batches=batches,
                owners=owners,
                summary=summaries[(1, arm)],
                raw_by_key=raw_by_key,
                base_instance=base,
                carbon_profile=bundle.carbon_profile,
                prices=audit.formal_prices(),
            )
            for arm in audit.EXPECTED_ARMS
        }
        cooperative = replayed["cooperative"]
        independent = replayed["independent"]
        differing = {
            customer_id
            for customer_id in set(cooperative.final_workload) | set(independent.final_workload)
            if cooperative.final_workload.get(customer_id) != independent.final_workload.get(customer_id)
        }
        self.assertEqual(differing, {"C109"})
        self.assertEqual(cooperative.final_customer_count - independent.final_customer_count, 1)
        self.assertAlmostEqual(cooperative.final_total_demand - independent.final_total_demand, 468.0)


class EventApplicationTests(unittest.TestCase):
    def test_locked_cancel_and_change_keep_original_work(self) -> None:
        source = tiny_instance()
        events = [
            event("1", "cancel", "C1", 10.0, 0.0, 1.0),
            event("2", "demand_change", "C2", 20.0, 24.0, 9.0, appear=2.0),
        ]
        result = audit.apply_event_batch(source, events, {"C1", "C2"})
        nodes = {node.node_id: node for node in result.instance.nodes}
        self.assertEqual(result.applied_event_ids, ())
        self.assertEqual(result.ignored_locked_event_ids, ("1", "2"))
        self.assertEqual(nodes["C1"].demand, 10.0)
        self.assertEqual(nodes["C2"].demand, 20.0)

    def test_open_cancel_change_and_add_are_applied(self) -> None:
        source = tiny_instance()
        events = [
            event("1", "cancel", "C1", 10.0, 0.0, 1.0),
            event("2", "demand_change", "C2", 20.0, 24.0, 9.0, appear=2.0),
            event("3", "add", "N1", 0.0, 7.0, 6.0, appear=3.0, service=9.0),
        ]
        result = audit.apply_event_batch(source, events, set())
        nodes = {node.node_id: node for node in result.instance.nodes}
        self.assertEqual(result.applied_event_ids, ("1", "2", "3"))
        self.assertEqual(result.ignored_locked_event_ids, ())
        self.assertNotIn("C1", nodes)
        self.assertEqual(nodes["C2"].demand, 24.0)
        self.assertEqual(nodes["N1"].service_time, 9.0)

    def test_wrong_old_demand_is_rejected(self) -> None:
        bad = event("1", "cancel", "C1", 11.0, 0.0, 1.0)
        bad["delta_demand"] = -11.0
        with self.assertRaisesRegex(audit.AuditFailure, "old values"):
            audit.apply_event_batch(tiny_instance(), [bad], set())

    def test_add_can_never_be_ignored(self) -> None:
        added = event("1", "add", "N1", 0.0, 7.0, 6.0, service=9.0)
        with self.assertRaisesRegex(audit.AuditFailure, "unexpectedly locked"):
            audit.apply_event_batch(tiny_instance(), [added], {"N1"})


class CounterAndTimingTests(unittest.TestCase):
    def good_counter_row(self) -> dict[str, str]:
        return {
            "evaluations": "400",
            "changed_candidate_count": "385",
            "search_exact_check_count": "385",
            "executable_candidate_count": "51",
            "accepted_candidate_count": "2",
            "search_rejection_counts_json": json.dumps({"reason_a": 300, "reason_b": 34}),
        }

    def test_search_counter_equalities_pass(self) -> None:
        audit.validate_search_counts(self.good_counter_row(), 400)

    def test_search_counter_mutation_is_rejected(self) -> None:
        row = self.good_counter_row()
        row["search_rejection_counts_json"] = json.dumps({"reason_a": 300, "reason_b": 33})
        with self.assertRaisesRegex(audit.AuditFailure, "do not close"):
            audit.validate_search_counts(row, 400)

    def test_changed_count_above_budget_is_rejected(self) -> None:
        row = self.good_counter_row()
        row.update({
            "changed_candidate_count": "401",
            "search_exact_check_count": "401",
            "executable_candidate_count": "51",
            "search_rejection_counts_json": json.dumps({"reason": 350}),
        })
        with self.assertRaisesRegex(audit.AuditFailure, "changed candidate count"):
            audit.validate_search_counts(row, 400)

    def test_negative_search_count_is_rejected(self) -> None:
        row = self.good_counter_row()
        row.update({
            "changed_candidate_count": "-1",
            "search_exact_check_count": "-1",
            "executable_candidate_count": "-1",
            "accepted_candidate_count": "-1",
            "search_rejection_counts_json": "{}",
        })
        with self.assertRaisesRegex(audit.AuditFailure, "changed candidate count"):
            audit.validate_search_counts(row, 400)

    def test_stage_timing_passes_and_mutation_fails(self) -> None:
        batch = audit.TriggerBatch(1, 100.0, "q_bar", tuple())
        next_batch = audit.TriggerBatch(2, 160.0, "delta_t", tuple())
        row = {
            "trigger_second": "100",
            "trigger_reason": "q_bar",
            "next_trigger_second": "160",
            "available_compute_seconds": "60",
            "elapsed_seconds": "59.9",
            "completed_before_next_trigger": "True",
        }
        audit.validate_stage_timing(row, batch, next_batch)
        row["elapsed_seconds"] = "60.1"
        with self.assertRaisesRegex(audit.AuditFailure, "did not finish"):
            audit.validate_stage_timing(row, batch, next_batch)


class StrictReplayAndCostTests(unittest.TestCase):
    def test_independently_reconstructed_asset_state_mutation_is_rejected(self) -> None:
        fixture = stream1_stage1_fixture()
        recorded = copy.deepcopy(fixture["evidence"][0]["asset_states"])
        asset_id = sorted(recorded)[0]
        recorded[asset_id]["available_second"] += 1.0
        with self.assertRaisesRegex(audit.AuditFailure, "available"):
            audit.assert_asset_states_match(
                fixture["cut"].asset_states,
                recorded,
                "mutated stage",
            )

    def test_certificate_clock_mutation_is_rejected_by_bottom_checker(self) -> None:
        fixture = stream1_stage1_fixture()
        stage = fixture["evidence"][0]
        solution = audit.solution_from_dict(stage["solution"])
        certificate_payload = copy.deepcopy(stage["certificate"])
        certificate_payload["trips"][0]["return_second"] += 1.0
        certificate = audit.certificate_from_dict(certificate_payload)
        with self.assertRaises(ValueError):
            audit.validate_dynamic_multitrip_certificate(
                solution,
                certificate,
                fixture["effective"],
                fixture["prices"],
                asset_states=fixture["cut"].asset_states,
                stage_start_second=fixture["batch"].trigger_second,
                locked_charging_actions=fixture["cut"].locked_charging_actions,
            )

    def test_cost_component_mutation_is_rejected(self) -> None:
        fixture = stream1_stage1_fixture()
        stage = fixture["evidence"][0]
        solution = audit.solution_from_dict(stage["solution"])
        future = audit.evaluate_direct(
            solution,
            fixture["effective"],
            fixture["bundle"].carbon_profile,
            fixture["prices"],
        )
        mutated = {
            key: future[key]
            for key in audit.COST_BREAKDOWN_FIELDS
        }
        mutated["total_cost"] = float(future["total_cost"]) + 0.01
        with self.assertRaisesRegex(audit.AuditFailure, "total_cost"):
            audit.assert_cost_breakdown(mutated, future, "mutated cost")

    def test_missing_cost_component_is_rejected(self) -> None:
        fixture = stream1_stage1_fixture()
        recorded = copy.deepcopy(fixture["evidence"][0]["cost_breakdown"])
        recorded.pop("cost_fuel")
        with self.assertRaisesRegex(audit.AuditFailure, "cost fields"):
            audit.assert_cost_breakdown(recorded, recorded, "missing component")

    def test_metric_tolerance_accepts_small_roundoff_and_rejects_large_error(self) -> None:
        self.assertTrue(audit.metric_close(1000.0, 1000.0 + 5e-7))
        self.assertFalse(audit.metric_close(1000.0, 1000.0 + 1e-3))


class EvidenceContractTests(unittest.TestCase):
    def test_commit_bound_file_accepts_exact_blob_and_rejects_mutation(self) -> None:
        commit = "7a3f191058054fc69306ce7c97bd3043af7cd16c"
        relative = "baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py"
        blob = audit.git_blob(REPO_ROOT, commit, relative)
        with tempfile.TemporaryDirectory() as temporary:
            actual = Path(temporary) / "runner.py"
            actual.write_bytes(blob)
            audit.validate_commit_bound_file(
                REPO_ROOT, commit, relative, actual_path=actual
            )
            actual.write_bytes(blob + b"\n# mutation\n")
            with self.assertRaisesRegex(audit.AuditFailure, "differs"):
                audit.validate_commit_bound_file(
                    REPO_ROOT, commit, relative, actual_path=actual
                )

    def test_runtime_dependency_chain_contains_every_formal_entrypoint(self) -> None:
        required = {
            "baselines/e3_ablation/e3_v3_runner.py",
            "baselines/e7_dynamic/e7_dynamic_continuous_trigger_gate_20260714.py",
            "baselines/e7_dynamic/e7_p2_single_event_probe_20260714.py",
            "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
            "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
            "solver/src/setp_solver/algorithms/resetp_alns/operators/feasible_repair.py",
            "solver/src/setp_solver/search/dynamic.py",
            "solver/src/setp_solver/search/metaheuristic_baselines.py",
        }
        self.assertTrue(required <= set(audit.CRITICAL_TRACKED_PATHS))
        commit = "7a3f191058054fc69306ce7c97bd3043af7cd16c"
        relative = "baselines/e3_ablation/e3_v3_runner.py"
        with tempfile.TemporaryDirectory() as temporary:
            actual = Path(temporary) / "e3_v3_runner.py"
            actual.write_bytes(audit.git_blob(REPO_ROOT, commit, relative) + b"\n# altered\n")
            with self.assertRaisesRegex(audit.AuditFailure, "differs"):
                audit.validate_commit_bound_file(
                    REPO_ROOT, commit, relative, actual_path=actual
                )

    def test_formal_metadata_fields_are_locked(self) -> None:
        metadata = {
            "contract_id": audit.CONTRACT_ID,
            "scope": "formal",
            "arms": list(audit.EXPECTED_ARMS),
            "streams": list(audit.EXPECTED_STREAMS),
            "maximum_stages": None,
            "delta_t": audit.DELTA_T_SECONDS,
            "delta_t_seconds": audit.DELTA_T_SECONDS,
            "failure_count": 0,
        }
        decision = {"failure_count": 0}
        audit.validate_formal_metadata_contract(metadata, decision)
        mutations = (
            ("arms", ["independent", "cooperative"]),
            ("maximum_stages", 7),
            ("delta_t", audit.DELTA_T_SECONDS + 1),
            ("delta_t_seconds", audit.DELTA_T_SECONDS + 1),
            ("failure_count", 1),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                changed = copy.deepcopy(metadata)
                changed[field] = value
                with self.assertRaises(audit.AuditFailure):
                    audit.validate_formal_metadata_contract(changed, decision)

    def test_operator_menu_and_fingerprint_reject_deletion(self) -> None:
        frozen = ";".join(audit.EXPECTED_OPERATOR_PAIRS)
        audit.validate_operator_pairs(frozen, "frozen")
        shortened = ";".join(audit.EXPECTED_OPERATOR_PAIRS[:-1])
        with self.assertRaisesRegex(audit.AuditFailure, "operator-pair count"):
            audit.validate_operator_pairs(shortened, "mutated")

    def test_event_numeric_contract_rejects_nonfinite_or_invalid_values(self) -> None:
        valid = event("1", "add", "N1", 0.0, 7.0, 6.0, service=9.0)
        audit.validate_event_numeric_contract(valid, "valid")
        mutations = []
        nonfinite = copy.deepcopy(valid)
        nonfinite["x"] = float("nan")
        mutations.append(nonfinite)
        nonpositive = copy.deepcopy(valid)
        nonpositive["new_demand"] = 0.0
        nonpositive["delta_demand"] = 0.0
        mutations.append(nonpositive)
        inverted = copy.deepcopy(valid)
        inverted["new_ready_time"] = 1001.0
        mutations.append(inverted)
        unclosed = copy.deepcopy(valid)
        unclosed["delta_demand"] = 6.0
        mutations.append(unclosed)
        for changed in mutations:
            with self.subTest(changed=changed):
                with self.assertRaises(audit.AuditFailure):
                    audit.validate_event_numeric_contract(changed, "mutated")
        valid_change = event(
            "2", "demand_change", "C1", 10.0, 12.0, 1.0
        )
        audit.validate_event_numeric_contract(valid_change, "valid change")
        invalid_change = copy.deepcopy(valid_change)
        invalid_change["new_demand"] = 0.0
        invalid_change["delta_demand"] = -10.0
        with self.assertRaisesRegex(audit.AuditFailure, "changed demand"):
            audit.validate_event_numeric_contract(invalid_change, "invalid change")

    def test_owner_population_rejects_missing_or_extra_customer(self) -> None:
        events = audit.read_json(
            REPO_ROOT / audit.EVENT_ROOT / "stream_seed1.events.json"
        )
        owner_rows = audit.read_csv(
            REPO_ROOT / audit.EVENT_ROOT / "stream_seed1.owners.csv"
        )
        owners = {row["customer_id"]: row["owner_depot_id"] for row in owner_rows}
        base = audit.load_search_bundle(REPO_ROOT / audit.BASE_BUNDLE).instance
        original = audit._customer_ids(base)
        audit.validate_owner_population(owners, events, original, "stream1")
        missing = dict(owners)
        missing.pop(next(iter(missing)))
        with self.assertRaisesRegex(audit.AuditFailure, "owner population"):
            audit.validate_owner_population(missing, events, original, "stream1")
        extra = dict(owners)
        extra["EXTRA"] = "D0"
        with self.assertRaisesRegex(audit.AuditFailure, "owner population"):
            audit.validate_owner_population(extra, events, original, "stream1")

    def test_original_owner_value_must_match_frozen_geographic_map(self) -> None:
        events = audit.read_json(
            REPO_ROOT / audit.EVENT_ROOT / "stream_seed1.events.json"
        )
        owner_rows = audit.read_csv(
            REPO_ROOT / audit.EVENT_ROOT / "stream_seed1.owners.csv"
        )
        owners = {row["customer_id"]: row["owner_depot_id"] for row in owner_rows}
        base = audit.load_search_bundle(REPO_ROOT / audit.BASE_BUNDLE).instance
        audit.validate_owner_and_donor_provenance(
            REPO_ROOT, owners, events, base, "stream1"
        )
        mutated = dict(owners)
        customer_id = "C001"
        mutated[customer_id] = "D1" if owners[customer_id] == "D0" else "D0"
        with self.assertRaisesRegex(audit.AuditFailure, "stream owner value"):
            audit.validate_owner_and_donor_provenance(
                REPO_ROOT, mutated, events, base, "stream1"
            )

    def test_added_customer_donor_or_owner_mutation_is_rejected(self) -> None:
        events = audit.read_json(
            REPO_ROOT / audit.EVENT_ROOT / "stream_seed1.events.json"
        )
        owner_rows = audit.read_csv(
            REPO_ROOT / audit.EVENT_ROOT / "stream_seed1.owners.csv"
        )
        owners = {row["customer_id"]: row["owner_depot_id"] for row in owner_rows}
        base = audit.load_search_bundle(REPO_ROOT / audit.BASE_BUNDLE).instance
        add_index = next(
            index for index, row in enumerate(events) if row["event_type"] == "add"
        )
        mutations = []
        changed_coordinate = copy.deepcopy(events)
        changed_coordinate[add_index]["x"] += 1.0
        mutations.append(changed_coordinate)
        changed_instance = copy.deepcopy(events)
        changed_instance[add_index]["donor_instance_id"] = "wrong-instance"
        mutations.append(changed_instance)
        changed_donor = copy.deepcopy(events)
        changed_donor[add_index]["donor_customer_id"] = "missing-donor"
        mutations.append(changed_donor)
        changed_marker = copy.deepcopy(events)
        changed_marker[add_index]["service_time_source"] = "not-exact"
        mutations.append(changed_marker)
        for changed in mutations:
            with self.subTest(field=changed[add_index]):
                with self.assertRaises(audit.AuditFailure):
                    audit.validate_owner_and_donor_provenance(
                        REPO_ROOT, owners, changed, base, "stream1"
                    )

        changed_owners = dict(owners)
        customer_id = events[add_index]["customer_id"]
        changed_owners[customer_id] = (
            "D1" if owners[customer_id] == "D0" else "D0"
        )
        with self.assertRaisesRegex(audit.AuditFailure, "recomputed owner"):
            audit.validate_owner_and_donor_provenance(
                REPO_ROOT, changed_owners, events, base, "stream1"
            )

    def test_exact_session_path_rejects_same_kind_of_file_elsewhere(self) -> None:
        fixture = stream1_stage1_fixture()
        audit.assert_session_paths(
            REPO_ROOT,
            fixture["run_dir"],
            1,
            "cooperative",
            fixture["summary"],
        )
        mutated = dict(fixture["summary"])
        mutated["final_solution_path"] = mutated["final_solution_path"].replace(
            "solutions/", "certificates/"
        )
        with self.assertRaisesRegex(audit.AuditFailure, "exact final_solution_path"):
            audit.assert_session_paths(
                REPO_ROOT, fixture["run_dir"], 1, "cooperative", mutated
            )

    def test_fixed_shared_start_rejects_path_or_hash_substitution(self) -> None:
        fixture = stream1_stage1_fixture()
        audit.validate_shared_start_contract(
            REPO_ROOT,
            fixture["summary"],
            fixture["bundle"].instance,
            fixture["owners"],
        )
        mutated = dict(fixture["summary"])
        mutated["initial_solution_sha256"] = "0" * 64
        with self.assertRaisesRegex(audit.AuditFailure, "fixed initial solution hash"):
            audit.validate_shared_start_contract(
                REPO_ROOT,
                mutated,
                fixture["bundle"].instance,
                fixture["owners"],
            )

    def test_stage_identity_mutation_is_rejected(self) -> None:
        fixture = stream1_stage1_fixture()
        stage = copy.deepcopy(fixture["evidence"][0])
        raw = audit.read_csv(fixture["run_dir"] / "raw_runs.csv")[0]
        audit.assert_stage_identity(stage, raw, fixture["batch"], 1, "cooperative", 1)
        stage["arm"] = "independent"
        with self.assertRaisesRegex(audit.AuditFailure, "evidence arm"):
            audit.assert_stage_identity(stage, raw, fixture["batch"], 1, "cooperative", 1)

    def test_dynamic_added_field_mutation_is_rejected(self) -> None:
        fixture = stream1_stage1_fixture()
        stage = copy.deepcopy(fixture["evidence"][0])
        raw = audit.read_csv(fixture["run_dir"] / "raw_runs.csv")[0]
        dynamic_ids = set(stage["dynamic_added_customer_ids"])
        dynamic_cross = tuple(stage["dynamic_added_cross_site_customer_ids"])
        audit.assert_dynamic_cross_site_fields(
            stage, raw, dynamic_ids, dynamic_cross, "stage1"
        )
        stage["dynamic_added_customer_ids"] = stage["dynamic_added_customer_ids"][:-1]
        with self.assertRaisesRegex(audit.AuditFailure, "dynamic-added customer IDs"):
            audit.assert_dynamic_cross_site_fields(
                stage, raw, dynamic_ids, dynamic_cross, "stage1"
            )

    def test_cross_site_service_depot_mutation_is_rejected(self) -> None:
        fixture = stream1_stage1_fixture()
        stage = fixture["evidence"][0]
        expected = list(audit._cross_site_services(
            stage["solution"]["routes"], fixture["effective"], fixture["owners"]
        ))
        self.assertTrue(expected)
        audit.assert_cross_site_annotation(
            stage["solution"]["cross_site_services"], expected, "stage1"
        )
        mutated = copy.deepcopy(stage["solution"]["cross_site_services"])
        mutated[0]["served_by_depot_id"] = (
            "D1" if mutated[0]["served_by_depot_id"] == "D0" else "D0"
        )
        with self.assertRaisesRegex(audit.AuditFailure, "cross-site annotation"):
            audit.assert_cross_site_annotation(mutated, expected, "stage1")

    def test_locked_action_deletion_is_rejected(self) -> None:
        fixture = stream1_stage1_fixture()
        stage = fixture["evidence"][0]
        audit.assert_locked_actions_match(
            fixture["cut"].locked_charging_actions,
            stage["locked_charging_actions"],
            stage["locked_charging_actions_sha256"],
            "stage1",
        )
        mutated = copy.deepcopy(stage["locked_charging_actions"][:-1])
        with self.assertRaisesRegex(audit.AuditFailure, "locked charging actions"):
            audit.assert_locked_actions_match(
                fixture["cut"].locked_charging_actions,
                mutated,
                audit.canonical_sha256(mutated),
                "stage1",
            )

    def test_decision_event_count_mutation_is_rejected(self) -> None:
        rows = []
        for arm in audit.EXPECTED_ARMS:
            for seed in audit.EXPECTED_STREAMS:
                rows.append({
                    "arm": arm,
                    "event_count": str(audit.EXPECTED_EVENT_COUNT),
                    "applied_event_ids": ";".join(
                        f"{arm}-{seed}-{index}"
                        for index in range(audit.EXPECTED_EVENT_COUNT)
                    ),
                    "ignored_locked_event_ids": "",
                })
        decision = {
            "applied_event_count": audit.EXPECTED_EVENT_COUNT * 10,
            "locked_late_event_count": 0,
        }
        audit.validate_decision_event_counts(decision, rows)
        decision["applied_event_count"] -= 1
        with self.assertRaisesRegex(audit.AuditFailure, "decision applied-event count"):
            audit.validate_decision_event_counts(decision, rows)


class PathAndWorkloadTests(unittest.TestCase):
    def test_recorded_path_may_not_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root.parent / "outside-e7-test.txt"
            outside.write_text("x", encoding="utf-8")
            try:
                with self.assertRaisesRegex(audit.AuditFailure, "escapes repository"):
                    audit.safe_recorded_path(root, "../outside-e7-test.txt")
            finally:
                outside.unlink(missing_ok=True)

    def test_workload_ledger_detects_same_customer_with_changed_quantity(self) -> None:
        left = tiny_instance()
        right_nodes = [
            replace(node, demand=31.0) if node.node_id == "C3" else node
            for node in left.nodes
        ]
        right = audit.rebuild_instance(left, right_nodes)
        left_ledger = audit.workload_ledger(left)
        right_ledger = audit.workload_ledger(right)
        self.assertNotEqual(left_ledger, right_ledger)
        self.assertEqual(set(left_ledger), set(right_ledger))


if __name__ == "__main__":
    unittest.main()
