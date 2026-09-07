"""碳限额与交易（免费配额 + 买卖）杠杆的单元核对——2026-09-06。

两件事：

1. **数学**：配额 Q 只平移碳成本。同一个解在 Q=0 与 Q=200 下，除
   ``cost_carbon`` / ``total_cost`` / ``carbon_quota_kg`` 之外的每一个成本与
   排放字段**逐位相同**；``cost_carbon`` 恰等于 ``(E_total - Q) * P``；总成本
   之差等于 ``-P * Q``（浮点残差另报，不谎称逐位——``(E-Q)*P - E*P`` 在浮点
   下不必然逐位等于 ``-Q*P``）。
2. **接线**：``run_problem_hgs_private_technical.py`` 的 ``--carbon-quota-kg``
   经 ``_build_context`` → ``_build_saved_suite_context`` →
   ``_suite_context_from_built`` 三层透传，最终落到评价上下文的
   ``carbon_quota_kg``。

出处：``solver/src/setp_solver/cost.py:230``
（``cost_carbon = (e_total - quota) * carbon_price``，线性、允许为负）。
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from setp_solver.cost import evaluate

from solver.tests.test_cost import (
    LINEAR_CHINA_TEST_PRICES,
    _toy_instance,
    _toy_solution,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
QUOTA_ONLY_KEYS = {"cost_carbon", "total_cost", "carbon_quota_kg"}


class CarbonQuotaShiftsOnlyTheCarbonCost(unittest.TestCase):
    """Q 只平移碳成本这一项，别的账一动不动。"""

    def _breakdown(self, quota_kg: float) -> dict:
        return evaluate(
            _toy_solution(energy_kwh=20.0),
            _toy_instance(),
            [{"horizon_second_start": 0.0, "actual_gco2_per_kwh": 500.0}],
            LINEAR_CHINA_TEST_PRICES,
            carbon_quota_kg=quota_kg,
        )

    def test_every_other_field_is_bit_for_bit_identical(self) -> None:
        zero = self._breakdown(0.0)
        quota = self._breakdown(200.0)
        self.assertEqual(set(zero), set(quota))
        for key in sorted(set(zero) - QUOTA_ONLY_KEYS):
            with self.subTest(key=key):
                self.assertEqual(
                    zero[key], quota[key], f"{key} moved when only the quota changed"
                )
        self.assertEqual(zero["carbon_quota_kg"], 0.0)
        self.assertEqual(quota["carbon_quota_kg"], 200.0)

    def test_carbon_cost_is_exactly_the_quota_formula(self) -> None:
        price = LINEAR_CHINA_TEST_PRICES.carbon_price
        for quota_kg in (0.0, 200.0):
            with self.subTest(quota_kg=quota_kg):
                result = self._breakdown(quota_kg)
                self.assertEqual(
                    result["cost_carbon"],
                    (result["E_total"] - quota_kg) * price,
                )

    def test_total_cost_shifts_by_minus_price_times_quota(self) -> None:
        price = LINEAR_CHINA_TEST_PRICES.carbon_price
        zero = self._breakdown(0.0)
        quota = self._breakdown(200.0)
        delta = quota["total_cost"] - zero["total_cost"]
        expected = -price * 200.0
        # 浮点残差，不是"逐位"：见模块文档字符串。
        self.assertAlmostEqual(delta, expected, delta=1e-9)
        self.assertLess(quota["cost_carbon"], 0.0, "200 kg 配额下应当是卖方")

    def test_generous_quota_only_ever_sells_never_clamps(self) -> None:
        """线性、无 ``max(0, ·)``：这正是"配额不改变任何决策"的数学原因。"""

        price = LINEAR_CHINA_TEST_PRICES.carbon_price
        low = self._breakdown(300.0)
        high = self._breakdown(500.0)
        self.assertAlmostEqual(
            high["total_cost"] - low["total_cost"], -price * 200.0, delta=1e-9
        )


class CarbonQuotaRunnerWiring(unittest.TestCase):
    """``--carbon-quota-kg`` 三层透传到评价上下文。"""

    @classmethod
    def setUpClass(cls) -> None:
        scripts = REPO_ROOT / "solver/scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        try:
            import run_problem_hgs_private_technical as runtime
        except Exception as error:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(f"private runner unavailable: {error}")
        package_root = (
            REPO_ROOT / "data/ChinaInstances/china81_final_suite_v2_20260815"
        )
        if not package_root.is_dir():
            raise unittest.SkipTest(f"sealed instance package missing: {package_root}")
        cls.runtime = runtime
        cls.fleet = runtime.FLEET_PARAMETER_CLASSES["endogenous"]

    def _context(self, quota_kg: float | None):
        _bundle, _initial, _neutral, context = self.runtime._build_context(
            REPO_ROOT,
            self.runtime.DEPOT_SEARCH_INSTANCE_ID,
            fleet_parameters=self.fleet,
            carbon_quota_kg=quota_kg,
        )
        return context

    def test_default_keeps_the_instance_quota(self) -> None:
        self.assertEqual(self.runtime.DEFAULT_CARBON_QUOTA_KG, 0.0)
        self.assertEqual(self._context(None).carbon_quota_kg, 0.0)

    def test_override_reaches_the_evaluation_context(self) -> None:
        for quota_kg in (0.0, 200.0, 500.0):
            with self.subTest(quota_kg=quota_kg):
                self.assertEqual(
                    self._context(quota_kg).carbon_quota_kg, float(quota_kg)
                )

    def test_quota_does_not_disturb_the_ev_premium_lever(self) -> None:
        context = self._context(200.0)
        self.assertEqual(context.carbon_quota_kg, 200.0)
        self.assertEqual(context.ev_daily_fixed_premium_cny, 100.0)

    def test_command_line_flag_is_documented_by_the_runner_itself(self) -> None:
        """真调 CLI 的 --help，不自己复刻一个 parser。"""

        result = self._cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("--carbon-quota-kg", result.stdout)

    def test_negative_quota_is_refused_by_the_runner(self) -> None:
        result = self._cli(
            str(Path(self._tmpdir) / "never_created"),
            "--carbon-quota-kg",
            "-1",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "--carbon-quota-kg must be finite and non-negative",
            result.stdout + result.stderr,
        )
        self.assertFalse((Path(self._tmpdir) / "never_created").exists())

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _cli(self, *argv: str):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [
                "solver/src",
                "third_party/setp_hgs_kernel",
                "models/src",
                "solver/scripts",
            ]
        )
        return subprocess.run(
            [
                sys.executable,
                "solver/scripts/run_problem_hgs_private_technical.py",
                *argv,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
