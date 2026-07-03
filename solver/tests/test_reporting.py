from __future__ import annotations

import csv
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from setp_solver.reporting.figures import CARBON_MAIN_PRICE_GBP_PER_TONNE, carbon_stress_points, charging_period_shares, figure_f4_48slot_charging
from setp_solver.reporting.registry import get_runner
import setp_solver.reporting.runner  # noqa: F401 - registers reporting runners
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
                        "isolated_customer_share_pct": "0.0",
                        "gamma_slots": 48,
                        "anchor_day": "2025-11-13 UTC",
                    }
                ],
            )

            raw = path.read_bytes()
            first_line = raw.decode("utf-8-sig").splitlines()[0]
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(first_line, "算例,客户数,车场数,充电站数,总需求/kg,平均时间窗宽/h,孤立客户占比/\\%,$\\gamma$槽数,碳强度锚定日")

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
                        "isolated_customer_share_pct": "0.0",
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
            self.assertIn("算例 & n/d & 算法 & 参考最优", tex)
            self.assertIn("I1 & 100/2 & ALNS", tex)
            self.assertIn("I1 & 100/2 & VNS", tex)
            self.assertIn("偏差\\%", tex)
            self.assertIn("Average", tex)
            self.assertIn("达到最优的算例数", tex)

    def test_t3_standardizes_algorithm_display_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t3.csv"
            path.write_text(
                "\ufeff算例,n/d,参考最优(来源算法),ALNS-Wouda|相对已观测最优偏差\\%,ALNS-Wouda|时间s,scikit-opt-SA|相对已观测最优偏差\\%,scikit-opt-SA|时间s\n"
                "I1,100/2,100.000 (ALNS-Wouda),0.00,1.20,9.50,1.40\n",
                encoding="utf-8",
            )

            tex = table_t3_algorithm_comparison(path)

        self.assertIn("I1 & 100/2 & ALNS", tex)
        self.assertIn("I1 & 100/2 & SA", tex)
        self.assertNotIn("ALNS-Wouda &", tex)
        self.assertNotIn("scikit-opt-SA &", tex)

    def test_t5_chen_table8_columns(self) -> None:
        headers = [header for _, header in TABLE_SPECS["T5"]]
        self.assertEqual(headers, ["消融层级", "成本均值±std/£", "相对完整模型Δ/\\%", "显著性", "总排放/kgCO$_2$e", "电车路线数", "跨场服务数", "最小公平比"])

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

    def test_f4_renders_new_formal_48_slot_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "f4.csv"
            rows = ["scenario,slot_index,horizon_second_start,gamma_gco2_per_kwh,depot_kwh,station_kwh,other_kwh,total_kwh"]
            for scenario in ("naive_return_charge", "carbon_aware"):
                for slot in range(48):
                    gamma = 120 + (slot % 24) * 6
                    kwh = 0.0
                    if scenario == "naive_return_charge" and slot in {18, 19, 20}:
                        kwh = 20.0
                    if scenario == "carbon_aware" and slot in {4, 5, 6}:
                        kwh = 20.0
                    rows.append(f"{scenario},{slot},{slot * 1800},{gamma},0,0,0,{kwh}")
            source.write_text("\n".join(rows) + "\n", encoding="utf-8")

            pdf, png = figure_f4_48slot_charging(source, Path(tmp) / "f4")

            self.assertGreater(pdf.stat().st_size, 1000)
            self.assertGreater(png.stat().st_size, 1000)

    def test_f5b_carbon_stress_converts_factor_to_price_axis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            means = Path(tmp) / "means.csv"
            seeds = Path(tmp) / "seeds.csv"
            means.write_text(
                "carbon_price,total_carbon_kg,ev_count\n"
                "32,1086.020,57.2\n"
                "0.831,1293.142,50.6\n",
                encoding="utf-8",
            )
            seeds.write_text(
                "seed,carbon_price,total_carbon_kg\n"
                "1,32,1080\n"
                "2,32,1090\n"
                "1,0.831,1290\n"
                "2,0.831,1300\n",
                encoding="utf-8",
            )

            points = carbon_stress_points(means, seeds)

        self.assertEqual([point["factor"] for point in points], [0.831, 32.0])
        self.assertAlmostEqual(points[0]["price_gbp_per_tonne"], 0.831 * CARBON_MAIN_PRICE_GBP_PER_TONNE)
        self.assertAlmostEqual(points[1]["price_gbp_per_tonne"], 1610.88)

    def test_f5b_carbon_stress_uses_sample_standard_deviation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            means = Path(tmp) / "means.csv"
            seeds = Path(tmp) / "seeds.csv"
            means.write_text("carbon_price,total_carbon_kg,ev_count\n1,1305.473,49.6\n", encoding="utf-8")
            seeds.write_text(
                "seed,carbon_price,total_carbon_kg\n"
                "1,1,10\n"
                "2,1,20\n"
                "3,1,30\n",
                encoding="utf-8",
            )

            points = carbon_stress_points(means, seeds)

        self.assertAlmostEqual(points[0]["carbon_std"], 10.0)
        self.assertEqual(points[0]["carbon_mean"], 1305.473)

    def test_f5b_carbon_stress_accepts_price_factor_diagnostics_without_carbon_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            means = Path(tmp) / "means.csv"
            seeds = Path(tmp) / "diagnostics.csv"
            means.write_text("carbon_price,total_carbon_kg,ev_count\n0.831,1293.142,50.6\n", encoding="utf-8")
            seeds.write_text(
                "seed,price_factor,quota_factor,objective_carbon_price,actual_evals,feasible\n"
                "1,0.831,0.8,0.04183254,16006,是\n",
                encoding="utf-8",
            )

            points = carbon_stress_points(means, seeds)

        self.assertEqual(points[0]["factor"], 0.831)
        self.assertEqual(points[0]["carbon_std"], 0.0)

    def test_f6_source_uses_cost_ratio_to_independent_operation(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            sources = build_figure_sources(root, root / "solver" / "reports", Path(tmp))
            rows = sources["F6"].read_text(encoding="utf-8-sig").splitlines()
        self.assertIn("总成本/独立运营总成本", rows[0])
        self.assertIn("独立运营总成本", rows[0])

    def test_design_templates_runner_outputs_mock_only_package(self) -> None:
        root = Path(__file__).resolve().parents[2]
        runner = get_runner("design-templates")
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "design_templates"
            args = type("Args", (), {"repo_root": str(root), "output_dir": str(output_dir)})()

            result = runner(args)

            self.assertTrue((output_dir / "DATA_CONTRACT.md").exists())
            self.assertTrue((output_dir / "design_preview.tex").exists())
            self.assertTrue((output_dir / "tables" / "t4_solution_decomposition.tex").exists())
            self.assertTrue((output_dir / "figures" / "figure_f7_dynamic_timeline.pdf").exists())
            self.assertTrue((output_dir / "figures" / "figure_f5_carbon_response.pdf").exists())
            self.assertFalse((output_dir / "figures" / "figure_f5_carbon_heatmap.pdf").exists())
            self.assertNotIn("formal", "\n".join(str(path) for path in result["mock_data"].values()))

            contract = (output_dir / "DATA_CONTRACT.md").read_text(encoding="utf-8")
            self.assertIn("样例数据/非实验结果", contract)
            self.assertIn("F7 动态时间线", contract)
            self.assertIn("直接排放（燃油）", contract)
            self.assertIn("终值箱线图", contract)
            self.assertIn("燃油车同色实线", contract)
            self.assertIn("电动车同色虚线", contract)
            self.assertIn("黑色描边", contract)
            t4 = (output_dir / "tables" / "t4_solution_decomposition.tex").read_text(encoding="utf-8")
            self.assertIn("仅油车", t4)
            self.assertIn("混合", t4)
            self.assertIn("kgCO$_2$e", t4)
            self.assertNotIn("kgCO2e", t4)
            self.assertNotIn("source_seed", t4)
            self.assertNotIn("cv_only total_cost", t4)

            expected_notes = {
                "t1_instances.tex": "scenario manifest",
                "t3_algorithm_comparison.tex": "Wilcoxon",
                "t4_solution_decomposition.tex": "同预算独立重优化",
                "t5_ablation.tex": "不得靠表格掩饰",
                "t6_two_layer_carbon.tex": "仅油车重优化基线",
                "t7_carbon_sensitivity.tex": "不设配额轴",
                "t8_fairness_threshold.tex": "自然比值",
                "t9_dynamic.tex": "守恒审计",
            }
            for filename, snippet in expected_notes.items():
                text = (output_dir / "tables" / filename).read_text(encoding="utf-8")
                self.assertIn("样例数据/非实验结果", text)
                self.assertIn(snippet, text)
                self.assertIn(snippet, contract)
                self.assertIsNone(re.search(r"\d+\.\d{4,}", text))

            t3 = (output_dir / "tables" / "t3_algorithm_comparison.tex").read_text(encoding="utf-8")
            self.assertIn("\\midrule\n达优次数", t3)
            self.assertIn("平均偏差", t3)

            with (output_dir / "mock_data" / "t9_dynamic.csv").open(newline="", encoding="utf-8-sig") as handle:
                t9_rows = list(csv.DictReader(handle))
            self.assertEqual(len(t9_rows), 10)

            stage_csv = output_dir / "mock_data" / "t9_appendix_stage_detail.csv"
            self.assertTrue(stage_csv.exists())
            with stage_csv.open(newline="", encoding="utf-8-sig") as handle:
                stage_rows = list(csv.DictReader(handle))
            self.assertEqual(
                list(stage_rows[0]),
                [
                    "stage",
                    "trigger_time_h",
                    "event_counts",
                    "frozen_route_count",
                    "stage_cost",
                    "cumulative_cost",
                    "cumulative_carbon_kg",
                    "stage_min_fairness_ratio",
                    "stage_cross_site_customers",
                    "stage_low_carbon_charge_share_pct",
                ],
            )
            self.assertTrue((output_dir / "tables" / "t9_appendix_stage_detail.tex").exists())
            preview = (output_dir / "design_preview.tex").read_text(encoding="utf-8")
            self.assertIn("附录", preview)
            self.assertIn("t9_appendix_stage_detail.tex", preview)

            with (output_dir / "mock_data" / "f7_dynamic_timeline.csv").open(newline="", encoding="utf-8-sig") as handle:
                f7_rows = list(csv.DictReader(handle))
            self.assertGreaterEqual(len({row["vehicle_id"] for row in f7_rows}), 4)
            self.assertGreaterEqual(len({row["event_type"] for row in f7_rows if row["event_type"]}), 3)
            self.assertIn("event_time_h", f7_rows[0])


if __name__ == "__main__":
    unittest.main()
