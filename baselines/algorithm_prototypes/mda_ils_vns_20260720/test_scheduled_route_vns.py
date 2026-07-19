"""Focused tests for the frozen late-stage VNS schedule."""

import unittest

from scheduled_route_vns import should_run_scheduled_vns


class ScheduledRouteVNSTest(unittest.TestCase):
    def test_foundation_never_schedules(self) -> None:
        self.assertFalse(should_run_scheduled_vns(1000, 1.0, None))

    def test_schedule_waits_until_seventy_percent(self) -> None:
        self.assertFalse(should_run_scheduled_vns(500, 0.5, 500))
        self.assertTrue(should_run_scheduled_vns(1000, 0.7, 500))

    def test_schedule_requires_period_boundary(self) -> None:
        self.assertFalse(should_run_scheduled_vns(999, 1.0, 500))
        self.assertTrue(should_run_scheduled_vns(1000, 1.0, 500))


if __name__ == "__main__":
    unittest.main()
