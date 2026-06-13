from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from setp_solver.reporting.figures import charging_period_shares
from setp_solver.reporting.samples import build_figure_sources
from setp_solver.reporting.schema import read_records, write_records
from setp_solver.reporting.tables import (
    TABLE_SPECS,
    table_t1_instances,
    table_t3_algorithm_comparison,
    table_t7_carbon_sensitivity,
    write_table_rows,
)


class ReportingOutputTest(unittest.TestCase):
    def test_table_csv_uses_chinese_headers_and_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t1.csv"
            write_table_rows(
                "T1",
                path,
                [
                    {
                        "instance": "算例一",
                        "customers": 3,
                        "depots": 1,
                        "stations": 2,
                        "total_demand_kg": "12.0",
                        "window_width_h": "4.0",
                        "deleted_customers": 0,
                        "isolated": "关闭",
                        "gamma_slots": 48,
                        "anchor_day": "2025-11-13 UTC",
                    }
                ],
            )

            raw = path.read_bytes()
            first_line = raw.decode("utf-8-sig").splitlines()[0]
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(first_line, "算例,客户数,车场,站点,总需求kg,窗宽h,删除客户数,孤立客户,$\\gamma$槽,锚定日")

    def test_booktabs_reads_chinese_header_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t1.csv"
            write_table_rows(
                "T1",
                path,
                [
                    {
                        "instance": "算例一",
                        "customers": 3,
                        "depots": 1,
                        "stations": 2,
                        "total_demand_kg": "12.0",
                        "window_width_h": "4.0",
                        "deleted_customers": 0,
                        "isolated": "关闭",
                        "gamma_slots": 48,
                        "anchor_day": "2025-11-13 UTC",
                    }
                ],
            )

            tex = table_t1_instances(path)
            self.assertIn("算例 & 客户数", tex)
            self.assertIn("算例一 & 3 & 1 & 2", tex)
            self.assertNotIn("instance", tex)

    def test_w0_csv_uses_chinese_headers_and_can_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "records.csv"
            json_path = Path(tmp) / "records.json"
            write_records(
                [
                    {
                        "experiment_id": "exp-1",
                        "instance": "算例一",
                        "algorithm": "算法一",
                        "feasible": True,
                        "evals": 12,
                    }
                ],
                csv_path,
                json_path,
            )

            raw = csv_path.read_bytes()
            first_line = raw.decode("utf-8-sig").splitlines()[0]
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertTrue(first_line.startswith("schema版本,实验ID,算例,算法"))

            rows = read_records(csv_path)
            self.assertEqual(rows[0]["experiment_id"], "exp-1")
            self.assertEqual(rows[0]["feasible"], "是")

    def test_style_notes_records_reference_templates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        notes = root / "src" / "setp_solver" / "reporting" / "STYLE_NOTES.md"
        text = notes.read_text(encoding="utf-8")
        self.assertIn("陈婉茹2023", text)
        self.assertIn("Soriano2023", text)
        self.assertIn("Shi2025", text)
        self.assertIn("峰/平/谷按当日 $\\gamma$ 三分位划分", text)

    def test_t3_chen_table5_grouped_algorithm_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t3.csv"
            path.write_text(
                "\ufeff算例,n/d,参考最优(来源算法),ALNS|相对已观测最优偏差\\%,ALNS|时间s,VNS|相对已观测最优偏差\\%,VNS|时间s\n"
                "I1,100/2,100.000 (ALNS),0.00,1.20,2.50,1.40\n"
                "Average,,,0.00,1.20,2.50,1.40\n"
                "达到最优的算例数,,,1,,0,\n",
                encoding="utf-8",
            )

            tex = table_t3_algorithm_comparison(path)
            self.assertIn("\\multicolumn{2}{c}{ALNS}", tex)
            self.assertIn("\\cmidrule", tex)
            self.assertIn("相对已观测最优偏差\\%", tex)
            self.assertIn("Average", tex)
            self.assertIn("达到最优的算例数", tex)

    def test_t5_chen_table8_columns(self) -> None:
        headers = [header for _, header in TABLE_SPECS["T5"]]
        self.assertEqual(headers, ["消融层级", "最优", "均值", "std", "总碳kg", "相对完整模型变化\\%", "电车数", "跨场数", "$\\min\\Pi/\\Pi^0$"])

    def test_t7_chen_table10_quota_blocks_allow_negative_trading_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t7.csv"
            path.write_text(
                "\ufeff碳价,配额0.85|总成本,配额0.85|油耗,配额0.85|电费,配额0.85|碳交易成本,配额0.85|总碳,配额0.85|电车数,配额1.15|总成本,配额1.15|油耗,配额1.15|电费,配额1.15|碳交易成本,配额1.15|总碳,配额1.15|电车数\n"
                "0.0,6200,420,180,0.00,1900,12,6100,410,170,−10.50,1880,13\n",
                encoding="utf-8",
            )

            tex = table_t7_carbon_sensitivity(path)
            self.assertIn("\\multicolumn{6}{c}{配额0.85}", tex)
            self.assertIn("\\multicolumn{6}{c}{配额1.15}", tex)
            self.assertIn("−10.50", tex)
            self.assertIn("\\cmidrule", tex)

    def test_f4_period_shares_use_gamma_tertiles(self) -> None:
        rows = [
            {"scenario": "朴素充电", "gamma_gco2_per_kwh": "10", "total_kwh": "30"},
            {"scenario": "朴素充电", "gamma_gco2_per_kwh": "20", "total_kwh": "30"},
            {"scenario": "朴素充电", "gamma_gco2_per_kwh": "30", "total_kwh": "40"},
            {"scenario": "碳感知充电", "gamma_gco2_per_kwh": "10", "total_kwh": "80"},
            {"scenario": "碳感知充电", "gamma_gco2_per_kwh": "20", "total_kwh": "10"},
            {"scenario": "碳感知充电", "gamma_gco2_per_kwh": "30", "total_kwh": "10"},
        ]
        shares = charging_period_shares(rows)
        self.assertEqual(shares["朴素充电"], {"谷": 0.30, "平": 0.30, "峰": 0.40})
        self.assertEqual(shares["碳感知充电"], {"谷": 0.80, "平": 0.10, "峰": 0.10})

    def test_f6_source_uses_cost_ratio_to_independent_operation(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            sources = build_figure_sources(root, root / "solver" / "reports", Path(tmp))
            rows = sources["F6"].read_text(encoding="utf-8-sig").splitlines()
        self.assertIn("总成本/独立运营总成本", rows[0])
        self.assertIn("独立运营总成本", rows[0])


if __name__ == "__main__":
    unittest.main()
