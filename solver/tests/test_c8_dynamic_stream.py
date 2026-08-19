"""C8-1 stream contract tests.

These are additive tests.  They do not alter the existing test suite or any
protected evaluator file.
"""

from __future__ import annotations

import csv
import hashlib
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "solver/src"))
sys.path.insert(0, str(REPO_ROOT / "third_party/setp_hgs_kernel"))
sys.path.insert(0, str(REPO_ROOT / "solver/scripts"))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    ENDOGENOUS_FLEET_PARAMETERS,
    _build_context,
    _policy,
)
from setp_solver.algorithms.problem_hgs.dynamic_insertion import (  # noqa: E402
    DynamicInsertionOperator,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
)
from setp_solver.c8_dynamic_stream import (  # noqa: E402
    C8_BASE_INSTANCE_ID,
    C8_DYNAMIC_ORDER_COUNT,
    C8Protocol,
    _trigger_batches,
    generate_c8_stream,
    load_c8_stream,
    overlay_c8_bundle,
    package_content_sha256,
    package_file_hashes,
)


TARGET_DIR = (
    REPO_ROOT
    / "data/ChinaInstances/china81_final_suite_v2_20260815/instances"
    / C8_BASE_INSTANCE_ID
)


class C8DynamicStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle, cls.initial, _pi0, cls.context = _build_context(
            REPO_ROOT,
            C8_BASE_INSTANCE_ID,
            fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
        )
        with (TARGET_DIR / "orders.csv").open(
            newline="", encoding="utf-8-sig"
        ) as handle:
            cls.order_rows = list(csv.DictReader(handle))
        cls.source_hashes = package_file_hashes(TARGET_DIR)
        cls.source_hash = package_content_sha256(cls.source_hashes)

    def test_protocol_trigger_consumes_every_event_once(self) -> None:
        events = []
        for index, demand in enumerate((200.0, 320.0, 100.0), start=1):
            event = {
                "event_id": f"E{index}",
                "customer_id": f"C{index}",
                "event_type": "new_customer",
                "appearance_second": 28_800.0 + index * 100.0,
                "demand_kg": demand,
                "volume_m3": 1.0,
                "service_minutes": 5.0,
                "ready_second": 46_800.0,
                "due_second": 50_000.0,
                "shift_id": "PM",
                "home_depot_id": "D",
                "city": "beijing",
                "latitude": 0.0,
                "longitude": 0.0,
                "coordinate_proxy_customer_id": "C001",
                "demand_source_customer_id": "C001",
                "source_distribution": "test",
                "trigger_batch_index": 0,
                "trigger_second": 0.0,
                "trigger_cause": "",
                "direct_travel_second": 1.0,
                "direct_return_second": 1.0,
                "reveal_serviceable": True,
                "trigger_serviceable": True,
                "serviceability_reason": "PASS",
            }
            from setp_solver.c8_dynamic_stream import C8DynamicEvent

            events.append(C8DynamicEvent(**event))
        batches = _trigger_batches(events, C8Protocol())
        self.assertEqual(
            [event_id for batch in batches for event_id in batch.event_ids],
            ["E1", "E2", "E3"],
        )
        self.assertEqual(batches[0].cause, "demand_threshold")

    def test_generated_stream_is_deterministic_and_serviceable(self) -> None:
        first = generate_c8_stream(
            bundle=self.bundle,
            order_rows=self.order_rows,
            source_instance_dir=TARGET_DIR,
        )
        second = generate_c8_stream(
            bundle=self.bundle,
            order_rows=self.order_rows,
            source_instance_dir=TARGET_DIR,
        )
        self.assertEqual(first.stream_content_sha256, second.stream_content_sha256)
        self.assertEqual(first.seed, second.seed)
        self.assertEqual(len(first.events), C8_DYNAMIC_ORDER_COUNT)
        self.assertTrue(all(event.trigger_serviceable for event in first.events))
        self.assertEqual(first.source_instance_sha256, self.source_hash)
        self.assertNotIn("GZ-FS", first.base_instance_id)

    def test_overlay_is_in_memory_and_none_is_exact_noop(self) -> None:
        stream = generate_c8_stream(
            bundle=self.bundle,
            order_rows=self.order_rows,
            source_instance_dir=TARGET_DIR,
        )
        self.assertIs(overlay_c8_bundle(self.bundle, None), self.bundle)
        expanded = overlay_c8_bundle(self.bundle, stream)
        base_customers = sum(
            node.node_type.lower() == "c" for node in self.bundle.instance.nodes
        )
        expanded_customers = sum(
            node.node_type.lower() == "c" for node in expanded.instance.nodes
        )
        self.assertEqual(base_customers, 50)
        self.assertEqual(expanded_customers, 60)
        self.assertEqual(package_file_hashes(TARGET_DIR), self.source_hashes)

    def test_dynamic_operator_disabled_returns_same_object(self) -> None:
        evaluator = DutyFullEvaluator(self.context)
        evaluation = evaluator.evaluate(self.initial)
        policy = _policy(evaluator)
        result = DynamicInsertionOperator(enabled=False).apply(
            self.initial,
            evaluator=evaluator,
            charging_policy=policy,
            newly_revealed_customer_ids=(),
            current_evaluation=evaluation,
        )
        self.assertIs(result.individual, self.initial)
        self.assertIs(result.evaluation, evaluation)
        self.assertEqual(result.individual.fingerprint, self.initial.fingerprint)
        self.assertEqual(
            result.accounting.committed_sha256_before,
            result.accounting.committed_sha256_after,
        )


if __name__ == "__main__":
    unittest.main()
