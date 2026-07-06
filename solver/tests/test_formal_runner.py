from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import infer_customer_home_depots
from setp_solver.profit import calculate_depot_profits
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.search import dynamic as dynamic_module
from setp_solver.search.dynamic import (
    RollingParameters,
    RollingPolicyDecision,
    StagePlanResult,
    generate_dynamic_events,
    myopic_rolling_policy,
    run_rolling_reoptimization,
    _solution_for_customer_subset,
)
from setp_solver.search import formal_runner
from setp_solver.search.formal_runner import (
    ResumeLedger,
    RunKey,
    _derive_carbon_profile,
    _derive_cross_site_services,
    _e2_final_rows,
    _e3_table_rows,
    _e3_variant_specs,
    _f2_final_rows,
    _flatten_run_row,
    _prices_with_carbon_price_factor,
    _resolve_e2_algorithms,
    run_e0_gate,
    run_e4_carbon_sensitivity,
    run_e7_dynamic,
    run_e5_formal,
)
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import CandidateRunResult


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "models" / "data_bundle" / "generated_instances" / "verify_20251113"


class FormalRunnerTests(unittest.TestCase):
    # v2026-06-12: Z2-Z4 long runs must be restartable without repeating completed work.
    def test_resume_ledger_skips_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ResumeLedger(Path(tmp) / "manifest.json")
            key = RunKey("E2", "fixture", "ALNS-Wouda", 1, "smoke")
            calls = {"count": 0}

            def run_once() -> dict[str, int]:
                calls["count"] += 1
                return {"value": 7}

            first = ledger.run(key, run_once)
            second = ledger.run(key, run_once)

            self.assertEqual(first["status"], "completed")
            self.assertTrue(second["skipped"])
            self.assertEqual(calls["count"], 1)

    # v2026-06-12: W2 formal runs must expose actual eval/time even when a stage wrapper records them outside result.
    def test_flatten_run_row_promotes_actual_eval_and_elapsed_fields(self) -> None:
        key = RunKey("E3", "L-main", "ALNS-Wouda", 2, "M4")
        row = {
            "status": "completed",
            "elapsed_seconds": 12.5,
            "skipped": False,
            "result": {"feasible": True, "evals": 1234, "best_cost": 99.0},
        }

        flat = _flatten_run_row(key, row)

        self.assertEqual(flat["actual_evals"], 1234)
        self.assertEqual(flat["actual_elapsed_seconds"], 12.5)
        self.assertEqual(flat["result"]["actual_evals"], 1234)
        self.assertEqual(flat["result"]["elapsed_seconds"], 12.5)

    # v2026-06-12: W2 E6 stores fairness-on/off subruns but the formal manifest still needs top-level actual evals.
    def test_flatten_run_row_sums_fairness_pair_evaluations(self) -> None:
        key = RunKey("E6", "L-main", "ALNS-Wouda", 1, "theta=1.00")
        row = {
            "status": "completed",
            "elapsed_seconds": 20.0,
            "skipped": False,
            "result": {
                "fairness_on": {"evaluations": 10},
                "fairness_off": {"evaluations": 12},
                "fairness_on_feasible": True,
            },
        }

        flat = _flatten_run_row(key, row)

        self.assertEqual(flat["actual_evals"], 22)
        self.assertEqual(flat["result"]["actual_evals"], 22)

    # v2026-06-13: R2 E6 top-level elapsed_seconds must not stay at 0 when nested
    # fairness-on/off runs recorded their own wall-clock times.
    def test_flatten_run_row_sums_fairness_pair_elapsed_seconds(self) -> None:
        key = RunKey("E6", "L-main", "ALNS-Wouda", 1, "theta=1.00")
        row = {
            "status": "completed",
            "elapsed_seconds": 0.0,
            "skipped": False,
            "result": {
                "fairness_on": {"evaluations": 10, "elapsed_seconds": 3.5},
                "fairness_off": {"evaluations": 12, "elapsed_seconds": 4.5},
                "fairness_on_feasible": True,
            },
        }

        flat = _flatten_run_row(key, row)

        self.assertEqual(flat["actual_elapsed_seconds"], 8.0)
        self.assertEqual(flat["result"]["elapsed_seconds"], 8.0)

    def test_parse_float_list_supports_theta_grid_cli(self) -> None:
        self.assertEqual(formal_runner._parse_float_list("0.80,0.85,1.10"), [0.8, 0.85, 1.1])
        self.assertIsNone(formal_runner._parse_float_list(""))

    def test_resolve_e2_algorithms_can_exclude_dr_alns(self) -> None:
        algorithms = _resolve_e2_algorithms(["ALNS-Wouda", "DR-ALNS", "scikit-opt-SA"], ["DR-ALNS"])

        self.assertEqual(algorithms, ["ALNS-Wouda", "scikit-opt-SA"])

    def test_e1_table_uses_best_feasible_seed_and_writes_seed_detail(self) -> None:
        run_rows = [
            {
                "variant": "mixed",
                "seed": 1,
                "status": "completed",
                "actual_evals": 10,
                "result": {
                    "feasible": True,
                    "best_cost": 110.0,
                    "violation_count": 0,
                    "metrics": {"total_cost": 110.0, "E_total": 20.0, "E_ev_indirect": 4.0},
                    "ev_routes": 1,
                    "cv_routes": 2,
                    "route_count": 3,
                },
            },
            {
                "variant": "mixed",
                "seed": 2,
                "status": "completed",
                "actual_evals": 10,
                "result": {
                    "feasible": True,
                    "best_cost": 100.0,
                    "violation_count": 0,
                    "metrics": {"total_cost": 100.0, "E_total": 10.0, "E_ev_indirect": 3.0},
                    "ev_routes": 2,
                    "cv_routes": 1,
                    "route_count": 3,
                },
            },
        ]

        table = formal_runner._e1_table_rows(run_rows)
        detail = formal_runner._e1_seed_detail_rows(run_rows)

        values = {row["metric"]: row["value"] for row in table}
        self.assertEqual(values["mixed total_cost"], 100.0)
        self.assertEqual(values["mixed source_seed"], 2)
        self.assertEqual(len(detail), 2)
        self.assertEqual({row["seed"] for row in detail}, {1, 2})

    # v2026-06-12: W2 T3 gaps use per-instance observed best and include Chen-style tail rows.
    def test_e2_final_rows_use_instance_local_reference_and_tail_rows(self) -> None:
        rows = [
            {
                "instance": "A",
                "algorithm": "Alg1",
                "seed": 1,
                "status": "completed",
                "result": {"feasible": True, "best_cost": 100.0, "elapsed_seconds": 10.0, "evals": 1000},
            },
            {
                "instance": "A",
                "algorithm": "Alg2",
                "seed": 1,
                "status": "completed",
                "result": {"feasible": True, "best_cost": 110.0, "elapsed_seconds": 20.0, "evals": 900},
            },
            {
                "instance": "B",
                "algorithm": "Alg1",
                "seed": 1,
                "status": "completed",
                "result": {"feasible": True, "best_cost": 1000.0, "elapsed_seconds": 30.0, "evals": 800},
            },
            {
                "instance": "B",
                "algorithm": "Alg2",
                "seed": 1,
                "status": "completed",
                "result": {"feasible": True, "best_cost": 900.0, "elapsed_seconds": 40.0, "evals": 700},
            },
        ]

        final_rows = _e2_final_rows(rows)

        row_a = next(row for row in final_rows if row["instance"] == "A")
        row_b = next(row for row in final_rows if row["instance"] == "B")
        average = next(row for row in final_rows if row["instance"] == "Average")
        best_count = next(row for row in final_rows if row["instance"] == "达优次数")

        self.assertEqual(row_a["reference_best"], 100.0)
        self.assertEqual(row_b["reference_best"], 900.0)
        self.assertEqual(row_a["Alg2|相对已观测最优偏差\\%"], 10.0)
        self.assertAlmostEqual(row_b["Alg1|相对已观测最优偏差\\%"], 11.111, places=3)
        self.assertEqual(average["Alg1|时间s"], 20.0)
        self.assertEqual(best_count["Alg1|相对已观测最优偏差\\%"], 1)

    # v2026-06-13: R2 T3 exposes actual evaluation counts so slow algorithms are
    # reported honestly instead of being silently compared under unequal budgets.
    def test_e2_final_rows_include_actual_evaluations(self) -> None:
        rows = [
            {
                "instance": "A",
                "algorithm": "Alg1",
                "seed": 1,
                "status": "completed",
                "actual_evals": 16000,
                "result": {"feasible": True, "best_cost": 100.0, "elapsed_seconds": 10.0, "evals": 16000},
            },
            {
                "instance": "A",
                "algorithm": "Alg1",
                "seed": 2,
                "status": "completed",
                "actual_evals": 8000,
                "result": {"feasible": True, "best_cost": 102.0, "elapsed_seconds": 12.0, "evals": 8000},
            },
        ]

        final_rows = _e2_final_rows(rows)

        self.assertEqual(final_rows[0]["Alg1|实际评估次数"], 12000)

    # v2026-06-13: R2 E2 new attempts must persist the best feasible solution
    # and its metrics; T4/F1 are derived from this payload.
    def test_run_algorithm_once_persists_solution_and_metrics(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        depot = _first_depot_id(bundle)
        customer = _first_customer_id(bundle)
        solution = Solution(routes=[Route("CV1", "cv", depot, [depot, customer, depot])])

        fake = CandidateRunResult(
            algorithm="Alg1",
            feasible=True,
            evals=7,
            elapsed_seconds=1.25,
            best_cost=123.0,
            best_penalized_obj=123.0,
            best_solution=solution,
            history=[{"eval": 7, "best_obj": 123.0}],
            status="completed",
            actual_moves=3,
            candidate_scores=4,
            repair_scores=3,
            repair_delta_count=3,
            operator_counts={"relocate": 2, "repair": 1},
        )

        with patch.object(formal_runner, "run_candidate", return_value=fake):
            result = formal_runner._run_algorithm_once("Alg1", FIXTURE_DIR, seed=1, eval_budget=7, max_runtime_seconds=2.0)

        self.assertEqual(result["actual_evals"], 7)
        self.assertEqual(result["actual_moves"], 3)
        self.assertEqual(result["candidate_scores"], 4)
        self.assertEqual(result["repair_scores"], 3)
        self.assertEqual(result["repair_delta_count"], 3)
        self.assertEqual(result["operator_counts"], {"relocate": 2, "repair": 1})
        self.assertIn("best_solution", result)
        self.assertIn("metrics", result)
        self.assertEqual(result["best_solution"]["routes"][0]["vehicle_id"], "CV1")

    # v2026-06-14: F2 validation finals carry the fair-budget accounting
    # counters without altering the legacy T3 table shape.
    def test_f2_final_rows_include_move_and_score_accounting(self) -> None:
        rows = [
            {
                "instance": "A",
                "algorithm": "Alg1",
                "seed": 1,
                "actual_evals": 11,
                "result": {
                    "feasible": True,
                    "best_cost": 100.0,
                    "elapsed_seconds": 1.5,
                    "actual_moves": 5,
                    "candidate_scores": 6,
                    "repair_scores": 5,
                    "repair_delta_count": 5,
                },
            }
        ]

        final_rows = _f2_final_rows(rows)

        self.assertEqual(final_rows[0]["actual_evals"], 11)
        self.assertEqual(final_rows[0]["actual_moves"], 5)
        self.assertEqual(final_rows[0]["candidate_scores"], 6)
        self.assertEqual(final_rows[0]["repair_scores"], 5)
        self.assertEqual(final_rows[0]["repair_delta_count"], 5)

    # v2026-06-14: ALNS_FIX is validation-only and writes the requested fair
    # benchmark artifacts without touching solver/reports/formal.
    def test_alns_fix_validation_writes_isolated_outputs(self) -> None:
        def fake_e2(repo_root, output_dir, *, seeds, eval_budget, max_runtime_seconds):
            _ = repo_root, seeds, eval_budget, max_runtime_seconds
            out = Path(output_dir)
            (out / "figures").mkdir(parents=True, exist_ok=True)
            (out / "tables").mkdir(parents=True, exist_ok=True)
            (out / "figures" / "f2_algorithm_finals.csv").write_text("instance,algorithm,seed\n", encoding="utf-8")
            (out / "figures" / "f2_algorithm_curves.csv").write_text("instance,algorithm,seed,evals,best_obj\n", encoding="utf-8")
            key = {
                "experiment": "E2",
                "instance": "L-main",
                "algorithm": "ALNS-Wouda",
                "seed": 1,
                "variant": "formal",
            }
            result = {
                "feasible": True,
                "best_cost": 100.0,
                "evals": 40,
                "actual_moves": 5,
                "candidate_scores": 10,
                "repair_scores": 30,
                "repair_delta_count": 30,
                "ev_routes": 2,
                "charging_event_count": 3,
                "route_count": 8,
                "elapsed_seconds": 1.2,
                "history": [],
            }
            manifest = {
                "schema_version": "setp-formal-runner-ledger.v1",
                "runs": [
                    {
                        "key": key,
                        "key_id": "E2|L-main|ALNS-Wouda|1|formal",
                        "status": "completed",
                        "elapsed_seconds": 1.2,
                        "result": result,
                        "skipped": False,
                    }
                ],
            }
            (out / "formal_runner_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            return {
                "run_count": 1,
                "manifest": str(out / "formal_runner_manifest.json"),
                "finals": [
                    {
                        "instance": "Average",
                        "ALNS-Wouda|相对已观测最优偏差\\%": 3.0,
                    }
                ],
            }

        before = {
            ("L-main", 1): {
                "instance": "L-main",
                "algorithm": "ALNS-Wouda",
                "seed": 1,
                "result": {
                    "feasible": True,
                    "best_cost": 120.0,
                    "actual_moves": 2,
                    "candidate_scores": 4,
                    "repair_scores": 20,
                    "repair_delta_count": 20,
                    "ev_routes": 1,
                    "charging_event_count": 1,
                    "route_count": 9,
                    "elapsed_seconds": 2.0,
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "alns_fix_validation"
            with patch.object(formal_runner, "run_e2_algorithm_comparison", fake_e2), patch.object(
                formal_runner,
                "_load_prior_alns_wouda_rows",
                return_value=before,
            ):
                result = formal_runner.run_alns_fix_validation(REPO_ROOT, out, seeds=[1], eval_budget=40, max_runtime_seconds=60.0)

            self.assertEqual(result["gate"], "PASS")
            self.assertTrue((out / "formal_runner_manifest.json").exists())
            self.assertTrue((out / "tables" / "alns_wouda_before_after.csv").exists())
            self.assertTrue((out / "tables" / "t3_fair_budget_algorithm_comparison.csv").exists())
            self.assertTrue((out / "figures" / "f2_fair_budget_finals.csv").exists())
            self.assertTrue((out / "figures" / "f2_fair_budget_curves.csv").exists())
            self.assertIn("Gate: `PASS`", (out / "README.md").read_text(encoding="utf-8"))
            before_after = (out / "tables" / "alns_wouda_before_after.csv").read_text(encoding="utf-8")
            self.assertIn("before", before_after)
            self.assertIn("after", before_after)

    # v2026-06-15: ALNS_ROOT_CAUSE is a diagnostic-only runner stage and must
    # delegate to the isolated root-cause output path.
    def test_alns_root_cause_stage_uses_isolated_diagnostic_runner(self) -> None:
        calls = []

        def fake_root_cause(repo_root, output_dir, *, seeds, eval_budget, max_runtime_seconds):
            calls.append(
                {
                    "repo_root": Path(repo_root),
                    "output_dir": Path(output_dir),
                    "seeds": seeds,
                    "eval_budget": eval_budget,
                    "max_runtime_seconds": max_runtime_seconds,
                }
            )
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "diagnostic_manifest.json").write_text("{}", encoding="utf-8")
            return {"gate": "PASS", "run_count": 6, "manifest": str(Path(output_dir) / "diagnostic_manifest.json")}

        with tempfile.TemporaryDirectory() as tmp, patch.object(formal_runner, "run_alns_root_cause_diagnostics", fake_root_cause):
            out = Path(tmp) / "alns_root_cause"
            code = formal_runner.main(
                [
                    "ALNS_ROOT_CAUSE",
                    "--repo-root",
                    str(REPO_ROOT),
                    "--output-dir",
                    str(out),
                    "--eval-budget",
                    "20",
                    "--max-runtime-seconds",
                    "2",
                    "--seeds",
                    "1",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(calls[0]["output_dir"], out)
            self.assertEqual(calls[0]["seeds"], [1])
            self.assertEqual(calls[0]["eval_budget"], 20)
            self.assertTrue((out / "diagnostic_manifest.json").exists())

    # v2026-06-12: W2 E7 must inherit the formal 16000-eval/300s default口径.
    def test_e7_dynamic_default_budget_matches_w2_contract(self) -> None:
        self.assertEqual(run_e7_dynamic.__kwdefaults__["eval_budget"], 16_000)
        self.assertEqual(run_e7_dynamic.__kwdefaults__["max_runtime_seconds"], 300.0)

    # v2026-06-12: W2 E5 replay must not depend on callers pre-creating the output root.
    def test_e5_formal_creates_output_directories_before_replay(self) -> None:
        def fake_ablation(bundle_dir, source_report_path, *, output_json_path, output_csv_path, halt_on_zero_delta):
            _ = bundle_dir, source_report_path, halt_on_zero_delta
            self.assertTrue(Path(output_json_path).parent.exists())
            self.assertTrue(Path(output_csv_path).parent.exists())
            payload = {
                "cost_metrics": {"E_total": 100.0, "total_cost": 50.0},
                "charging_carbon_kg": 10.0,
                "mean_intensity_gco2_per_kwh": 200.0,
            }
            return {"carbon_aware": payload, "naive_return_charge": payload}

        with tempfile.TemporaryDirectory() as tmp, patch.object(formal_runner, "run_e5_charging_ablation", fake_ablation):
            out = Path(tmp) / "missing-output-root"
            result = run_e5_formal(REPO_ROOT, out)

            self.assertIn("carbon_aware", result)
            self.assertTrue((out / "tables" / "t6_two_layer_carbon.csv").exists())

    # v2026-06-12: W2 E5 T6 is a three-party comparison; CV-only comes from the E1 counterfactual table.
    def test_e5_formal_includes_cv_only_row_from_e1_t4(self) -> None:
        def fake_ablation(bundle_dir, source_report_path, *, output_json_path, output_csv_path, halt_on_zero_delta):
            _ = bundle_dir, source_report_path, output_json_path, output_csv_path, halt_on_zero_delta
            payload = {
                "cost_metrics": {"E_total": 80.0, "total_cost": 40.0},
                "charging_carbon_kg": 8.0,
                "mean_intensity_gco2_per_kwh": 180.0,
            }
            return {"carbon_aware": payload, "naive_return_charge": payload}

        with tempfile.TemporaryDirectory() as tmp, patch.object(formal_runner, "run_e5_charging_ablation", fake_ablation):
            out = Path(tmp) / "formal"
            (out / "tables").mkdir(parents=True)
            (out / "tables" / "t4_solution_decomposition.csv").write_text(
                "metric,value,share_pct\n"
                "cv_only total_cost,123.4,\n"
                "cv_only total_carbon_kg,456.7,\n",
                encoding="utf-8",
            )

            run_e5_formal(REPO_ROOT, out)

            text = (out / "tables" / "t6_two_layer_carbon.csv").read_text(encoding="utf-8")
            self.assertIn("CV-only", text)
            self.assertIn("456.7", text)

    # v2026-06-12: W2a proves E3 changes the carbon table, not only labels variants.
    def test_e3_carbon_profiles_zero_mean_actual_semantics(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        gamma_values = [float(row["actual_gco2_per_kwh"]) for row in bundle.carbon_profile]
        mean_gamma = sum(gamma_values) / len(gamma_values)
        slot_index = max(range(len(gamma_values)), key=lambda idx: abs(gamma_values[idx] - mean_gamma))
        action = ChargingAction("EV1", _first_depot_id(bundle), 10.0, 30.0, float(bundle.carbon_profile[slot_index]["horizon_second_start"]))
        solution = Solution(
            routes=[Route("EV1", "ev", _first_depot_id(bundle), [_first_depot_id(bundle), _first_customer_id(bundle), _first_depot_id(bundle)])],
            charging_actions=[action],
        )

        zero_metrics = evaluate(solution, bundle.instance, _derive_carbon_profile(bundle.carbon_profile, "zero_gamma"), DEFAULT_PRICES, carbon_quota_kg=math.inf)
        mean_metrics = evaluate(solution, bundle.instance, _derive_carbon_profile(bundle.carbon_profile, "mean_gamma"), DEFAULT_PRICES, carbon_quota_kg=math.inf)
        actual_metrics = evaluate(solution, bundle.instance, _derive_carbon_profile(bundle.carbon_profile, "actual_gamma"), DEFAULT_PRICES, carbon_quota_kg=math.inf)

        self.assertEqual(zero_metrics["E_ev_indirect"], 0.0)
        self.assertAlmostEqual(mean_metrics["E_ev_indirect"], 10.0 * mean_gamma / 1000.0, places=9)
        self.assertNotAlmostEqual(actual_metrics["E_ev_indirect"], mean_metrics["E_ev_indirect"], places=6)
        self.assertEqual(mean_metrics["cost_carbon"], 0.0)
        self.assertEqual(actual_metrics["cost_carbon"], 0.0)

    # v2026-06-12: W2a carbon trading enters only at finite CE and keeps buy/sell sign.
    def test_e3_carbon_trading_cost_activates_only_with_finite_quota(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        action = ChargingAction("EV1", _first_depot_id(bundle), 5.0, 30.0, 0.0)
        solution = Solution(
            routes=[Route("EV1", "ev", _first_depot_id(bundle), [_first_depot_id(bundle), _first_customer_id(bundle), _first_depot_id(bundle)])],
            charging_actions=[action],
        )
        metrics = evaluate(solution, bundle.instance, _derive_carbon_profile(bundle.carbon_profile, "mean_gamma"), DEFAULT_PRICES, carbon_quota_kg=math.inf)
        self.assertEqual(metrics["cost_carbon"], 0.0)

        emissions = float(metrics["E_total"])
        buy = evaluate(solution, bundle.instance, _derive_carbon_profile(bundle.carbon_profile, "mean_gamma"), DEFAULT_PRICES, carbon_quota_kg=emissions - 0.1)
        sell = evaluate(solution, bundle.instance, _derive_carbon_profile(bundle.carbon_profile, "mean_gamma"), DEFAULT_PRICES, carbon_quota_kg=emissions + 0.1)

        self.assertGreater(buy["cost_carbon"], 0.0)
        self.assertLess(sell["cost_carbon"], 0.0)

    # v2026-06-12: W2a follows paper_main.tex line 295: no-trading means p_car=0;
    # CE=inf remains a verified safe code sentinel, not the official E3 switch.
    def test_e3_no_carbon_trading_switch_matches_paper_and_ce_inf_is_safe(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        action = ChargingAction("EV1", _first_depot_id(bundle), 5.0, 30.0, 0.0)
        solution = Solution(
            routes=[Route("EV1", "ev", _first_depot_id(bundle), [_first_depot_id(bundle), _first_customer_id(bundle), _first_depot_id(bundle)])],
            charging_actions=[action],
        )
        profile = _derive_carbon_profile(bundle.carbon_profile, "mean_gamma")
        no_trade_prices = _prices_with_carbon_price_factor(0.0)

        no_trade = evaluate(solution, bundle.instance, profile, no_trade_prices, carbon_quota_kg=0.0)
        finite_trade = evaluate(solution, bundle.instance, profile, DEFAULT_PRICES, carbon_quota_kg=float(no_trade["E_total"]) - 0.1)
        ce_inf = evaluate(solution, bundle.instance, profile, DEFAULT_PRICES, carbon_quota_kg=math.inf)
        depot_rows = calculate_depot_profits(solution, bundle.instance, profile, DEFAULT_PRICES, carbon_quota_kg=math.inf)

        self.assertGreater(no_trade["E_total"], 0.0)
        self.assertEqual(no_trade["cost_carbon"], 0.0)
        self.assertGreater(finite_trade["cost_carbon"], 0.0)
        self.assertEqual(ce_inf["cost_carbon"], 0.0)
        self.assertTrue(all(math.isfinite(row.cost_carbon) for row in depot_rows.values()))
        self.assertEqual(sum(row.cost_carbon for row in depot_rows.values()), 0.0)

    # v2026-06-12: W2a cooperative variants must record cross-site service costs when they occur.
    def test_derive_cross_site_services_counts_non_home_customers(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        owners = infer_customer_home_depots(bundle.instance)
        depots = sorted(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d")
        customer_id, home_depot = next(iter(owners.items()))
        other_depot = next(depot for depot in depots if depot != home_depot)
        raw = Solution(routes=[Route("CV1", "cv", other_depot, [other_depot, customer_id, other_depot])])

        derived = _derive_cross_site_services(raw, bundle.instance, owners)
        metrics = evaluate(derived, bundle.instance, bundle.carbon_profile)

        self.assertEqual(len(derived.cross_site_services), 1)
        self.assertEqual(derived.cross_site_services[0].customer_id, customer_id)
        self.assertEqual(derived.cross_site_services[0].served_by_depot_id, other_depot)
        self.assertEqual(metrics["cost_transship"], DEFAULT_PRICES.cross_site_cost)

    # v2026-06-12: W2a runner variants encode real ablation semantics, not display labels.
    def test_e3_variant_specs_lock_real_ablation_semantics(self) -> None:
        specs = {spec["code"]: spec for spec in _e3_variant_specs(123.0)}

        self.assertTrue(specs["M0"]["independent"])
        self.assertEqual(specs["M0"]["carbon_profile_mode"], "zero_gamma")
        self.assertEqual(specs["M1"]["carbon_profile_mode"], "zero_gamma")
        self.assertEqual(specs["M2"]["carbon_profile_mode"], "mean_gamma")
        self.assertEqual(specs["M3"]["carbon_profile_mode"], "actual_gamma")
        for code in ("M0", "M1", "M2", "M3"):
            self.assertEqual(specs[code]["carbon_price_factor"], 0.0)
            self.assertEqual(specs[code]["carbon_weight"], 0.0)
            self.assertEqual(specs[code]["carbon_quota_kg"], 0.0)
        self.assertEqual(specs["M4"]["carbon_quota_kg"], 123.0)
        self.assertEqual(specs["M4"]["carbon_price_factor"], 1.0)
        self.assertTrue(specs["M5"]["fairness_enabled"])
        self.assertEqual(specs["M5"]["carbon_price_factor"], 1.0)
        self.assertEqual(
            {code: specs[code]["label"] for code in ("M0", "M1", "M2", "M3", "M4", "M5")},
            {
                "M0": "无多场协同",
                "M1": "无碳感知",
                "M2": "均值碳强度",
                "M3": "无碳交易",
                "M4": "无收益公平",
                "M5": "完整模型",
            },
        )

    # v2026-06-13: R2 cooperative E3 layers must all start from the concatenated
    # independent seed so the ablation variable is not confounded by construction.
    def test_e3_cooperative_variant_uses_concatenated_seed(self) -> None:
        seed_solution = Solution(routes=[Route("CV1", "cv", "D0", ["D0", "C1", "D0"])])
        spec = next(item for item in _e3_variant_specs(123.0) if item["code"] == "M1")

        def fake_seed(*args, **kwargs):
            _ = args, kwargs
            return {
                "initial_solution": seed_solution,
                "seed_recipe": "concatenated_independent_seed",
                "initial_seed_metrics": {"total_cost": 10.0},
            }

        def fake_run(*args, **kwargs):
            self.assertIs(kwargs["initial_solution"], seed_solution)
            return {"feasible": True, "best_cost": 9.0, "metrics": {"E_total": 4.0}}

        with tempfile.TemporaryDirectory() as tmp, patch.object(formal_runner, "_build_e3_concatenated_seed", fake_seed), patch.object(formal_runner, "_run_alns_metrics", fake_run):
            result = formal_runner._run_e3_variant(FIXTURE_DIR, Path(tmp), spec, seed=1, eval_budget=10, max_runtime_seconds=1.0)

        self.assertEqual(result["seed_recipe"], "concatenated_independent_seed")

    # v2026-06-13: R2 T5 needs emissions because M1/M2 can have identical costs
    # when carbon price is zero.
    def test_e3_table_rows_include_total_emissions(self) -> None:
        rows = [
            {"variant": "M5", "label": "full", "status": "completed", "result": {"feasible": True, "best_cost": 10.0, "metrics": {"E_total": 5.0}}},
            {"variant": "M1", "label": "cooperative", "status": "completed", "result": {"feasible": True, "best_cost": 11.0, "metrics": {"E_total": 7.0}}},
        ]

        table = _e3_table_rows(rows)

        m1 = next(row for row in table if row["step"].startswith("M1 "))
        self.assertEqual(m1["E_total_kg"], 7.0)

    # v2026-06-13: R2 E4 is a 16-combination by 5-seed experiment and records
    # the objective carbon price used by each run before any backfill.
    def test_e4_carbon_sensitivity_runs_five_seeds_and_writes_diagnostics(self) -> None:
        def fake_once(*args, **kwargs):
            _ = args
            price_factor = kwargs["price_factor"]
            quota_factor = kwargs["quota_factor"]
            seed = kwargs["seed"]
            return {
                "feasible": True,
                "actual_evals": 10,
                "elapsed_seconds": 1.0,
                "best_cost": 100.0 + seed,
                "metrics": {
                    "total_cost": 100.0 + seed,
                    "fuel_liters": 1.0,
                    "cost_elec": 2.0,
                    "cost_carbon": 3.0,
                    "E_total": 4.0 + price_factor + quota_factor,
                },
                "ev_routes": 1,
                "objective_carbon_price": 0.1 * price_factor,
                "price_factor": price_factor,
                "quota_factor": quota_factor,
            }

        with tempfile.TemporaryDirectory() as tmp, patch.object(formal_runner, "compute_default_carbon_quota", return_value={"baseline_emissions_kg": 100.0}), patch.object(formal_runner, "_run_e4_once", fake_once):
            result = run_e4_carbon_sensitivity(REPO_ROOT, Path(tmp), seeds=[1, 2, 3, 4, 5], eval_budget=10, max_runtime_seconds=1.0)
            diagnostics = (Path(tmp) / "tables" / "e4_carbon_price_diagnostics.csv").read_text(encoding="utf-8")

        self.assertEqual(result["run_count"], 80)
        self.assertIn("objective_carbon_price", diagnostics)
        self.assertIn("seed", diagnostics)

    # v2026-06-13: R2 E7 failures must identify the first bad stage and
    # constraint fields instead of only returning final feasible=False.
    def test_dynamic_stage_failure_payload_contains_violation_details(self) -> None:
        from setp_solver.check import Violation
        from setp_solver.search.dynamic import dynamic_stage_failure_payload_for_test

        payload = dynamic_stage_failure_payload_for_test(
            3,
            [Violation("CUSTOMER_COVERAGE", "", "C7", "customer not served")],
        )

        self.assertEqual(payload["gate"], "HALT_E7_STAGE_CHECK")
        self.assertEqual(payload["first_bad_stage"], 3)
        self.assertEqual(payload["violations"][0]["constraint_type"], "CUSTOMER_COVERAGE")
        self.assertEqual(payload["violations"][0]["nodes"], "C7")

    # v2026-06-13: R2 E7 slicing must not copy station actions from the parent
    # stage route when the station is not present in the committed chunk.
    def test_dynamic_customer_subset_replays_charging_instead_of_copying_stale_station_actions(self) -> None:
        instance = _synthetic_dynamic_instance(
            [
                ("C1", 100.0, 1_000.0, 0.0),
                ("C2", 100.0, 2_000.0, 0.0),
            ],
            stations=[("F1", 1_500.0, 0.0)],
        )
        plan = Solution(
            routes=[Route("EV1", "ev", "D0", ["D0", "C1", "F1", "C2", "D0"])],
            charging_actions=[ChargingAction("EV1", "F1", 10.0, 30.0, 3_600.0)],
        )

        chunk = _solution_for_customer_subset(
            plan,
            instance,
            _flat_carbon_profile(),
            {"C1"},
            prefix="S1_",
        )

        route_nodes = {node_id for route in chunk.routes for node_id in route.node_sequence}
        self.assertNotIn("F1", route_nodes)
        self.assertTrue(all(action.station_id in route_nodes for action in chunk.charging_actions))
        self.assertEqual(check_solution(chunk, _subinstance_for_test(instance, {"C1"}), DEFAULT_PRICES), [])

    # v2026-06-13: R2 E7 committed chunks are checked as closed routes, so a
    # subset whose current demand exceeds Q must be split before final assembly.
    def test_dynamic_customer_subset_splits_over_capacity_committed_chunk(self) -> None:
        instance = _synthetic_dynamic_instance(
            [
                ("C1", 900.0, 1_000.0, 0.0),
                ("C2", 900.0, 2_000.0, 0.0),
            ],
            stations=[],
        )
        plan = Solution(routes=[Route("CV1", "cv", "D0", ["D0", "C1", "C2", "D0"])])

        chunk = _solution_for_customer_subset(
            plan,
            instance,
            _flat_carbon_profile(),
            {"C1", "C2"},
            prefix="S2_",
        )

        self.assertEqual(len(chunk.routes), 2)
        self.assertEqual(check_solution(chunk, _subinstance_for_test(instance, {"C1", "C2"}), DEFAULT_PRICES), [])

    # v2026-06-13: R2 E7 EV chunk extraction must rebuild charging for the
    # shortened route because inherited actions no longer match the route body.
    def test_dynamic_customer_subset_repairs_ev_battery_after_slicing(self) -> None:
        instance = _synthetic_dynamic_instance(
            [("C1", 100.0, 10_000.0, 0.0)],
            stations=[("F1", 5_000.0, 0.0)],
        )
        plan = Solution(routes=[Route("EV1", "ev", "D0", ["D0", "F1", "C1", "D0"])])

        chunk = _solution_for_customer_subset(
            plan,
            instance,
            _flat_carbon_profile(),
            {"C1"},
            prefix="S3_",
        )

        self.assertTrue(chunk.charging_actions)
        self.assertEqual(check_solution(chunk, _subinstance_for_test(instance, {"C1"}), DEFAULT_PRICES), [])

    # v2026-06-13: R2 E7 must not report success when the final assembled dynamic
    # control fails the same checker used by the static control.
    def test_dynamic_report_halts_when_final_dynamic_check_fails(self) -> None:
        from setp_solver.check import Violation

        violation = Violation("BATTERY", "EV1", "C1->D0", "battery below zero")

        def fake_stage_plan(*args, **kwargs):
            _ = args, kwargs
            bundle = load_search_bundle(FIXTURE_DIR)
            return StagePlanResult(Solution(), bundle.instance, 0, True, [])

        with patch.object(dynamic_module, "load_or_generate_dynamic_events", return_value=[]), patch.object(
            dynamic_module, "_run_stage_plan", fake_stage_plan
        ), patch.object(dynamic_module, "run_alns_wouda", return_value=SimpleNamespace(best_solution=Solution(), feasible=True, evaluations=0)), patch.object(
            dynamic_module, "evaluate", return_value={"total_cost": 100.0, "E_total": 10.0}
        ), patch.object(dynamic_module, "_active_customer_ids", return_value=set()), patch.object(dynamic_module, "check_solution", side_effect=[[violation], []]):
            report = run_rolling_reoptimization(FIXTURE_DIR, seed=1, eval_budget=1, stage_eval_budget=1)

        self.assertEqual(report["gate"], "HALT_E7_FINAL_CHECK")
        self.assertEqual(report["violations"][0]["constraint_type"], "BATTERY")

    # v2026-06-12: Z3 event defaults should generate the configured event families.
    def test_dynamic_event_generation_uses_default_families(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        events = generate_dynamic_events(bundle.instance, seed=1, params=RollingParameters(stages=3))

        event_types = {event.event_type for event in events}

        self.assertIn("add", event_types)
        self.assertIn("cancel", event_types)
        self.assertIn("demand_change", event_types)
        add_event = next(event for event in events if event.event_type == "add")
        self.assertIsInstance(add_event.x, float)
        self.assertGreater(add_event.new_due_time, add_event.new_ready_time)

    # v2026-06-12: W2b generator-style TSV events must round-trip all fields used to create new customers.
    def test_dynamic_event_reader_accepts_generator_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dynamic_events.tsv"
            path.write_text(
                "event_id\tevent_type\tt_appear\tcustomer_id\tx\ty\told_demand\tnew_demand\tdelta_demand\told_ready_time\told_due_time\tnew_ready_time\tnew_due_time\ttime_window_action\tdemand_source\ttime_window_source\tdonor_instance_id\tdonor_customer_id\tsource\tseed\n"
                "1\tadd\t7200\tN1\t11.0\t12.0\t0.0\t80.0\t80.0\t300.0\t9000.0\t300.0\t9000.0\tnone\tdonor_inherited\tdonor_inherited\tE-UK150_08\tC37\tgoeke_donor_overlay\t1\n",
                encoding="utf-8",
            )

            events = formal_runner.dynamic_read_events_for_test(path)

            self.assertEqual(events[0].customer_id, "N1")
            self.assertEqual(events[0].x, 11.0)
            self.assertEqual(events[0].donor_customer_id, "C37")

    # v2026-06-12: W2b qbar is a real trigger and is allowed to create more than five stages.
    def test_dynamic_qbar_trigger_can_exceed_five_stages(self) -> None:
        events = [
            formal_runner.dynamic_event_for_test(str(idx), "demand_change", float(idx * 100), f"C{idx}", new_demand=10.0)
            for idx in range(1, 49)
        ]

        batches = formal_runner.dynamic_trigger_batches_for_test(events, RollingParameters(delta_t_seconds=10_800.0, q_bar=8))

        self.assertGreater(len(batches), 5)
        self.assertTrue(any(batch["trigger_reason"] == "q_bar" for batch in batches))

    # v2026-06-12: W2b added customers may not appear in plans before their arrival.
    def test_dynamic_new_customer_visible_only_after_arrival(self) -> None:
        bundle = load_search_bundle(FIXTURE_DIR)
        event = formal_runner.dynamic_event_for_test("1", "add", 7200.0, "N1", x=10.0, y=10.0, new_demand=50.0, new_ready_time=7200.0, new_due_time=20_000.0)

        before = formal_runner.dynamic_active_customer_ids_for_test(bundle.instance, [event], trigger_time=3600.0, already_served=set())
        after = formal_runner.dynamic_active_customer_ids_for_test(bundle.instance, [event], trigger_time=7200.0, already_served=set())

        self.assertNotIn("N1", before)
        self.assertIn("N1", after)

    # v2026-06-12: W2b dynamic and full-information static controls must be scored by the same evaluator.
    def test_dynamic_report_declares_same_scorer_for_dynamic_and_static(self) -> None:
        report = run_rolling_reoptimization(
            FIXTURE_DIR,
            seed=1,
            eval_budget=5,
            max_runtime_seconds=60.0,
            stage_eval_budget=3,
            stage_max_runtime_seconds=60.0,
            params=RollingParameters(delta_t_seconds=3600.0, q_bar=2),
        )

        self.assertEqual(report["dynamic_final_control"]["scorer"], "setp_solver.cost.evaluate")
        self.assertEqual(report["static_revealed_control"]["scorer"], "setp_solver.cost.evaluate")

    # v2026-07-01: Track20 policy hook must default to the old myopic active
    # customer set when the callback returns no stage override.
    def test_dynamic_myopic_policy_callback_keeps_stage_active_set(self) -> None:
        captured: list[set[str]] = []

        def fake_stage_plan(*args, **kwargs):
            _bundle, instance, active_ids = args[:3]
            captured.append(set(active_ids))
            return StagePlanResult(Solution(), instance, 0, True, [])

        with patch.object(dynamic_module, "load_or_generate_dynamic_events", return_value=[]), patch.object(
            dynamic_module, "_active_customer_ids", return_value={"C1", "C2"}
        ), patch.object(dynamic_module, "_run_stage_plan", fake_stage_plan), patch.object(
            dynamic_module, "run_alns_wouda", return_value=SimpleNamespace(best_solution=Solution(), feasible=True, evaluations=0)
        ), patch.object(dynamic_module, "evaluate", return_value={"total_cost": 100.0, "E_total": 10.0}), patch.object(
            dynamic_module, "check_solution", return_value=[]
        ):
            report = run_rolling_reoptimization(FIXTURE_DIR, seed=1, eval_budget=1, stage_eval_budget=1, policy_callback=myopic_rolling_policy)

        self.assertEqual(captured[0], {"C1", "C2"})
        self.assertEqual(report["policy_trace"][0]["deferred_count"], 0)

    # v2026-07-01: Track20 policy hook is allowed to defer a strict subset of
    # currently active customers, and the action is auditable in policy_trace.
    def test_dynamic_policy_callback_can_defer_stage_customers(self) -> None:
        captured: list[set[str]] = []

        def fake_stage_plan(*args, **kwargs):
            _bundle, instance, active_ids = args[:3]
            captured.append(set(active_ids))
            return StagePlanResult(Solution(), instance, 0, True, [])

        def defer_one(context):
            chosen = {sorted(context.active_ids)[0]}
            return RollingPolicyDecision(active_ids=chosen, metadata={"action": "defer_one"})

        with patch.object(dynamic_module, "load_or_generate_dynamic_events", return_value=[]), patch.object(
            dynamic_module, "_active_customer_ids", return_value={"C1", "C2"}
        ), patch.object(dynamic_module, "_run_stage_plan", fake_stage_plan), patch.object(
            dynamic_module, "run_alns_wouda", return_value=SimpleNamespace(best_solution=Solution(), feasible=True, evaluations=0)
        ), patch.object(dynamic_module, "evaluate", return_value={"total_cost": 100.0, "E_total": 10.0}), patch.object(
            dynamic_module, "check_solution", return_value=[]
        ):
            report = run_rolling_reoptimization(FIXTURE_DIR, seed=1, eval_budget=1, stage_eval_budget=1, policy_callback=defer_one)

        self.assertEqual(len(captured[0]), 1)
        self.assertEqual(report["policy_trace"][0]["deferred_count"], 1)
        self.assertEqual(report["policy_trace"][0]["metadata"]["action"], "defer_one")

    # v2026-07-06: Track24-R policy defer must keep skipped customers in the
    # runner's pending queue instead of making them disappear from later stages.
    def test_dynamic_policy_defer_keeps_customer_pending_until_later_stage(self) -> None:
        instance = _synthetic_dynamic_instance([("C1", 1.0, 10.0, 0.0), ("C2", 1.0, 20.0, 0.0)], stations=[])
        bundle = SimpleNamespace(instance=instance, carbon_profile=_flat_carbon_profile(), bundle_dir=str(FIXTURE_DIR))
        captured: list[set[str]] = []

        def fake_stage_plan(*args, **kwargs):
            _bundle, _instance, active_ids = args[:3]
            captured.append(set(active_ids))
            routes = []
            if active_ids:
                routes.append(Route(f"CV{len(captured)}", "cv", "D0", ["D0", *sorted(active_ids), "D0"]))
            return StagePlanResult(Solution(routes=routes), instance, 1, True, [])

        def defer_first_stage(context):
            if context.stage_index == 0:
                return RollingPolicyDecision(active_ids={"C1"}, metadata={"action": "defer_c2"})
            return RollingPolicyDecision(metadata={"action": "serve_pending"})

        event = formal_runner.dynamic_event_for_test("1", "demand_change", 1.0, "C1", new_demand=1.0)
        with tempfile.TemporaryDirectory() as tmp, patch.object(dynamic_module, "load_search_bundle", return_value=bundle), patch.object(
            dynamic_module, "load_or_generate_dynamic_events", return_value=[event]
        ), patch.object(dynamic_module, "_active_customer_ids", side_effect=[{"C1", "C2"}, set(), set()]), patch.object(
            dynamic_module, "_run_stage_plan", fake_stage_plan
        ), patch.object(
            dynamic_module, "run_alns_wouda", return_value=SimpleNamespace(best_solution=Solution(), feasible=True, evaluations=0)
        ), patch.object(
            dynamic_module, "evaluate", return_value={"total_cost": 100.0, "E_total": 10.0}
        ), patch.object(dynamic_module, "check_solution", return_value=[]):
            report = run_rolling_reoptimization(
                FIXTURE_DIR,
                output_json_path=Path(tmp) / "payload.json",
                seed=1,
                eval_budget=1,
                stage_eval_budget=1,
                policy_callback=defer_first_stage,
                params=RollingParameters(delta_t_seconds=2.0, q_bar=8),
            )

        self.assertEqual(captured[0], {"C1"})
        self.assertIn("C2", captured[1])
        self.assertEqual(report["policy_trace"][0]["new_deferred_count"], 1)
        self.assertEqual(report["policy_trace"][1]["pending_count_before"], 1)

    # v2026-07-06: final remaining customers may be absent from the previous
    # stage plan; they need a final repair/reoptimization, not a plan slice.
    def test_dynamic_final_repair_services_customer_absent_from_previous_plan(self) -> None:
        report, calls = _run_final_repair_scenario()

        self.assertNotIn("gate", report)
        self.assertEqual(calls[0], {"C1"})
        self.assertIn("C2", calls[1])
        self.assertEqual(report["dynamic_final_control"]["violations"], [])

    # v2026-07-06: active-subset decisions must not drop per-stage budget
    # overrides; Track24 stage_budget_event_density depends on both fields.
    def test_policy_decision_preserves_active_subset_and_budget_override(self) -> None:
        instance = _synthetic_dynamic_instance([("C1", 1.0, 10.0, 0.0), ("C2", 1.0, 20.0, 0.0)], stations=[])

        def choose_one(_context):
            return RollingPolicyDecision(active_ids={"C1"}, stage_eval_budget=17, stage_max_runtime_seconds=3.5)

        decision = dynamic_module._policy_decision_for_stage(
            choose_one,
            stage_index=0,
            trigger=0.0,
            stage_events=[],
            events=[],
            settings=RollingParameters(),
            base_instance=instance,
            effective_instance=instance,
            active_ids={"C1", "C2"},
            served_customers=set(),
            previous_plan=None,
            previous_instance=None,
        )

        self.assertEqual(decision.active_ids, {"C1"})
        self.assertEqual(decision.stage_eval_budget, 17)
        self.assertEqual(decision.stage_max_runtime_seconds, 3.5)

    # v2026-07-06: dict callbacks are part of the public hook; they need the
    # same budget-preservation path as RollingPolicyDecision objects.
    def test_dict_policy_decision_preserves_budget_override(self) -> None:
        instance = _synthetic_dynamic_instance([("C1", 1.0, 10.0, 0.0), ("C2", 1.0, 20.0, 0.0)], stations=[])

        def choose_one(_context):
            return {"active_ids": {"C1"}, "stage_eval_budget": 19, "stage_max_runtime_seconds": 4.5}

        decision = dynamic_module._policy_decision_for_stage(
            choose_one,
            stage_index=0,
            trigger=0.0,
            stage_events=[],
            events=[],
            settings=RollingParameters(),
            base_instance=instance,
            effective_instance=instance,
            active_ids={"C1", "C2"},
            served_customers=set(),
            previous_plan=None,
            previous_instance=None,
        )

        self.assertEqual(decision.active_ids, {"C1"})
        self.assertEqual(decision.stage_eval_budget, 19)
        self.assertEqual(decision.stage_max_runtime_seconds, 4.5)

    # v2026-07-06: Track24-R payloads need enough counters to audit whether
    # defer and final repair semantics were used.
    def test_dynamic_payload_reports_pending_and_final_repair_counts(self) -> None:
        report, _calls = _run_final_repair_scenario()

        self.assertEqual(report["policy_trace"][0]["pending_count_before"], 0)
        self.assertEqual(report["policy_trace"][0]["new_deferred_count"], 1)
        self.assertEqual(report["policy_trace"][0]["pending_count_after"], 1)
        self.assertEqual(report["final_repair_customer_count"], 2)
        self.assertGreaterEqual(report["final_repair_evaluations"], 1)
        self.assertEqual(report["final_repair_violation_count"], 0)

    # v2026-07-06: final repair has its own legality gate so true infeasible
    # repair output is not mislabeled as a generic final chunk failure.
    def test_dynamic_final_repair_halts_on_repair_violation(self) -> None:
        report, _calls = _run_final_repair_scenario(final_repair_empty=True)

        self.assertEqual(report["gate"], "HALT_E7_FINAL_REPAIR_CHECK")
        self.assertEqual(report["first_bad_stage"], "final_repair")
        self.assertEqual(report["final_repair_violation_count"], 1)

    # v2026-06-12: E7 rolling gate must preserve cumulative-state continuity and frozen paths.
    def test_dynamic_rolling_gate_conservation_assertions_pass(self) -> None:
        report = run_rolling_reoptimization(
            FIXTURE_DIR,
            seed=1,
            eval_budget=5,
            max_runtime_seconds=60.0,
            params=RollingParameters(stages=3, delta_t_seconds=3600.0),
        )

        self.assertTrue(report["all_assertions_pass"])
        self.assertGreaterEqual(report["trigger_count"], 1)
        self.assertEqual(report["stage_rows"][-1]["stage"], "dynamic_vs_static")
        self.assertTrue(all(row["feasible"] for row in report["stage_rows"] if row["stage"] != "dynamic_vs_static"))

    # v2026-06-12: E0 gate writer gives the formal T1 source a deterministic shape.
    def test_e0_gate_writes_t1_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_e0_gate(REPO_ROOT, Path(tmp) / "t1_instances.csv")

            self.assertEqual(result["gate"], "PASS")
            self.assertEqual(len(result["rows"]), 2)


def _run_final_repair_scenario(*, final_repair_empty: bool = False) -> tuple[dict[str, object], list[set[str]]]:
    from setp_solver.check import Violation

    instance = _synthetic_dynamic_instance([("C1", 1.0, 10.0, 0.0), ("C2", 1.0, 20.0, 0.0)], stations=[])
    bundle = SimpleNamespace(instance=instance, carbon_profile=_flat_carbon_profile(), bundle_dir=str(FIXTURE_DIR))
    calls: list[set[str]] = []

    def fake_stage_plan(*args, **kwargs):
        _bundle, _instance, active_ids = args[:3]
        calls.append(set(active_ids))
        routes = []
        if active_ids and not (final_repair_empty and len(calls) == 2):
            routes.append(Route(f"CV{len(calls)}", "cv", "D0", ["D0", *sorted(active_ids), "D0"]))
        return StagePlanResult(Solution(routes=routes), instance, 1, True, [])

    def defer_c2(_context):
        return RollingPolicyDecision(active_ids={"C1"}, metadata={"action": "defer_c2"})

    def coverage_check(solution, checked_instance, prices=DEFAULT_PRICES):
        _ = prices
        expected = {
            node.node_id
            for node in checked_instance.nodes
            if node.node_type.lower() == "c" and float(node.demand) > 1e-9
        }
        served = {
            node_id
            for route in solution.routes
            for node_id in route.node_sequence
            if node_id in expected
        }
        missing = sorted(expected - served)
        if missing:
            return [Violation("CUSTOMER_COVERAGE", "", missing[0], "customer not served")]
        return []

    with tempfile.TemporaryDirectory() as tmp, patch.object(dynamic_module, "load_search_bundle", return_value=bundle), patch.object(
        dynamic_module, "load_or_generate_dynamic_events", return_value=[]
    ), patch.object(dynamic_module, "_active_customer_ids", return_value={"C1", "C2"}), patch.object(
        dynamic_module, "_run_stage_plan", fake_stage_plan
    ), patch.object(
        dynamic_module, "run_alns_wouda", return_value=SimpleNamespace(best_solution=Solution(routes=[Route("CVS", "cv", "D0", ["D0", "C1", "C2", "D0"])]), feasible=True, evaluations=0)
    ), patch.object(
        dynamic_module, "evaluate", return_value={"total_cost": 100.0, "E_total": 10.0}
    ), patch.object(dynamic_module, "check_solution", side_effect=coverage_check):
        report = run_rolling_reoptimization(
            FIXTURE_DIR,
            output_json_path=Path(tmp) / "payload.json",
            seed=1,
            eval_budget=1,
            stage_eval_budget=1,
            policy_callback=defer_c2,
        )

    return report, calls


def _first_depot_id(bundle) -> str:
    return next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d")


def _first_customer_id(bundle) -> str:
    return next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c")


def _synthetic_dynamic_instance(
    customers: list[tuple[str, float, float, float]],
    *,
    stations: list[tuple[str, float, float]],
) -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, ready_time=0.0, due_time=86_400.0, service_time=0.0, charge_power_kw=22.0, station_chargers=10),
    ]
    nodes.extend(Node(node_id, "c", x, y, demand=demand, ready_time=0.0, due_time=86_400.0, service_time=0.0) for node_id, demand, x, y in customers)
    nodes.extend(Node(node_id, "f", x, y, ready_time=0.0, due_time=86_400.0, service_time=0.0, charge_power_kw=50.0, station_chargers=1) for node_id, x, y in stations)
    matrix = [[float(((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5) for b in nodes] for a in nodes]
    return Instance(nodes=nodes, distance_matrix=matrix)


def _subinstance_for_test(instance: Instance, customer_ids: set[str]) -> Instance:
    keep = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() in {"d", "f"} or (node.node_type.lower() == "c" and node.node_id in customer_ids)
    }
    nodes = [node for node in instance.nodes if node.node_id in keep]
    source_index = instance.node_index
    matrix = [[float(instance.distance_matrix[source_index[a.node_id]][source_index[b.node_id]]) for b in nodes] for a in nodes]
    return Instance(nodes=nodes, distance_matrix=matrix)


def _flat_carbon_profile() -> list[dict[str, object]]:
    return [
        {
            "time_index": idx,
            "datetime_utc": "",
            "actual_gco2_per_kwh": 200.0,
            "forecast_gco2_per_kwh": 200.0,
            "index_label": "",
            "index_code": idx,
            "horizon_second_start": float(idx * 1_800),
        }
        for idx in range(48)
    ]


if __name__ == "__main__":
    unittest.main()
