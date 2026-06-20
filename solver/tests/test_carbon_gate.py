from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from setp_solver.cost import (
    CARBON_N_SLOTS,
    CARBON_ORIGIN_OFFSET_SECONDS,
    CARBON_ORIGIN_UTC,
    CARBON_SLOT_SECONDS,
    carbon_profile_row_for_slot,
    carbon_slot_index,
)
from setp_solver.instance_loader import load_carbon_profile


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_ROOT = REPO_ROOT / "models" / "data_bundle" / "generated_instances"
Q1_FIXTURE_DIR = GENERATED_ROOT / "E-UK100_01__d2_s3_seed1_24h_20251113"


def _real_gate_fixture_dir() -> Path:
    preferred = GENERATED_ROOT / "MD-UK50-01-v3"
    fallback = GENERATED_ROOT / "verify_20251113"
    return preferred if preferred.exists() else fallback


def _ref_slot(t_second: float) -> int:
    raw = math.floor((float(t_second) - CARBON_ORIGIN_OFFSET_SECONDS) / CARBON_SLOT_SECONDS)
    return max(0, min(CARBON_N_SLOTS - 1, int(raw)))


def _ref_slot_n(t_second: float, n_slots: int) -> int:
    raw = math.floor(float(t_second) / CARBON_SLOT_SECONDS)
    return max(0, min(n_slots - 1, int(raw)))


class CarbonGateTests(unittest.TestCase):
    # v2026-06-11: B1 anchor gate for paper_main.tex B-full charging time grid.
    def test_carbon_slot_anchor_matches_reference_samples(self) -> None:
        self.assertEqual(CARBON_ORIGIN_UTC.isoformat(), "2025-11-13T08:00:00+00:00")
        samples = [0.0, 1799.0, 1800.0, 1801.0, 30600.0, 32399.0, 32400.0, 37400.0]
        for t_second in samples:
            self.assertEqual(carbon_slot_index(t_second), _ref_slot(t_second), msg=f"t={t_second}")

    # v2026-06-11: B1 gamma round-trip gate against a real generated carbon_profile.csv, not a mock.
    def test_real_fixture_gamma_round_trip_matches_profile(self) -> None:
        fixture = _real_gate_fixture_dir()
        profile = load_carbon_profile(fixture / "carbon_profile.csv")
        self.assertEqual(len(profile), CARBON_N_SLOTS)
        for slot_index, expected in enumerate(profile):
            actual = carbon_profile_row_for_slot(profile, slot_index)
            self.assertEqual(actual["actual_gco2_per_kwh"], expected["actual_gco2_per_kwh"], msg=f"slot={slot_index}")

    # v2026-06-11: B1 unit gate checks generated time windows are seconds on the 2025-11-13 schedule.
    def test_real_fixture_time_window_scale_is_seconds(self) -> None:
        fixture = _real_gate_fixture_dir()
        data = json.loads((fixture / "instance.json").read_text(encoding="utf-8"))
        max_due = max(float(node.get("due_time", node.get("l", 0.0))) for node in data["nodes"])
        span_hours = max_due / 3600.0
        self.assertGreaterEqual(span_hours, 1.0)
        self.assertLessEqual(span_hours, 24.0)

    # v2026-06-11: B2 feasible-domain gate; depot return windows cap feasible charging before carbon-window end.
    def test_real_fixture_depot_return_deadline_makes_overflow_infeasible(self) -> None:
        fixture = _real_gate_fixture_dir()
        data = json.loads((fixture / "instance.json").read_text(encoding="utf-8"))
        depot_nodes = [node for node in data["nodes"] if str(node.get("node_type", "")).lower() == "d"]
        self.assertTrue(depot_nodes)
        return_deadline = max(float(node.get("due_time", node.get("l", 0.0))) for node in depot_nodes)
        window_end = CARBON_N_SLOTS * CARBON_SLOT_SECONDS
        self.assertLessEqual(return_deadline, window_end + 1e-6)

    def test_q1_24h_fixture_gamma_anchor_samples_and_b2_safe(self) -> None:
        # v2026-06-12: Q1 gate for 2025-11-13 midnight anchor, 48 half-hour slots, and shifted depot deadline.
        profile = load_carbon_profile(Q1_FIXTURE_DIR / "carbon_profile.csv")
        data = json.loads((Q1_FIXTURE_DIR / "instance.json").read_text(encoding="utf-8"))

        self.assertEqual(len(profile), 48)
        self.assertEqual(profile[0]["datetime_utc"], "2025-11-13T00:00:00+00:00")
        self.assertEqual(profile[-1]["datetime_utc"], "2025-11-13T23:30:00+00:00")
        self.assertEqual(profile[-1]["horizon_second_start"], 84600.0)
        for t_second in [0.0, 1799.0, 1800.0, 28799.0, 28800.0, 61199.0, 61200.0, 86399.0]:
            slot = carbon_slot_index(t_second, n_slots=len(profile))
            self.assertEqual(slot, _ref_slot_n(t_second, len(profile)), msg=f"t={t_second}")
            self.assertEqual(carbon_profile_row_for_slot(profile, slot)["actual_gco2_per_kwh"], profile[slot]["actual_gco2_per_kwh"])

        depots = [node for node in data["nodes"] if str(node.get("node_type", "")).lower() == "d"]
        return_deadline = max(float(node["due_time"]) for node in depots)
        self.assertEqual(return_deadline, 61200.0)
        self.assertLessEqual(return_deadline, len(profile) * CARBON_SLOT_SECONDS)


if __name__ == "__main__":
    unittest.main()
